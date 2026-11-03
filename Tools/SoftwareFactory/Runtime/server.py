# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

# Never import runtime code or dependencies from the uploaded/bind-mounted workspace.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coding_agent import MODEL, Workspace, run_agent, run_process


PROJECT_ENDPOINT = "https://lorawan-factory-f1474e0a.services.ai.azure.com/api/projects/lorawan-software-factory"
REPOSITORY = "https://github.com/Mandur/iotedge-lorawan-starterkit.git"


def report_workspace_failure(operation, home, root, error=None):
    def metadata(path):
        result = {"path": str(path)}
        try:
            info = path.lstat()
            result.update(uid=info.st_uid, gid=info.st_gid, mode=f"{stat.S_IMODE(info.st_mode):04o}")
        except OSError as failure:
            result["stat_errno"] = failure.errno
        return result

    print(json.dumps({
        "event": "hosted_workspace_failure", "operation": operation,
        "effective_uid": os.geteuid(), "effective_gid": os.getegid(),
        "home": metadata(home), "workspace": metadata(root),
        "errno": getattr(error, "errno", None),
    }), file=sys.stderr, flush=True)


async def prepare_workspace():
    hosted = os.environ.get("FACTORY_HOSTED") == "1"
    default_root = (Path.home() / "factory-workspace" if hosted
                    else Path("/workspaces/iotedge-lorawan-starterkit"))
    root = Path(os.environ.get("FACTORY_WORKSPACE", str(default_root)))
    commit = os.environ.get("FACTORY_REPOSITORY_COMMIT")
    if hosted:
        if not commit:
            raise ValueError("Hosted workspace requires a pinned repository commit.")
        if not root.is_absolute() or root != Path.home() / "factory-workspace":
            raise ValueError("Hosted workspace must be the dedicated factory-workspace under session HOME.")
        home = Path.home()
        if not home.is_absolute() or home.resolve() != home or not home.is_dir():
            raise ValueError("Hosted session HOME must be an existing absolute directory without symlinks.")
        try:
            root.mkdir(mode=0o700, exist_ok=True)
        except OSError as error:
            report_workspace_failure("mkdir", home, root, error)
            raise RuntimeError(
                "Cannot initialize private workspace in persisted session HOME. The platform must provide "
                "write access for the non-root runtime user; no fallback or permission repair is allowed.") from error
        # Validate before reading or executing anything in persisted, upload-writable storage.
        Workspace(root)
        metadata = root.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            report_workspace_failure("ownership", home, root)
            raise ValueError("Hosted workspace must be owned by the runtime user with mode 0700.")
        try:
            with tempfile.TemporaryFile(dir=root):
                pass
        except OSError as error:
            report_workspace_failure("write_probe", home, root, error)
            raise RuntimeError("Hosted workspace is not writable; no fallback or permission repair is allowed.") from error
    if commit:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("FACTORY_REPOSITORY_COMMIT must be a full lowercase commit SHA.")
        if root.exists() and any(root.iterdir()):
            result = await run_process(["git", "-C", str(root), "rev-parse", "HEAD"], root)
            if result["exit_code"] != 0 or result["output"].strip() != commit:
                raise ValueError("Existing workspace is not the pinned commit; refusing to overwrite.")
            return Workspace(root, enable_execution=os.environ.get("FACTORY_ENABLE_EXECUTION") == "1")
        root.mkdir(parents=True, exist_ok=True)
        commands = [
            ["git", "init", str(root)],
            ["git", "-C", str(root), "remote", "add", "origin", REPOSITORY],
            ["git", "-C", str(root), "fetch", "--depth=1", "origin", commit],
            ["git", "-C", str(root), "-c", "core.hooksPath=/dev/null",
             "checkout", "--detach", "FETCH_HEAD"],
        ]
        for command in commands:
            result = await run_process(command, root)
            if result["exit_code"] != 0:
                raise RuntimeError(f"Workspace checkout failed: {result['output']}")
    return Workspace(root, enable_execution=os.environ.get("FACTORY_ENABLE_EXECUTION") == "1")


def validate_configuration():
    if os.environ.get("FOUNDRY_PROJECT_ENDPOINT", PROJECT_ENDPOINT) != PROJECT_ENDPOINT:
        raise ValueError("This slice is bound to the approved Foundry project.")
    if os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", MODEL) != MODEL:
        raise ValueError("Only the approved gpt-6-sol deployment is supported.")
    if os.environ.get("FACTORY_ENABLE_EXECUTION", "0") not in {"0", "1"}:
        raise ValueError("FACTORY_ENABLE_EXECUTION must be 0 or 1.")
    if os.environ.get("FACTORY_HOSTED", "0") not in {"0", "1"}:
        raise ValueError("FACTORY_HOSTED must be 0 or 1.")
    if os.environ.get("FACTORY_HOSTED") == "1":
        raise ValueError("Foundry Hosted Agent compute is superseded; use an explicit ACA Sandbox.")
    backend = os.environ.get("FACTORY_EXECUTION_BACKEND", "local")
    if backend not in {"local", "aca"}:
        raise ValueError("FACTORY_EXECUTION_BACKEND must be local or aca.")
    if backend == "aca":
        if not os.environ.get("FACTORY_SANDBOX_TOKEN"):
            raise ValueError("ACA Sandbox data-plane token is required in the trusted orchestrator.")
        if not os.environ.get("FACTORY_SANDBOX_TOKEN_EXPIRES_ON"):
            raise ValueError("ACA Sandbox token expiry is required in the trusted orchestrator.")
        from sandbox_runtime import SandboxTarget
        SandboxTarget.from_env()


@asynccontextmanager
async def model_client():
    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import DefaultAzureCredential

    async with DefaultAzureCredential() as credential:
        async with AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as project:
            options = {"timeout": 60, "max_retries": 0}
            if os.environ.get("FACTORY_MODEL_TOKEN"):
                options["api_key"] = os.environ["FACTORY_MODEL_TOKEN"]
            async with project.get_openai_client(**options) as client:
                yield client


def create_app(workspace, client_factory=model_client):
    from azure.ai.agentserver.responses import (
        CreateResponse, ResponseContext, ResponsesAgentServerHost, TextResponse,
    )

    app = ResponsesAgentServerHost()
    # One workspace per process/session: requests never race each other's writes.
    lock = asyncio.Lock()

    @app.response_handler
    async def handler(request: CreateResponse, context: ResponseContext, cancellation_signal):
        async def execute():
            if context.is_recovery:
                raise RuntimeError("Automatic replay of coding work is not supported.")
            if lock.locked():
                raise RuntimeError("Workspace is busy; concurrent coding requests are rejected.")
            async with lock:
                prompt = await context.get_input_text()
                async with client_factory() as client:
                    return await run_agent(client, workspace, prompt)

        work = asyncio.create_task(execute())
        cancelled = asyncio.create_task(cancellation_signal.wait())
        shutdown = asyncio.create_task(context.shutdown.wait())
        try:
            done, _ = await asyncio.wait(
                {work, cancelled, shutdown}, return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done or shutdown in done:
                raise asyncio.CancelledError
            result = await work
            return TextResponse(context, request, text=json.dumps(result))
        finally:
            for task in (work, cancelled, shutdown):
                task.cancel()
            await asyncio.gather(work, cancelled, shutdown, return_exceptions=True)

    return app


def main():
    validate_configuration()
    if os.environ.get("FACTORY_EXECUTION_BACKEND", "local") == "aca":
        from sandbox_runtime import connect_sandbox_workspace
        workspace = connect_sandbox_workspace()
    else:
        workspace = asyncio.run(prepare_workspace())
    try:
        create_app(workspace).run()
    finally:
        close = getattr(workspace, "close", None)
        if close is not None:
            close()


if __name__ == "__main__":
    main()
