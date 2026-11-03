# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

import asyncio
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from azure.containerapps.sandbox import DATA_PLANE_SCOPE

import sandbox_operator
import sandbox_runtime
import sandbox_worker
from coding_agent import ToolError
from server import validate_configuration


SUBSCRIPTION = sandbox_runtime.SUBSCRIPTION
COMMIT = "a" * 40
TASK_ID = "11111111-2222-4333-8444-555555555555"
SANDBOX_ID = "sandbox-012345"
IMAGE = f"{sandbox_operator.IMAGE_REPOSITORY}@sha256:{'b' * 64}"


def runtime_environment():
    return {
        "ACA_REGION": "swedencentral",
        "ACA_RESOURCE_GROUP": "rg-lorawan-software-factory",
        "ACA_SANDBOX_GROUP": "factory-group",
        "ACA_SANDBOX_ID": SANDBOX_ID,
        "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
        "AZURE_TENANT_ID": sandbox_runtime.TENANT,
        "FACTORY_TASK_ID": TASK_ID,
        "FACTORY_REPOSITORY_COMMIT": COMMIT,
        "FACTORY_SANDBOX_TOKEN": "short-lived-token",
        "FACTORY_SANDBOX_TOKEN_EXPIRES_ON": str(int(time.time()) + 600),
        "FACTORY_ENABLE_EXECUTION": "0",
    }


class SandboxRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_server_requires_explicit_aca_target_and_trusted_token(self):
        environment = runtime_environment()
        environment["FACTORY_EXECUTION_BACKEND"] = "aca"
        with patch.dict(os.environ, environment, clear=True):
            validate_configuration()
        for key in ("FACTORY_SANDBOX_TOKEN", "FACTORY_SANDBOX_TOKEN_EXPIRES_ON",
                    "ACA_SANDBOX_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID"):
            invalid = dict(environment)
            invalid.pop(key)
            with self.subTest(key=key), patch.dict(os.environ, invalid, clear=True):
                with self.assertRaises(ValueError):
                    validate_configuration()

    def test_target_is_frozen_to_approved_subscription_and_region(self):
        target = sandbox_runtime.SandboxTarget.from_env(runtime_environment())
        self.assertEqual(target.sandbox_id, SANDBOX_ID)
        self.assertEqual(target.task_id, TASK_ID)
        for key, value in (("AZURE_SUBSCRIPTION_ID", "other"),
                           ("AZURE_TENANT_ID", "other"),
                           ("ACA_REGION", "eastus"),
                           ("FACTORY_REPOSITORY_COMMIT", "mutable")):
            environment = runtime_environment()
            environment[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                sandbox_runtime.SandboxTarget.from_env(environment)

    def test_static_token_is_scoped_and_expiring(self):
        credential = sandbox_runtime.StaticTokenCredential(
            "temporary", int(time.time()) + 300)
        self.assertEqual(credential.get_token(DATA_PLANE_SCOPE).token, "temporary")
        with self.assertRaisesRegex(ValueError, "not valid"):
            credential.get_token("https://management.azure.com/.default")
        credential.close()
        with self.assertRaisesRegex(ValueError, "missing or malformed"):
            credential.get_token(DATA_PLANE_SCOPE)
        with self.assertRaisesRegex(ValueError, "expires too soon"):
            sandbox_runtime.StaticTokenCredential("expired", int(time.time()) + 10)

    async def test_connect_checks_existing_sandbox_without_create_or_resume(self):
        environment = runtime_environment()
        sandbox = Mock()
        sandbox.get.return_value = SimpleNamespace(
            id=SANDBOX_ID, state="Running",
            labels={"job-id": TASK_ID, "repo-commit": COMMIT})
        sandbox.exec.return_value = SimpleNamespace(
            exit_code=0, stdout=json.dumps({"ok": True, "value": {"commit": COMMIT}}), stderr="")
        group = Mock()
        group.get_sandbox_client.return_value = sandbox
        with patch("sandbox_runtime.SandboxGroupClient", return_value=group) as constructor:
            workspace = sandbox_runtime.connect_sandbox_workspace(environment)
        try:
            self.assertEqual(workspace.sandbox_id, SANDBOX_ID)
            self.assertEqual(workspace.task_id, TASK_ID)
            constructor.assert_called_once()
            self.assertEqual(constructor.call_args.args[0],
                             "https://management.swedencentral.azuredevcompute.io")
            self.assertEqual(constructor.call_args.kwargs["retry_total"], 0)
            self.assertEqual(constructor.call_args.kwargs["read_timeout"], 60)
            sandbox.resume.assert_not_called()
            sandbox.exec.assert_called_once()
            self.assertIn(COMMIT, sandbox.exec.call_args.args[0])
        finally:
            workspace.close()

    async def test_connect_rejects_wrong_task_or_stopped_sandbox_without_resume(self):
        environment = runtime_environment()
        sandbox = Mock()
        sandbox.get.return_value = SimpleNamespace(
            id=SANDBOX_ID, state="Stopped",
            labels={"job-id": TASK_ID, "repo-commit": COMMIT})
        group = Mock()
        group.get_sandbox_client.return_value = sandbox
        with patch("sandbox_runtime.SandboxGroupClient", return_value=group):
            with self.assertRaisesRegex(RuntimeError, "explicit resume"):
                sandbox_runtime.connect_sandbox_workspace(environment)
        sandbox.resume.assert_not_called()
        sandbox.exec.assert_not_called()
        group.close.assert_called_once()

        sandbox.get.return_value = SimpleNamespace(
            id=SANDBOX_ID, state="Running", labels={"job-id": "different", "repo-commit": COMMIT})
        with patch("sandbox_runtime.SandboxGroupClient", return_value=group):
            with self.assertRaisesRegex(ValueError, "labels"):
                sandbox_runtime.connect_sandbox_workspace(environment)
        sandbox.exec.assert_not_called()

    async def test_tool_proxy_is_bounded_and_never_receives_credentials(self):
        target = sandbox_runtime.SandboxTarget.from_env(runtime_environment())
        remote_sandbox = Mock()
        remote_sandbox.exec.return_value = SimpleNamespace(
            exit_code=0, stdout=json.dumps({"ok": True, "value": {"content": "safe"}}), stderr="")
        client = Mock()
        credential = Mock()
        workspace = sandbox_runtime.SandboxWorkspace(client, credential, Mock(), target)
        try:
            with patch("sandbox_runtime.SandboxClient", return_value=remote_sandbox) as constructor:
                result = await workspace.execute("read_file", {"path": "src/example.cs"})
            self.assertEqual(result, {"content": "safe"})
            command = remote_sandbox.exec.call_args.args[0]
            self.assertIn("/usr/bin/timeout --signal=KILL 45s", command)
            self.assertNotIn(environment_secret := runtime_environment()["FACTORY_SANDBOX_TOKEN"], command)
            parts = shlex.split(command)
            payload = json.loads(base64.urlsafe_b64decode(parts[-1][4:]).decode("utf-8"))
            self.assertEqual(payload, {"path": "src/example.cs"})
            self.assertEqual(remote_sandbox.exec.call_args.kwargs, {"working_directory": "/"})
            self.assertEqual(constructor.call_args.kwargs["read_timeout"], 45)
            self.assertEqual(constructor.call_args.kwargs["sandbox_id"], SANDBOX_ID)
            self.assertEqual(sandbox_runtime.worker_command(
                "tool", "verify", "x", timeout_seconds=600).split()[2], "600s")
            with self.assertRaisesRegex(ToolError, "NOT run"):
                await workspace.execute("verify", {"lane": "repository"})
            self.assertEqual(remote_sandbox.exec.call_count, 1)
            self.assertNotIn(environment_secret, remote_sandbox.exec.call_args.args[0])
        finally:
            workspace.close()
        remote_sandbox.close.assert_called_once()
        client.close.assert_called_once()

    async def test_worker_errors_and_remote_timeouts_are_reported(self):
        target = sandbox_runtime.SandboxTarget.from_env(runtime_environment())
        remote_sandbox = Mock()
        remote_sandbox.exec.return_value = SimpleNamespace(
            exit_code=1, stdout=json.dumps({"ok": False, "error": "path denied"}), stderr="")
        client = Mock()
        workspace = sandbox_runtime.SandboxWorkspace(client, Mock(), Mock(), target)
        with patch("sandbox_runtime.SandboxClient", return_value=remote_sandbox):
            with self.assertRaisesRegex(ToolError, "path denied"):
                await workspace.execute("read_file", {"path": "../secret"})
            remote_sandbox.exec.side_effect = TimeoutError
            with self.assertRaisesRegex(TimeoutError, "cancellation is not confirmed"):
                await workspace.execute("list_files", {"path": "."})


class SandboxOperatorTests(unittest.TestCase):
    disk_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-lorawan-software-factory/"
        "providers/Microsoft.App/sandboxGroups/factory-group/diskImages/image-a")

    def test_digest_source_and_disk_readiness_must_match(self):
        disk = SimpleNamespace(
            image=SimpleNamespace(base=IMAGE), status=SimpleNamespace(state="Ready"))
        sandbox_operator.disk_image_matches(disk, IMAGE)
        with self.assertRaisesRegex(ValueError, "immutable digest"):
            sandbox_operator.image_reference("loracivpgdgbnkyeh4u.azurecr.io/lorawan/factory:latest")
        with self.assertRaisesRegex(ValueError, "does not match"):
            sandbox_operator.disk_image_matches(
                SimpleNamespace(image=SimpleNamespace(base="other"), status=disk.status), IMAGE)
        with self.assertRaisesRegex(ValueError, "not verified ready"):
            sandbox_operator.disk_image_matches(
                SimpleNamespace(image=disk.image, status=None), IMAGE)
        with self.assertRaisesRegex(ValueError, "full ACA Sandbox"):
            sandbox_operator.disk_image_name(None)
        self.assertEqual(
            sandbox_operator.operation_read_timeout("create-sandbox"),
            sandbox_operator.WORKSPACE_INIT_TIMEOUT + 20)
        self.assertEqual(sandbox_operator.operation_read_timeout("status"), 60)

    def test_create_image_passes_only_pinned_source_and_registry_credential(self):
        disk = SimpleNamespace(
            id=self.disk_id,
            image=SimpleNamespace(base=IMAGE),
            status=SimpleNamespace(state="Ready"))
        client = Mock()
        client.begin_create_disk_image.return_value.result.return_value = disk
        credentials = sandbox_operator.RegistryCredentials(username="token-user", token="secret")
        result = sandbox_operator.create_disk_image(client, IMAGE, "runtime-image", credentials)
        self.assertIs(result, disk)
        client.begin_create_disk_image.assert_called_once_with(
            IMAGE, name="runtime-image", registry_credentials=credentials,
            polling_timeout=1800, polling_interval=10)

    def test_create_sandbox_binds_task_digest_and_deny_egress_at_creation(self):
        disk = SimpleNamespace(
            id=self.disk_id,
            image=SimpleNamespace(base=IMAGE),
            status=SimpleNamespace(state="Ready"))
        sandbox = SimpleNamespace(sandbox_id=SANDBOX_ID)
        client = Mock()
        client.get_disk_image.return_value = disk
        client.begin_create_sandbox.return_value.result.return_value = sandbox
        result = sandbox_operator.create_sandbox(
            client, disk.id, IMAGE, TASK_ID, COMMIT, "L")
        self.assertIs(result, sandbox)
        request = client.begin_create_sandbox.call_args.kwargs
        self.assertEqual(request["disk_id"], disk.id)
        client.get_disk_image.assert_called_once_with("image-a")
        self.assertEqual(request["labels"], {"job-id": TASK_ID, "repo-commit": COMMIT})
        self.assertEqual((request["cpu"], request["memory"]), ("2000m", "4096Mi"))
        self.assertEqual(request["auto_suspend_seconds"], 300)
        self.assertEqual(request["auto_suspend_mode"], "Disk")
        self.assertEqual(request["egress_policy"].default_action, "Deny")
        self.assertEqual(request["egress_policy"].traffic_inspection, "Full")
        self.assertEqual(
            {rule.pattern for rule in request["egress_policy"].host_rules},
            set(sandbox_operator.EGRESS_HOSTS))
        client.begin_create_sandbox.assert_called_once()

    def test_create_sandbox_rejects_bad_image_tier_or_identity_before_create(self):
        client = Mock()
        with self.assertRaises(ValueError):
            sandbox_operator.create_sandbox(client, "disk", "mutable", TASK_ID, COMMIT, "L")
        with self.assertRaisesRegex(ValueError, "tier"):
            sandbox_operator.create_sandbox(client, "disk", IMAGE, TASK_ID, COMMIT, "XL")
        self.assertFalse(client.begin_create_sandbox.called)

    def test_task_labels_and_lifecycle_identity_are_exact(self):
        labels = sandbox_operator.task_labels(TASK_ID.upper(), COMMIT)
        self.assertEqual(labels, {"job-id": TASK_ID, "repo-commit": COMMIT})
        client = Mock()
        client.sandbox_id = SANDBOX_ID
        client.get.return_value = SimpleNamespace(
            id=SANDBOX_ID, labels=labels, state="Running")
        self.assertEqual(sandbox_operator.verify_sandbox_task(client, TASK_ID, COMMIT).state, "Running")
        client.get.return_value.labels["repo-commit"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "task and commit"):
            sandbox_operator.verify_sandbox_task(client, TASK_ID, COMMIT)
        with self.assertRaisesRegex(ValueError, "exact sandbox ID"):
            sandbox_operator.require_approval(SANDBOX_ID, "different")


class SandboxWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_private_workspace_initializes_and_existing_edits_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            with patch("sandbox_worker.run_process", new_callable=unittest.mock.AsyncMock) as command:
                command.return_value = {"exit_code": 0, "output": ""}
                first = await sandbox_worker.prepare_workspace(COMMIT, root)
                self.assertFalse(first["preserved"])
                self.assertEqual(command.await_count, 4)
                self.assertEqual(first["uid"], os.geteuid())
                self.assertEqual(first["gid"], os.getegid())
                self.assertEqual(first["mode"], "0700")
                (root / "edit.cs").write_text("preserve this edit")
                command.return_value = {"exit_code": 0, "output": COMMIT + "\n"}
                resumed = await sandbox_worker.prepare_workspace(COMMIT, root)
                self.assertTrue(resumed["preserved"])
                self.assertEqual(command.await_count, 5)
                self.assertEqual((root / "edit.cs").read_text(), "preserve this edit")

    async def test_workspace_failure_carries_numeric_owner_mode_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o755)
            validate = sandbox_worker.validate_workspace
            output = io.StringIO()
            with patch("sandbox_worker.WORKSPACE_ROOT", root), \
                    patch("sandbox_worker.validate_workspace",
                          side_effect=lambda: validate(root)), \
                    patch("sys.argv", ["sandbox_worker.py", "status", "--commit", COMMIT]), \
                    contextlib.redirect_stderr(output), contextlib.redirect_stdout(io.StringIO()) as stdout:
                with self.assertRaises(SystemExit):
                    sandbox_worker.main()
            diagnostic = json.loads(stdout.getvalue())["diagnostic"]
            self.assertEqual(diagnostic["operation"], "ownership")
            self.assertEqual(diagnostic["effective_uid"], os.geteuid())
            self.assertEqual(diagnostic["effective_gid"], os.getegid())
            self.assertEqual(diagnostic["workspace"]["uid"], root.stat().st_uid)
            self.assertEqual(diagnostic["workspace"]["gid"], root.stat().st_gid)
            self.assertEqual(diagnostic["workspace"]["mode"], "0755")
            self.assertEqual(json.loads(output.getvalue())["event"], "sandbox_workspace_failure")
            self.assertNotIn("AZURE_CLIENT_SECRET", output.getvalue())

    async def test_workspace_path_must_already_exist_and_be_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary, "not-created")
            with self.assertRaisesRegex(sandbox_worker.WorkspaceFailure, "no fallback"):
                sandbox_worker.validate_workspace(missing)
            self.assertFalse(missing.exists())
            with self.assertRaises(ValueError):
                await sandbox_worker.prepare_workspace("mutable", Path(temporary))
