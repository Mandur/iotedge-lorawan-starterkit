# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""SDK/ASGI contract tests. These require the complete locked runtime environment."""

from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from azure.ai.projects.models import HostedAgentDefinition
import httpx2

from coding_agent import Workspace
from deploy import definition, deploy
from server import create_app
from test_runtime import response


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreviewed_registry_or_connection_never_creates_client(self):
        with patch("azure.ai.projects.AIProjectClient") as client:
            for image, connection in (
                    ("unapproved.azurecr.io/runtime@sha256:" + "a" * 64, None),
                    ("loracivpgdgbnkyeh4u.azurecr.io/runtime@sha256:" + "a" * 64, "unreviewed")):
                with self.assertRaisesRegex(RuntimeError, "retired"):
                    deploy(definition(image, "b" * 40, connection),
                           "11111111-2222-3333-4444-555555555555")
            client.assert_not_called()

    async def test_retired_hosted_deployment_does_not_create_versions(self):
        principal = "11111111-2222-3333-4444-555555555555"
        project = Mock()
        project.agents.get.return_value.as_dict.return_value = {
            "instance_identity": {"principal_id": principal, "status": "active"}}
        with patch("deploy.verify_caller"), patch("deploy.verify_registry"), \
                patch("deploy.project_metadata"), patch("deploy.pull_plan", return_value={"principal": principal}), \
                patch("deploy.verify_region"), patch("deploy.has_pull_access", return_value=False), \
                patch("azure.identity.AzureCliCredential"), \
                patch("azure.ai.projects.AIProjectClient") as client:
            client.return_value.__enter__.return_value = project
            with self.assertRaisesRegex(RuntimeError, "retired"):
                deploy(definition(
                    "loracivpgdgbnkyeh4u.azurecr.io/runtime@sha256:" + "a" * 64, "b" * 40),
                    principal)
        project.agents.create_version.assert_not_called()

    async def test_sdk_definition_roundtrip(self):
        payload = definition("approved.azurecr.io/runtime@sha256:" + "a" * 64, "b" * 40)
        actual = HostedAgentDefinition(**payload).as_dict()
        self.assertEqual(actual["container_configuration"]["image"],
                         payload["container_configuration"]["image"])
        self.assertEqual(actual["protocol_versions"][0]["version"], "2.0.0")
        self.assertEqual(actual["session_configuration"]["idle_timeout_seconds"], 120)

    async def test_responses_endpoint_invokes_real_workspace_tools(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(side_effect=[
            response(calls=[("write_file", {"path": "smoke.txt", "content": "factory-smoke",
                                           "expected_sha256": "new"})]),
            response(calls=[("read_file", {"path": "smoke.txt"})]),
            response(text="Created and read smoke.txt; verification not run."),
        ])))

        @asynccontextmanager
        async def factory():
            yield client

        with tempfile.TemporaryDirectory() as root:
            app = create_app(Workspace(root), factory)
            async with app.router.lifespan_context(app):
                async with httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app=app), base_url="http://test") as http:
                    ready = await http.get("/readiness")
                    self.assertEqual(ready.status_code, 200)
                    result = await http.post("/responses", json={
                        "model": "gpt-6-sol", "input": "Create smoke.txt and read it",
                        "stream": False, "store": False,
                    })
            self.assertEqual(result.status_code, 200, result.text)
            payload = result.json()
            self.assertEqual(payload["status"], "completed")
            text = "".join(content["text"] for item in payload["output"]
                           if item["type"] == "message" for content in item["content"]
                           if content["type"] == "output_text")
            self.assertEqual(len(json.loads(text)["tools"]), 2)
            self.assertEqual(Path(root, "smoke.txt").read_text(), "factory-smoke")

if __name__ == "__main__":
    unittest.main()
