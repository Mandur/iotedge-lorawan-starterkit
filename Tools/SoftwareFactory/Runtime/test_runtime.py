# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from coding_agent import MAX_FILE_BYTES, MAX_OUTPUT_BYTES, ToolError, Workspace, run_agent, run_process
from deploy import (ACR_PULL, PROJECT_ID, REGISTRY_ID, SUBSCRIPTION, TENANT, azure, definition,
                    has_pull_access, pull_plan, setup_pull, verify_caller, verify_region,
                    verify_registry)
from smoke import verify_evidence
from server import prepare_workspace, validate_configuration


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = Workspace(self.root)

    async def test_read_write_and_compare_swap(self):
        result = await self.workspace.execute("write_file", {
            "path": "Example.cs", "content": "original", "expected_sha256": "new"})
        self.assertEqual(result["sha256"], hashlib.sha256(b"original").hexdigest())
        read = await self.workspace.execute("read_file", {"path": "Example.cs"})
        self.assertEqual(read["content"], "original")
        with self.assertRaises(ToolError):
            await self.workspace.execute("write_file", {
                "path": "Example.cs", "content": "stale", "expected_sha256": "new"})
        await self.workspace.execute("write_file", {
            "path": "Example.cs", "content": "updated", "expected_sha256": read["sha256"]})
        self.assertEqual((self.root / "Example.cs").read_text(), "updated")

    async def test_path_boundaries(self):
        for path in ("/etc/passwd", "../escape", "a/../../escape", ".git/config",
                     ".env", "secret.key", "obj/output", "local.settings.json", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ToolError):
                await self.workspace.execute("read_file", {"path": path})

    async def test_links_and_special_files(self):
        (self.root / "original").write_text("value")
        (self.root / "link").symlink_to(self.root / "original")
        os.link(self.root / "original", self.root / "hardlink")
        os.mkfifo(self.root / "pipe")
        for path in ("link", "hardlink", "original", "pipe"):
            with self.subTest(path=path), self.assertRaises(ToolError):
                await self.workspace.execute("read_file", {"path": path})

    async def test_limits_and_schema(self):
        (self.root / "large").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with self.assertRaises(ToolError):
            await self.workspace.execute("read_file", {"path": "large"})
        for name, args in (("shell", {}), ("read_file", {"path": 2}),
                           ("read_file", {"path": "large", "extra": "x"}),
                           ("write_file", {"path": "new", "content": "x" * (MAX_FILE_BYTES + 1),
                                           "expected_sha256": "new"})):
            with self.subTest(name=name), self.assertRaises(ToolError):
                await self.workspace.execute(name, args)

    async def test_hidden_entries_not_exposed(self):
        (self.root / ".env").write_text("not exposed")
        (self.root / "Example.cs").write_text("visible")
        result = await self.workspace.execute("list_files", {"path": "."})
        self.assertEqual(result["entries"], [{"name": "Example.cs", "directory": False}])

    async def test_execution_is_explicit_and_fixed(self):
        with self.assertRaisesRegex(ToolError, "NOT run"):
            await self.workspace.execute("verify", {"lane": "repository"})
        workspace = Workspace(self.root, enable_execution=True)
        with self.assertRaises(ToolError):
            await workspace.execute("verify", {"lane": "shell"})
        with patch("coding_agent.run_process", new_callable=AsyncMock) as command:
            command.return_value = {"exit_code": 19, "output": "failed", "truncated": False}
            result = await workspace.execute("verify", {"lane": "repository"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["integration"], "not run")
            self.assertTrue(command.call_args.args[0][3].endswith("Verify-Repository.ps1"))

    async def test_process_failure_and_output_bound(self):
        result = await run_process([sys.executable, "-c",
                                    "import sys; print('x'*40000); sys.exit(7)"], self.root)
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(len(result["output"]), MAX_OUTPUT_BYTES)
        self.assertTrue(result["truncated"])

    async def test_timeout_and_cancellation_kill_descendants(self):
        script = ("import subprocess,sys,time; "
                  "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                  "open('child','w').write(str(p.pid)); time.sleep(60)")
        for cancel in (False, True):
            task = asyncio.create_task(run_process(
                [sys.executable, "-c", script], self.root, timeout=0.2))
            if cancel:
                await asyncio.sleep(0.1)
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                await task
            pid = int((self.root / "child").read_text())
            proc = Path(f"/proc/{pid}/stat")
            self.assertTrue(not proc.exists() or proc.read_text().split()[2] == "Z")

    async def test_child_environment_drops_credentials(self):
        with patch.dict(os.environ, {"AZURE_CLIENT_SECRET": "not-forwarded", "GITHUB_TOKEN": "not-forwarded"}):
            result = await run_process([sys.executable, "-c",
                "import os; print(os.getenv('AZURE_CLIENT_SECRET')); print(os.getenv('GITHUB_TOKEN'))"], self.root)
        self.assertEqual(result["output"], "None\nNone\n")


def response(text="", calls=(), status="completed"):
    items = []
    for index, (name, args) in enumerate(calls):
        values = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                  "call_id": f"call_{index}"}
        item = SimpleNamespace(**values)
        item.model_dump = lambda exclude_none=True, v=values: v.copy()
        items.append(item)
    return SimpleNamespace(status=status, output=items, output_text=text)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_limit_and_model_timeout_fail_explicitly(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
            return_value=response(calls=[("list_files", {"path": "."})] * 3))))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "Tool-call limit"):
                await run_agent(client, Workspace(root), "Act forever")

            async def wait_forever(**kwargs):
                await asyncio.Event().wait()

            client.responses.create = AsyncMock(side_effect=wait_forever)
            with patch("coding_agent.DEADLINE_SECONDS", 0.01), self.assertRaises(TimeoutError):
                await run_agent(client, Workspace(root), "Act forever")

    async def test_invalid_tool_json_is_a_failed_tool_result(self):
        broken = response(calls=[("write_file", {})])
        broken.output[0].arguments = "{invalid"
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
            broken, response(text="Unable to edit"),
        ])))
        with tempfile.TemporaryDirectory() as root:
            result = await run_agent(client, Workspace(root), "Act")
        self.assertFalse(result["tools"][0]["ok"])

    async def test_real_tools_with_fake_model(self):
        with tempfile.TemporaryDirectory() as root:
            client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
                response(calls=[("write_file", {"path": "Example.cs", "content": "code",
                                               "expected_sha256": "new"})]),
                response(calls=[("read_file", {"path": "Example.cs"})]),
                response(text="Created Example.cs. Verification not run."),
            ])))
            result = await run_agent(client, Workspace(root), "Create Example.cs")
            self.assertEqual(Path(root, "Example.cs").read_text(), "code")
            self.assertEqual(result["model"], "gpt-6-sol")
            self.assertEqual(len(result["tools"]), 2)
            self.assertIn("sha256", client.responses.create.call_args.kwargs["input"][-1]["output"])
            self.assertFalse(client.responses.create.call_args.kwargs["store"])

    async def test_tool_error_is_returned_not_hidden(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
            response(calls=[("read_file", {"path": "../escape"})]), response(text="Blocked"),
        ])))
        with tempfile.TemporaryDirectory() as root:
            result = await run_agent(client, Workspace(root), "Read file")
        self.assertFalse(result["tools"][0]["ok"])

    async def test_verification_timeout_is_reported_as_not_verified(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
            response(calls=[("verify", {"lane": "repository"})]), response(text="Not verified"),
        ])))
        with tempfile.TemporaryDirectory() as root:
            with patch("coding_agent.run_process", new_callable=AsyncMock, side_effect=TimeoutError):
                result = await run_agent(client, Workspace(root, enable_execution=True), "Verify")
        self.assertFalse(result["tools"][0]["ok"])
        self.assertIn("timed out", result["tools"][0]["error"])

    async def test_failed_or_empty_model_response_fails(self):
        for model_response in (response(status="incomplete"), response()):
            client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=model_response)))
            with tempfile.TemporaryDirectory() as root, self.assertRaises(RuntimeError):
                await run_agent(client, Workspace(root), "Act")

    async def test_limits_and_invalid_prompt(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(
            return_value=response(calls=[("list_files", {"path": "."})]))))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, "step limit"):
                await run_agent(client, Workspace(root), "Act forever")
            for prompt in ("", " " * 10, "x" * 32001):
                with self.assertRaises(ValueError):
                    await run_agent(client, Workspace(root), prompt)

    async def test_model_exception_propagates(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("unauthorized"))))
        with tempfile.TemporaryDirectory() as root, self.assertRaisesRegex(RuntimeError, "unauthorized"):
            await run_agent(client, Workspace(root), "Act")


class DeploymentTests(unittest.TestCase):
    image = "approved.azurecr.io/factory/runtime@sha256:" + "a" * 64
    commit = "b" * 40

    def test_azure_cli_resolution_and_explicit_target(self):
        with patch("deploy.shutil.which", return_value="resolved-azure-cli"), \
                patch("deploy.subprocess.run", return_value=SimpleNamespace(stdout="{}")) as run:
            self.assertEqual(azure("account", "show"), {})
            self.assertEqual(run.call_args.args[0], [
                "resolved-azure-cli", "account", "show", "--subscription", SUBSCRIPTION,
                "--output", "json"])
            self.assertTrue(run.call_args.kwargs["check"])
        with patch("deploy.shutil.which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "Azure CLI"):
                azure("account", "show")

    def test_digest_and_approved_configuration(self):
        payload = definition(self.image, self.commit)
        self.assertEqual(payload["container_configuration"]["image"], self.image)
        self.assertEqual(payload["environment_variables"]["AZURE_AI_MODEL_DEPLOYMENT_NAME"], "gpt-6-sol")
        self.assertEqual(payload["environment_variables"]["FACTORY_ENABLE_EXECUTION"], "0")
        self.assertNotIn("FOUNDRY_PROJECT_ENDPOINT", payload["environment_variables"])

    def test_mutable_or_invalid_inputs_rejected(self):
        for image in ("approved.azurecr.io/factory:latest", "http://host/image", self.image.upper()):
            with self.assertRaises(ValueError):
                definition(image, self.commit)
        with self.assertRaises(ValueError):
            definition(self.image, "dev")
        with self.assertRaises(ValueError):
            definition(self.image, self.commit, "token=secret")

    def test_region_failure_prevents_deployment(self):
        credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="not-a-real-token"))
        with patch("deploy.urllib.request.urlopen", side_effect=PermissionError("403")):
            with self.assertRaisesRegex(PermissionError, "403"):
                verify_region(credential)

    def test_pull_plan_requires_reviewed_enabled_project_identity(self):
        principal = "11111111-2222-3333-4444-555555555555"
        metadata = {"id": PROJECT_ID, "properties": {"provisioningState": "Succeeded"},
                    "identity": {"principalId": principal, "type": "SystemAssigned", "tenantId": TENANT}}
        directory = {"id": principal, "accountEnabled": True, "servicePrincipalType": "ManagedIdentity"}
        with patch("deploy.azure", return_value=directory):
            plan = pull_plan(metadata, principal)
        self.assertEqual(plan["principal"], principal)
        self.assertEqual(plan["scope"], REGISTRY_ID)
        self.assertEqual(plan["role"], "AcrPull")
        for expected in ("66666666-7777-8888-9999-000000000000", "not-a-guid"):
            with self.assertRaises(ValueError):
                pull_plan(metadata, expected)
        for invalid in ({}, {"instance_identity": {"principal_id": principal}},
                        {**metadata, "id": "/wrong-project"}):
            with self.assertRaisesRegex(ValueError, "not ready"):
                pull_plan(invalid, principal)
        for invalid in ({**directory, "accountEnabled": False},
                        {**directory, "servicePrincipalType": "ServiceIdentity"}):
            with patch("deploy.azure", return_value=invalid):
                with self.assertRaisesRegex(ValueError, "not enabled"):
                    pull_plan(metadata, principal)

    def test_pull_verification_rejects_conditional_or_wrong_role(self):
        principal = "11111111-2222-3333-4444-555555555555"
        role = {"roleDefinitionId": f"/roles/{ACR_PULL}", "condition": None}
        with patch("deploy.azure", return_value=[role]):
            self.assertTrue(has_pull_access({"principal": principal}))
        for assignments in ([], [{"roleDefinitionId": "/roles/wrong"}],
                            [{**role, "condition": "conditional"}]):
            with patch("deploy.azure", return_value=assignments):
                self.assertFalse(has_pull_access({"principal": principal}))

    def test_retired_hosted_setup_and_deployment_cannot_write(self):
        principal = "11111111-2222-3333-4444-555555555555"
        with patch("deploy.azure") as command:
            with self.assertRaisesRegex(RuntimeError, "retired"):
                setup_pull(principal, approve=True)
            with self.assertRaisesRegex(RuntimeError, "retired"):
                from deploy import deploy
                deploy({}, principal)
        command.assert_not_called()

    def test_caller_requires_management_and_data_plane_permissions(self):
        account = {"id": SUBSCRIPTION, "tenantId": TENANT}
        for names, allowed in ((["Owner"], False), (["Foundry User"], False),
                               (["Owner", "Foundry User"], True),
                               (["Foundry Project Manager"], True)):
            with patch("deploy.azure", side_effect=[
                    account, {"id": "caller"},
                    [{"roleDefinitionName": name} for name in names]]):
                if allowed:
                    verify_caller()
                else:
                    with self.assertRaisesRegex(ValueError, "permissions"):
                        verify_caller()
        with patch("deploy.azure", return_value={**account, "tenantId": "wrong"}):
            with self.assertRaisesRegex(ValueError, "tenant"):
                verify_caller()

    def test_registry_preflight_fails_closed_without_policy_changes(self):
        registry = {"id": REGISTRY_ID, "loginServer": "loracivpgdgbnkyeh4u.azurecr.io",
                    "roleAssignmentMode": "LegacyRegistryPermissions", "publicNetworkAccess": "Enabled"}
        with patch("deploy.azure", side_effect=[registry, {"status": "enabled"}]) as command:
            verify_registry()
            self.assertEqual(command.call_count, 2)
        with patch("deploy.azure", side_effect=[registry, {"status": "disabled"}]) as command:
            with self.assertRaisesRegex(ValueError, "no policy will be changed"):
                verify_registry()
            self.assertEqual(command.call_count, 2)
        with patch("deploy.azure", return_value={**registry, "id": "/wrong-registry"}):
            with self.assertRaisesRegex(ValueError, "new review"):
                verify_registry()

    def test_smoke_rejects_prose_and_missing_or_wrong_tool_evidence(self):
        digest = hashlib.sha256(b"expected").hexdigest()
        valid = {"model": "gpt-6-sol", "summary": "done", "tools": [
            {"name": name, "ok": True, "path": "smoke.txt", "sha256": digest}
            for name in ("read_file", "write_file")]}
        self.assertEqual(verify_evidence(json.dumps(valid), "smoke.txt", "expected"), valid)
        with self.assertRaises(ValueError):
            verify_evidence(json.dumps(valid), "smoke.txt", "different")
        valid["tools"] = []
        with self.assertRaises(ValueError):
            verify_evidence(json.dumps(valid), "smoke.txt", "expected")


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_hosted_unwritable_home_uses_private_preprovisioned_workspace_and_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary, "session")
            home.mkdir()
            root = home / "factory-workspace"
            root.mkdir(mode=0o700)
            home.chmod(0o500)
            environment = {"HOME": str(home), "FACTORY_HOSTED": "1",
                           "FACTORY_WORKSPACE": str(root), "FACTORY_REPOSITORY_COMMIT": "a" * 40}
            with patch.dict(os.environ, environment), \
                    patch("server.run_process", new_callable=AsyncMock) as command:
                command.return_value = {"exit_code": 0, "output": ""}
                workspace = await prepare_workspace()
                await workspace.execute("write_file", {
                    "path": "kept.txt", "content": "resume", "expected_sha256": "new"})
                command.return_value = {"exit_code": 0, "output": "a" * 40 + "\n"}
                resumed = await prepare_workspace()
                self.assertEqual((await resumed.execute("read_file", {"path": "kept.txt"}))["content"], "resume")
                self.assertEqual(command.await_count, 5)

    async def test_hosted_storage_fails_closed_before_git(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "factory-workspace"
            environment = {"HOME": str(home), "FACTORY_HOSTED": "1",
                           "FACTORY_WORKSPACE": str(root), "FACTORY_REPOSITORY_COMMIT": "a" * 40}
            with patch.dict(os.environ, environment), \
                    patch("server.run_process", new_callable=AsyncMock) as command:
                with patch("server.Path.mkdir", side_effect=PermissionError("mount ownership")):
                    with self.assertRaisesRegex(RuntimeError, "platform must provide"):
                        await prepare_workspace()
                root.mkdir(mode=0o755)
                with self.assertRaisesRegex(ValueError, "mode 0700"):
                    await prepare_workspace()
                root.chmod(0o700)
                with patch("server.os.geteuid", return_value=root.stat().st_uid + 1):
                    with self.assertRaisesRegex(ValueError, "owned"):
                        await prepare_workspace()
                with patch("server.tempfile.TemporaryFile", side_effect=PermissionError("read-only")):
                    with patch("sys.stderr", new_callable=io.StringIO) as diagnostic:
                        with self.assertRaisesRegex(RuntimeError, "no fallback"):
                            await prepare_workspace()
                    evidence = json.loads(diagnostic.getvalue())
                    self.assertEqual(evidence["operation"], "write_probe")
                    self.assertEqual(evidence["effective_uid"], os.geteuid())
                    self.assertEqual(evidence["effective_gid"], os.getegid())
                    self.assertEqual(evidence["workspace"]["mode"], "0700")
                    self.assertEqual(evidence["home"]["uid"], home.stat().st_uid)
                    self.assertNotIn("environment", evidence)
                with patch.dict(os.environ, {"FACTORY_WORKSPACE": str(home)}):
                    with self.assertRaisesRegex(ValueError, "dedicated"):
                        await prepare_workspace()
                root.rmdir()
                root.symlink_to(home, target_is_directory=True)
                with self.assertRaisesRegex(ToolError, "symlinks"):
                    await prepare_workspace()
                root.unlink()
                command.assert_not_awaited()

    async def test_hosted_empty_writable_home_initializes_private_child(self):
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                "HOME": home, "FACTORY_HOSTED": "1",
                "FACTORY_WORKSPACE": str(Path(home, "factory-workspace")),
                "FACTORY_REPOSITORY_COMMIT": "a" * 40}):
            with patch("server.run_process", new_callable=AsyncMock) as command:
                command.return_value = {"exit_code": 0, "output": ""}
                workspace = await prepare_workspace()
                self.assertEqual(workspace.root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(workspace.root.stat().st_uid, os.geteuid())
                self.assertEqual(command.await_count, 4)

    async def test_invalid_configuration_rejected_before_startup(self):
        for key, value in (("AZURE_AI_MODEL_DEPLOYMENT_NAME", "another-model"),
                           ("FACTORY_ENABLE_EXECUTION", "yes"),
                           ("FACTORY_HOSTED", "yes"),
                           ("FOUNDRY_PROJECT_ENDPOINT", "https://another-project")):
            with patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                validate_configuration()
        with patch.dict(os.environ, {"FACTORY_HOSTED": "1", "FACTORY_MODEL_TOKEN": "test-token"}):
            with self.assertRaisesRegex(ValueError, "superseded"):
                validate_configuration()

    async def test_pinned_workspace_restart_preserves_edits(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
                "FACTORY_WORKSPACE": root, "FACTORY_REPOSITORY_COMMIT": "a" * 40}):
            Path(root, "edited.cs").write_text("preserved")
            with patch("server.run_process", new_callable=AsyncMock) as command:
                command.return_value = {"exit_code": 0, "output": "a" * 40 + "\n"}
                workspace = await prepare_workspace()
                self.assertEqual(workspace.root, Path(root))
                self.assertEqual(Path(root, "edited.cs").read_text(), "preserved")
                self.assertEqual(command.await_count, 1)
                command.return_value = {"exit_code": 0, "output": "b" * 40 + "\n"}
                with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                    await prepare_workspace()

    async def test_pinned_checkout_failure_is_not_ready(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
                "FACTORY_WORKSPACE": root, "FACTORY_REPOSITORY_COMMIT": "a" * 40}):
            with patch("server.run_process", new_callable=AsyncMock) as command:
                command.return_value = {"exit_code": 7, "output": "fetch failed"}
                with self.assertRaisesRegex(RuntimeError, "fetch failed"):
                    await prepare_workspace()
                self.assertEqual(command.await_count, 1)

    async def test_pinned_checkout_uses_only_fixed_public_remote_and_disabled_hooks(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
                "FACTORY_WORKSPACE": root, "FACTORY_REPOSITORY_COMMIT": "a" * 40}):
            with patch("server.run_process", new_callable=AsyncMock) as command:
                command.return_value = {"exit_code": 0, "output": ""}
                await prepare_workspace()
                self.assertEqual(command.await_count, 4)
                self.assertIn("https://github.com/Mandur/iotedge-lorawan-starterkit.git",
                              command.call_args_list[1].args[0])
                self.assertIn("core.hooksPath=/dev/null", command.call_args_list[3].args[0])
            with patch.dict(os.environ, {"FACTORY_REPOSITORY_COMMIT": "dev"}):
                with self.assertRaisesRegex(ValueError, "full lowercase commit SHA"):
                    await prepare_workspace()


if __name__ == "__main__":
    unittest.main()
