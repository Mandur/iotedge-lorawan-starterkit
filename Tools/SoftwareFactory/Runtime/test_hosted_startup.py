# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""Real non-root HTTP readiness and restart, with no Azure or model requests."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from coding_agent import Workspace


class RuntimeStartupTests(unittest.TestCase):
    def test_empty_mounted_home_contract(self):
        """Run with a fresh tmpfs over HOME, never with an existing persisted session."""
        if os.environ.get("FACTORY_TEST_MOUNT") not in {"writable", "nonwritable"}:
            self.skipTest("Requires an explicitly supplied disposable session mount.")
        root = Path("/home/session/factory-workspace")
        self.assertFalse(root.exists())
        environment = {**os.environ, "HOME": "/home/session", "FACTORY_HOSTED": "1",
                       "FACTORY_WORKSPACE": str(root), "FACTORY_REPOSITORY_COMMIT": "a" * 40,
                       "AZURE_CLIENT_SECRET": "diagnostic-must-not-print-this"}
        script = """
import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
from server import prepare_workspace
with patch('server.run_process', new_callable=AsyncMock) as git:
    git.return_value = {'exit_code': 0, 'output': ''}
    workspace = asyncio.run(prepare_workspace())
    assert workspace.root.stat().st_mode & 0o777 == 0o700
    assert git.await_count == 4
    (workspace.root / 'kept.txt').write_text('preserved edit')
    git.return_value = {'exit_code': 0, 'output': 'a' * 40 + '\\n'}
    resumed = asyncio.run(prepare_workspace())
    assert (resumed.root / 'kept.txt').read_text() == 'preserved edit'
    assert git.await_count == 5
"""
        environment.pop("FACTORY_WORKSPACE")
        result = subprocess.run([sys.executable, "-c", script], env=environment,
                                capture_output=True, text=True, timeout=15)
        if os.environ["FACTORY_TEST_MOUNT"] == "writable":
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(root.is_dir())
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("platform must provide write access", result.stderr)
            diagnostic = json.loads(result.stderr.splitlines()[0])
            self.assertEqual(diagnostic["operation"], "mkdir")
            self.assertEqual(diagnostic["effective_uid"], 1654)
            self.assertEqual(diagnostic["effective_gid"], 1654)
            self.assertEqual(diagnostic["home"], {
                "path": "/home/session", "uid": 0, "gid": 0, "mode": "0755"})
            self.assertEqual(diagnostic["workspace"]["stat_errno"], 2)
            self.assertEqual(diagnostic["errno"], 13)
            self.assertNotIn(environment["AZURE_CLIENT_SECRET"], result.stderr)
            self.assertFalse(root.exists())

    def test_local_runtime_workspace_readiness_and_restart(self):
        root = Path("/home/session/factory-workspace")
        self.assertNotEqual(os.geteuid(), 0)
        self.assertFalse(os.access(root.parent, os.W_OK))
        self.assertEqual(root.stat().st_uid, os.geteuid())
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        state = root.parent / ".agentserver"
        self.assertEqual(state.stat().st_uid, os.geteuid())
        self.assertEqual(state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(root.iterdir()), [])
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Factory Test",
                        "-c", "user.email=factory@example.invalid", "commit",
                        "--allow-empty", "-qm", "Startup fixture"], check=True)
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = {**os.environ, "HOME": str(root.parent), "FACTORY_EXECUTION_BACKEND": "local",
                       "FACTORY_WORKSPACE": str(root), "FACTORY_REPOSITORY_COMMIT": commit,
                       "FACTORY_ENABLE_EXECUTION": "0", "PORT": str(port)}
        environment.pop("FACTORY_MODEL_TOKEN", None)
        environment.pop("FACTORY_HOSTED", None)
        launcher = """
import asyncio
from contextlib import asynccontextmanager
import server
@asynccontextmanager
async def no_model():
    raise AssertionError("Readiness must not call a model or request credentials.")
    yield
server.validate_configuration()
workspace = asyncio.run(server.prepare_workspace())
server.create_app(workspace, client_factory=no_model).run()
"""
        content = b"preserved across process restart"
        for restart in range(2):
            with tempfile.TemporaryFile() as logs:
                process = subprocess.Popen(
                    [sys.executable, "-c", launcher], cwd=Path(__file__).parent,
                    env=environment, stdout=logs, stderr=subprocess.STDOUT)
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            logs.seek(0)
                            self.fail(logs.read().decode())
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readiness", timeout=1) as response:
                                self.assertEqual(response.status, 200)
                                break
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.1)
                    else:
                        self.fail("Real local startup never became ready.")
                    if restart == 0:
                        (root / "resume.txt").write_bytes(content)
                    else:
                        self.assertEqual(hashlib.sha256((root / "resume.txt").read_bytes()).digest(),
                                         hashlib.sha256(content).digest())
                    self.assertEqual(Workspace(root).root, root)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
