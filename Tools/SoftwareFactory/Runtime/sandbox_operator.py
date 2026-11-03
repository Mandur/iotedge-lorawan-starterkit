# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""Explicit ACA Sandbox disk-image and task lifecycle operations."""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import uuid

from azure.containerapps.sandbox import (
    EgressHostRule,
    EgressPolicy,
    RegistryCredentials,
    SandboxGroupClient,
    endpoint_for_region,
)

from sandbox_runtime import (
    SUBSCRIPTION,
    TENANT,
    SandboxTarget,
    _value,
    worker_command,
)


REGISTRY = "loracivpgdgbnkyeh4u"
REGISTRY_SERVER = f"{REGISTRY}.azurecr.io"
IMAGE_REPOSITORY = f"{REGISTRY_SERVER}/lorawan/factory"
IMAGE_REFERENCE_PATTERN = re.compile(
    rf"{re.escape(IMAGE_REPOSITORY)}@sha256:[0-9a-f]{{64}}")
RESOURCE_TIERS = {"M": ("1000m", "2048Mi"), "L": ("2000m", "4096Mi")}
WORKSPACE_INIT_TIMEOUT = 520
EGRESS_HOSTS = (
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "api.nuget.org",
    "globalcdn.nuget.org",
    "packagefeedproxy.microsoft.io",
)


def image_reference(value):
    if not isinstance(value, str) or not IMAGE_REFERENCE_PATTERN.fullmatch(value):
        raise ValueError(f"Image must be an immutable digest under {IMAGE_REPOSITORY}.")
    return value


def disk_image_matches(disk_image, expected_reference):
    image = _value(disk_image, "image")
    actual = _value(image, "base")
    if actual != expected_reference:
        raise ValueError("Disk image source does not match the approved immutable OCI digest.")
    status = _value(_value(disk_image, "status"), "state")
    if not status or status.lower() not in {"ready", "succeeded"}:
        raise ValueError(f"Disk image is not verified ready (state: {status or 'unknown'}).")


def task_labels(task_id, commit):
    try:
        canonical_task_id = str(uuid.UUID(task_id))
    except ValueError as error:
        raise ValueError("Task ID must be a UUID.") from error
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Repository commit must be a full lowercase SHA.")
    return {"job-id": canonical_task_id, "repo-commit": commit}


def disk_image_name(resource_id):
    if not isinstance(resource_id, str):
        raise ValueError("Disk image ID must be the full ACA Sandbox disk-image resource ID.")
    parts = resource_id.rstrip("/").split("/")
    if len(parts) < 2 or parts[-2].lower() != "diskimages":
        raise ValueError("Disk image ID must be the full ACA Sandbox disk-image resource ID.")
    name = parts[-1]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,90}", name):
        raise ValueError("Disk image resource ID contains an invalid name.")
    return name


def default_egress_policy():
    return EgressPolicy(
        default_action="Deny",
        host_rules=[EgressHostRule(pattern=host, action="Allow") for host in EGRESS_HOSTS],
        traffic_inspection="Full",
    )


def create_disk_image(client, base_image, name, registry_credentials):
    base_image = image_reference(base_image)
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", name):
        raise ValueError("Disk image name must be a lowercase alphanumeric slug.")
    disk = client.begin_create_disk_image(
        base_image,
        name=name,
        registry_credentials=registry_credentials,
        polling_timeout=1800,
        polling_interval=10,
    ).result()
    disk_image_matches(disk, base_image)
    return disk


def create_sandbox(client, disk_image_id, base_image, task_id, commit, tier):
    base_image = image_reference(base_image)
    if tier not in RESOURCE_TIERS:
        raise ValueError("Choose an explicit sandbox resource tier: M or L.")
    disk_image = client.get_disk_image(disk_image_name(disk_image_id))
    actual_id = _value(disk_image, "id")
    if not actual_id or actual_id.casefold() != disk_image_id.casefold():
        raise ValueError("Disk image resource ID does not match the selected Sandbox group.")
    disk_image_matches(disk_image, base_image)
    cpu, memory = RESOURCE_TIERS[tier]
    sandbox = client.begin_create_sandbox(
        disk_id=disk_image_id,
        cpu=cpu,
        memory=memory,
        auto_suspend_seconds=300,
        auto_suspend_mode="Disk",
        labels=task_labels(task_id, commit),
        egress_policy=default_egress_policy(),
        polling_timeout=300,
        polling_interval=3,
    ).result()
    return sandbox


def verify_sandbox_task(sandbox, task_id, commit):
    current = sandbox.get()
    labels = _value(current, "labels", {}) or {}
    expected = task_labels(task_id, commit)
    if _value(current, "id") != sandbox.sandbox_id:
        raise ValueError("Sandbox identity changed during the operation.")
    if any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError("Sandbox labels do not match the requested task and commit.")
    return current


def require_approval(sandbox_id, confirmation):
    if confirmation != sandbox_id:
        raise ValueError("Mutation requires --confirm-sandbox-id with the exact sandbox ID.")


def azure_cli(*arguments, timeout=60):
    executable = shutil.which("az")
    if executable is None:
        raise FileNotFoundError("Azure CLI is required for ACA Sandbox operations.")
    return subprocess.run(
        [executable, *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def verify_caller():
    account = json.loads(azure_cli(
        "account", "show", "--subscription", SUBSCRIPTION, "--output", "json").stdout)
    if account.get("id") != SUBSCRIPTION or account.get("tenantId") != TENANT:
        raise ValueError("Azure CLI account differs from the approved subscription and tenant.")


def registry_credentials():
    result = json.loads(azure_cli(
        "acr", "login", "--name", REGISTRY, "--expose-token",
        "--subscription", SUBSCRIPTION, "--output", "json",
    ).stdout)
    if result.get("loginServer") != REGISTRY_SERVER:
        raise ValueError("Azure CLI returned a different container registry.")
    username, token = result.get("username"), result.get("accessToken")
    if not username or not token or any(char.isspace() for char in token):
        raise ValueError("Azure CLI did not return valid short-lived ACR credentials.")
    return RegistryCredentials(username=username, token=token)


def make_client(region, resource_group, sandbox_group, credential, read_timeout=60):
    return SandboxGroupClient(
        endpoint_for_region(region),
        credential,
        subscription_id=SUBSCRIPTION,
        resource_group=resource_group,
        sandbox_group=sandbox_group,
        retry_total=0,
        connection_timeout=10,
        read_timeout=read_timeout,
    )


def operation_read_timeout(action):
    return WORKSPACE_INIT_TIMEOUT + 20 if action == "create-sandbox" else 60


def operator_target(args):
    environment = {
        "ACA_REGION": args.region,
        "ACA_RESOURCE_GROUP": args.resource_group,
        "ACA_SANDBOX_GROUP": args.sandbox_group,
        "ACA_SANDBOX_ID": getattr(args, "sandbox_id", None) or "pending",
        "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
        "AZURE_TENANT_ID": TENANT,
        "FACTORY_TASK_ID": getattr(args, "task_id", None) or str(uuid.uuid4()),
        "FACTORY_REPOSITORY_COMMIT": getattr(args, "commit", None) or "0" * 40,
    }
    return SandboxTarget.from_env(environment)


def parser_for_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="swedencentral")
    parser.add_argument("--resource-group", default="rg-lorawan-software-factory")
    parser.add_argument("--sandbox-group", required=True)
    commands = parser.add_subparsers(dest="action", required=True)

    image = commands.add_parser("create-image", help="Convert one approved ACR digest to a disk image.")
    image.add_argument("--image", required=True)
    image.add_argument("--name", required=True)
    image.add_argument("--approve", action="store_true", required=True)

    create = commands.add_parser("create-sandbox", help="Create one task-bound sandbox from a ready disk image.")
    create.add_argument("--image", required=True)
    create.add_argument("--disk-image-id", required=True)
    create.add_argument("--task-id", required=True)
    create.add_argument("--commit", required=True)
    create.add_argument("--tier", choices=sorted(RESOURCE_TIERS), required=True)
    create.add_argument("--approve", action="store_true", required=True)

    for action in ("status", "resume", "stop", "delete"):
        command = commands.add_parser(action)
        command.add_argument("--sandbox-id", required=True)
        command.add_argument("--task-id", required=True)
        command.add_argument("--commit", required=True)
        if action in {"resume", "stop", "delete"}:
            command.add_argument("--confirm-sandbox-id", required=True)
    return parser


def main():
    args = parser_for_cli().parse_args()
    if args.action == "create-image":
        image_reference(args.image)
        operator_target(args)
        verify_caller()
        from azure.identity import AzureCliCredential

        with AzureCliCredential(tenant_id=TENANT) as credential:
            client = make_client(args.region, args.resource_group, args.sandbox_group, credential)
            try:
                disk = create_disk_image(client, args.image, args.name, registry_credentials())
                print(json.dumps({"disk_image_id": disk.id, "source_image": args.image,
                                  "state": _value(_value(disk, "status"), "state")}))
            finally:
                client.close()
        return

    target = operator_target(args)
    if args.action == "create-sandbox":
        image_reference(args.image)
        task_labels(args.task_id, args.commit)
        args.task_id = task_labels(args.task_id, args.commit)["job-id"]
    elif args.action in {"resume", "stop", "delete"}:
        require_approval(args.sandbox_id, args.confirm_sandbox_id)

    verify_caller()
    from azure.identity import AzureCliCredential

    with AzureCliCredential(tenant_id=TENANT) as credential:
        client = make_client(
            args.region, args.resource_group, args.sandbox_group, credential,
            operation_read_timeout(args.action))
        try:
            if args.action == "create-sandbox":
                sandbox = create_sandbox(
                    client, args.disk_image_id, args.image, args.task_id, args.commit, args.tier)
                print(json.dumps({"sandbox_id": sandbox.sandbox_id,
                                  "task_id": args.task_id, "commit": args.commit,
                                  "disk_image_id": args.disk_image_id, "image": args.image,
                                  "tier": args.tier, "state": "Running"}))
                initialized = sandbox.exec(
                    worker_command(
                        "initialize", "--commit", args.commit,
                        timeout_seconds=WORKSPACE_INIT_TIMEOUT),
                    working_directory="/",
                )
                if initialized.exit_code != 0:
                    raise RuntimeError(
                        f"Sandbox created but workspace initialization failed "
                        f"(exit {initialized.exit_code}): {initialized.stdout} {initialized.stderr}")
                print(initialized.stdout)
                return

            sandbox = client.get_sandbox_client(args.sandbox_id)
            current = verify_sandbox_task(sandbox, args.task_id, args.commit)
            state = _value(current, "state")
            if args.action == "status":
                print(json.dumps({"sandbox_id": sandbox.sandbox_id, "state": state,
                                  "labels": _value(current, "labels", {})}))
            elif args.action == "resume":
                if not state or state.lower() not in {"stopped", "suspended"}:
                    raise ValueError(f"Resume requires a stopped or suspended sandbox, not {state!r}.")
                sandbox.resume()
                current = sandbox.wait_for_running(timeout=180, poll_interval=3)
                verify_sandbox_task(sandbox, args.task_id, args.commit)
                print(json.dumps({"sandbox_id": sandbox.sandbox_id,
                                  "state": _value(current, "state")}))
            elif args.action == "stop":
                if not state or state.lower() != "running":
                    raise ValueError(f"Stop requires a running sandbox, not {state!r}.")
                sandbox.stop()
                deadline = time.monotonic() + 180
                while True:
                    current = sandbox.get()
                    state = _value(current, "state")
                    if state and state.lower() == "stopped":
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Stop was requested but sandbox state is {state!r}; do not retry blindly.")
                    time.sleep(3)
                print(json.dumps({"sandbox_id": sandbox.sandbox_id, "state": state}))
            else:
                sandbox.delete()
                print(json.dumps({"sandbox_id": sandbox.sandbox_id,
                                  "result": "delete requested; completion not confirmed"}))
        finally:
            client.close()


if __name__ == "__main__":
    main()
