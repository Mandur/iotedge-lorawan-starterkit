# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""ACA Sandbox client adapter for the trusted Foundry model orchestrator."""

import asyncio
import base64
from dataclasses import dataclass
import json
import os
import re
import shlex
import time
import uuid

from azure.core.credentials import AccessToken
from azure.containerapps.sandbox import (
    DATA_PLANE_SCOPE,
    SandboxClient,
    SandboxGroupClient,
    endpoint_for_region,
)

from coding_agent import MAX_FILE_BYTES, ToolError


SUBSCRIPTION = "f1474e0a-622f-410f-933e-d632635d1e03"
TENANT = "fea4bf20-a5c7-4467-a97b-4322661134d5"
WORKER = "/opt/lorawan-factory/Runtime/sandbox_worker.py"
PYTHON = "/opt/factory-python/bin/python"
WORKSPACE = "/workspaces/iotedge-lorawan-starterkit"
MAX_TOOL_RESPONSE_BYTES = MAX_FILE_BYTES * 6 + 8192
FILE_CALL_TIMEOUT = 45
VERIFY_CALL_TIMEOUT = 630

SUPPORTED_REGIONS = frozenset({"swedencentral"})


@dataclass(frozen=True)
class SandboxTarget:
    region: str
    resource_group: str
    sandbox_group: str
    sandbox_id: str
    task_id: str
    commit: str

    @classmethod
    def from_env(cls, environment=os.environ):
        required = (
            "ACA_REGION", "ACA_RESOURCE_GROUP", "ACA_SANDBOX_GROUP", "ACA_SANDBOX_ID",
            "AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID", "FACTORY_TASK_ID",
            "FACTORY_REPOSITORY_COMMIT",
        )
        missing = [name for name in required if not environment.get(name)]
        if missing:
            raise ValueError(f"ACA Sandbox runtime is missing required settings: {', '.join(missing)}.")
        region = environment["ACA_REGION"].lower()
        if region not in SUPPORTED_REGIONS:
            raise ValueError(f"ACA Sandboxes is not documented in region {region!r}.")
        if environment.get("AZURE_SUBSCRIPTION_ID") != SUBSCRIPTION:
            raise ValueError("ACA Sandbox runtime must use the explicitly approved subscription.")
        if environment.get("AZURE_TENANT_ID") != TENANT:
            raise ValueError("ACA Sandbox runtime must use the explicitly approved tenant.")
        if not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", environment["ACA_RESOURCE_GROUP"]):
            raise ValueError("Invalid ACA resource group name.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,90}", environment["ACA_SANDBOX_GROUP"]):
            raise ValueError("Invalid ACA Sandbox group name.")
        try:
            task_id = str(uuid.UUID(environment["FACTORY_TASK_ID"]))
        except ValueError as error:
            raise ValueError("Factory task ID must be a UUID.") from error
        sandbox_id = environment["ACA_SANDBOX_ID"]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,90}", sandbox_id):
            raise ValueError("ACA sandbox ID contains unsupported characters.")
        commit = environment["FACTORY_REPOSITORY_COMMIT"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("FACTORY_REPOSITORY_COMMIT must be a full lowercase commit SHA.")
        return cls(region, environment["ACA_RESOURCE_GROUP"], environment["ACA_SANDBOX_GROUP"],
                   sandbox_id, task_id, commit)


class StaticTokenCredential:
    """Uses a short-lived CLI token held only in the trusted orchestrator process."""

    def __init__(self, token, expires_on):
        if not token or any(char.isspace() for char in token):
            raise ValueError("ACA Sandbox token is missing or malformed.")
        try:
            self.expires_on = int(expires_on)
        except (TypeError, ValueError) as error:
            raise ValueError("ACA Sandbox token expiry must be a Unix timestamp.") from error
        if self.expires_on <= int(time.time()) + 60:
            raise ValueError("ACA Sandbox token expires too soon; restart the local runtime.")
        self._token = token

    def get_token(self, *scopes, **kwargs):
        if not self._token:
            raise ValueError("ACA Sandbox token is missing or malformed.")
        if DATA_PLANE_SCOPE not in scopes:
            raise ValueError("The token is not valid for the ACA Sandbox data plane.")
        if self.expires_on <= int(time.time()) + 30:
            raise RuntimeError("ACA Sandbox token expired; restart the local runtime.")
        return AccessToken(self._token, self.expires_on)

    def close(self):
        self._token = ""


def _value(model, name, default=None):
    if isinstance(model, dict):
        return model.get(name, default)
    return getattr(model, name, default)


def worker_command(action, *arguments, enable_execution=False, timeout_seconds=45):
    if not 1 <= timeout_seconds <= VERIFY_CALL_TIMEOUT:
        raise ValueError("Worker command timeout is outside the configured bound.")
    values = [action, *arguments]
    quoted = " ".join(shlex.quote(value) for value in values)
    command = (f"/usr/bin/timeout --signal=KILL {timeout_seconds}s "
               f"{shlex.quote(PYTHON)} -I {shlex.quote(WORKER)} {quoted}")
    if enable_execution:
        command += " --enable-execution"
    return command


class SandboxWorkspace:
    def __init__(self, client, credential, sandbox, target, enable_execution=False):
        self.client = client
        self.credential = credential
        self.sandbox = sandbox
        self.target = target
        self.task_id = target.task_id
        self.sandbox_id = target.sandbox_id
        self.enable_execution = enable_execution

    async def execute(self, name, arguments):
        if name == "verify" and not self.enable_execution:
            raise ToolError("Execution disabled by operator; verification NOT run.")
        if name not in {"list_files", "read_file", "write_file", "verify"}:
            raise ToolError("Unknown sandbox tool.")
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be an object.")
        serialized = json.dumps(arguments, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(serialized) > MAX_FILE_BYTES + 8192:
            raise ToolError("Sandbox tool request exceeds the bounded payload size.")
        payload = base64.urlsafe_b64encode(serialized).decode("ascii")
        payload = f"b64:{payload}"
        timeout = VERIFY_CALL_TIMEOUT if name == "verify" else FILE_CALL_TIMEOUT
        command = worker_command(
            "tool", name, payload, enable_execution=self.enable_execution and name == "verify",
            timeout_seconds=timeout)

        async def invoke():
            def execute():
                sandbox = SandboxClient(
                    endpoint_for_region(self.target.region),
                    self.credential,
                    subscription_id=SUBSCRIPTION,
                    resource_group=self.target.resource_group,
                    sandbox_group=self.target.sandbox_group,
                    sandbox_id=self.sandbox_id,
                    retry_total=0,
                    connection_timeout=10,
                    read_timeout=timeout,
                )
                try:
                    return sandbox.exec(command, working_directory="/")
                finally:
                    sandbox.close()

            return await asyncio.to_thread(execute)

        try:
            result = await asyncio.wait_for(invoke(), timeout=timeout + 15)
        except TimeoutError as error:
            raise TimeoutError(
                "ACA Sandbox tool request timed out; remote cancellation is not confirmed.") from error
        if result.exit_code != 0:
            message = result.stdout[:MAX_TOOL_RESPONSE_BYTES] or "ACA Sandbox worker command failed."
            try:
                payload = json.loads(message)
                message = payload.get("error", message)
                if payload.get("diagnostic"):
                    message += f" Diagnostic: {json.dumps(payload['diagnostic'], sort_keys=True)}"
            except json.JSONDecodeError:
                pass
            raise ToolError(message)
        raw = result.stdout.encode("utf-8")
        if len(raw) > MAX_TOOL_RESPONSE_BYTES:
            raise RuntimeError("ACA Sandbox worker response exceeded the bounded output size.")
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("ACA Sandbox worker returned invalid JSON.") from error
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            raise ToolError(str(envelope.get("error", "ACA Sandbox worker failed.")))
        return envelope["value"]

    def close(self):
        try:
            self.client.close()
        finally:
            self.credential.close()


def connect_sandbox_workspace(environment=os.environ):
    target = SandboxTarget.from_env(environment)
    credential = StaticTokenCredential(
        environment.get("FACTORY_SANDBOX_TOKEN"),
        environment.get("FACTORY_SANDBOX_TOKEN_EXPIRES_ON"),
    )
    client = None
    retained = False
    try:
        client = SandboxGroupClient(
            endpoint_for_region(target.region),
            credential,
            subscription_id=SUBSCRIPTION,
            resource_group=target.resource_group,
            sandbox_group=target.sandbox_group,
            retry_total=0,
            connection_timeout=10,
            read_timeout=60,
        )
        sandbox = client.get_sandbox_client(target.sandbox_id)
        details = sandbox.get()
        state = str(_value(details, "state", "")).lower()
        if state != "running":
            raise RuntimeError(
                f"ACA Sandbox {target.sandbox_id} is {state or 'in an unknown state'}; "
                "use the explicit resume operation before starting the runtime.")
        labels = _value(details, "labels", {}) or {}
        if (labels.get("job-id") != target.task_id or labels.get("repo-commit") != target.commit):
            raise ValueError("ACA Sandbox task/commit labels do not match the requested task.")

        status = sandbox.exec(
            worker_command("status", "--commit", target.commit, timeout_seconds=FILE_CALL_TIMEOUT),
            working_directory="/",
        )
        if status.exit_code != 0:
            raise RuntimeError(
                f"ACA Sandbox workspace preflight failed (exit {status.exit_code}): "
                f"{status.stdout} {getattr(status, 'stderr', '')}")
        try:
            envelope = json.loads(status.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "ACA Sandbox workspace preflight returned invalid JSON.") from error
        if not isinstance(envelope, dict):
            raise RuntimeError("ACA Sandbox workspace preflight returned an invalid response envelope.")
        if envelope.get("ok") is not True:
            diagnostic = envelope.get("diagnostic")
            suffix = f" Diagnostic: {json.dumps(diagnostic, sort_keys=True)}" if diagnostic else ""
            raise RuntimeError(
                f"{envelope.get('error', 'ACA Sandbox workspace preflight failed.')}{suffix}")
        workspace = SandboxWorkspace(
            client, credential, sandbox, target,
            enable_execution=environment.get("FACTORY_ENABLE_EXECUTION", "0") == "1")
        retained = True
        return workspace
    finally:
        if not retained:
            try:
                if client is not None:
                    client.close()
            finally:
                credential.close()
