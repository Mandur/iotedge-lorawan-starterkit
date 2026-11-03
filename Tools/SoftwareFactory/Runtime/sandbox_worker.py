# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""Trusted, narrow worker entrypoint invoked through the ACA Sandbox SDK."""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coding_agent import Workspace, run_process


WORKSPACE_ROOT = Path("/workspaces/iotedge-lorawan-starterkit")
REPOSITORY = "https://github.com/Mandur/iotedge-lorawan-starterkit.git"


def workspace_metadata(root=WORKSPACE_ROOT):
    result = {"path": str(root)}
    try:
        info = root.lstat()
        result.update(
            uid=info.st_uid,
            gid=info.st_gid,
            mode=f"{stat.S_IMODE(info.st_mode):04o}",
        )
    except OSError as error:
        result["stat_errno"] = error.errno
    return result


class WorkspaceFailure(RuntimeError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


def report_workspace_failure(operation, error=None, root=WORKSPACE_ROOT):
    home = os.environ.get("HOME")
    diagnostic = {
        "event": "sandbox_workspace_failure",
        "operation": operation,
        "effective_uid": os.geteuid(),
        "effective_gid": os.getegid(),
        "home": workspace_metadata(Path(home)) if home else {"path": None},
        "workspace": workspace_metadata(root),
        "errno": getattr(error, "errno", None),
    }
    print(json.dumps(diagnostic), file=sys.stderr, flush=True)
    return diagnostic


def validate_workspace(root=WORKSPACE_ROOT):
    if not root.is_absolute() or root.resolve() != root or root.is_symlink():
        diagnostic = report_workspace_failure("path", root=root)
        raise WorkspaceFailure("Sandbox workspace must be an absolute nonsymlinked image path.", diagnostic)
    try:
        info = root.lstat()
    except OSError as error:
        diagnostic = report_workspace_failure("stat", error, root)
        raise WorkspaceFailure(
            "Sandbox workspace is missing or inaccessible; no fallback is allowed.", diagnostic) from error
    if not stat.S_ISDIR(info.st_mode):
        diagnostic = report_workspace_failure("type", root=root)
        raise WorkspaceFailure("Sandbox workspace must be a directory.", diagnostic)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        diagnostic = report_workspace_failure("ownership", root=root)
        raise WorkspaceFailure(
            "Sandbox workspace must be owned by the runtime UID with mode 0700.", diagnostic)
    try:
        with tempfile.TemporaryFile(dir=root):
            pass
    except OSError as error:
        diagnostic = report_workspace_failure("write_probe", error, root)
        raise WorkspaceFailure("Sandbox workspace is not writable by the runtime user.", diagnostic) from error


async def prepare_workspace(commit, root=WORKSPACE_ROOT):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Repository commit must be a full lowercase SHA.")
    validate_workspace(root)
    if any(root.iterdir()):
        result = await run_process(["git", "-C", str(root), "rev-parse", "HEAD"], root)
        if result["exit_code"] != 0 or result["output"].strip() != commit:
            raise RuntimeError("Existing sandbox workspace is not the pinned commit; refusing to overwrite.")
        return {"commit": commit, "workspace": str(root), "preserved": True,
                "uid": os.geteuid(), "gid": os.getegid(), "mode": "0700"}

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
            raise RuntimeError(f"Sandbox workspace checkout failed: {result['output']}")
    return {"commit": commit, "workspace": str(root), "preserved": False,
            "uid": os.geteuid(), "gid": os.getegid(), "mode": "0700"}


def decode_arguments(value):
    try:
        if not value.startswith("b64:"):
            raise ValueError("Missing argument encoding prefix.")
        return json.loads(base64.urlsafe_b64decode(value[4:].encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid encoded tool arguments.") from error


async def execute_tool(name, encoded_arguments, enable_execution):
    arguments = decode_arguments(encoded_arguments)
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    validate_workspace()
    workspace = Workspace(WORKSPACE_ROOT, enable_execution=enable_execution)
    return await workspace.execute(name, arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--commit", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--commit", required=True)
    tool = subparsers.add_parser("tool")
    tool.add_argument("name")
    tool.add_argument("arguments")
    tool.add_argument("--enable-execution", action="store_true")
    args = parser.parse_args()

    try:
        if args.action == "initialize":
            result = asyncio.run(prepare_workspace(args.commit))
        elif args.action == "status":
            validate_workspace()
            head = asyncio.run(run_process(
                ["git", "-C", str(WORKSPACE_ROOT), "rev-parse", "HEAD"], WORKSPACE_ROOT))
            if head["exit_code"] != 0 or head["output"].strip() != args.commit:
                raise RuntimeError("Sandbox workspace is not at the pinned commit.")
            result = {"commit": args.commit, "workspace": str(WORKSPACE_ROOT),
                      "uid": os.geteuid(), "gid": os.getegid(), "mode": "0700"}
        else:
            result = asyncio.run(execute_tool(args.name, args.arguments, args.enable_execution))
        print(json.dumps({"ok": True, "value": result}, separators=(",", ":")))
    except (OSError, RuntimeError, ValueError, UnicodeError) as error:
        print(json.dumps({
            "ok": False,
            "error": str(error),
            "diagnostic": getattr(error, "diagnostic", None),
        }, separators=(",", ":")))
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
