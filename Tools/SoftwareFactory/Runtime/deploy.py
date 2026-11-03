# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""Archived Foundry Hosted Agent implementation; the CLI is intentionally disabled."""

import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.request
import uuid

PROJECT_ID = "/subscriptions/f1474e0a-622f-410f-933e-d632635d1e03/resourceGroups/rg-lorawan-software-factory/providers/Microsoft.CognitiveServices/accounts/lorawan-factory-f1474e0a/projects/lorawan-software-factory"
PROJECT_ENDPOINT = "https://lorawan-factory-f1474e0a.services.ai.azure.com/api/projects/lorawan-software-factory"
AGENT_NAME = "lorawan-factory-coder"
SUBSCRIPTION = "f1474e0a-622f-410f-933e-d632635d1e03"
TENANT = "fea4bf20-a5c7-4467-a97b-4322661134d5"
REGISTRY = "loracivpgdgbnkyeh4u"
REGISTRY_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/lora/providers/Microsoft.ContainerRegistry/registries/{REGISTRY}"
ACR_PULL = "7f951dda-4ed3-4680-a7ca-43fe172d538d"


def azure(*args):
    executable = shutil.which("az")
    if executable is None:
        raise FileNotFoundError("Azure CLI is required for reviewed pull setup and deployment.")
    result = subprocess.run(
        [executable, *args, "--subscription", SUBSCRIPTION, "--output", "json"],
        check=True, capture_output=True, text=True, timeout=60)
    return json.loads(result.stdout)


def pull_plan(project_metadata, expected_principal):
    identity = project_metadata.get("identity") or {}
    principal = identity.get("principalId")
    if (project_metadata.get("id", "").lower() != PROJECT_ID.lower()
            or project_metadata.get("properties", {}).get("provisioningState") != "Succeeded"
            or identity.get("type") != "SystemAssigned"
            or identity.get("tenantId") != TENANT or not principal):
        raise ValueError("Approved project system-assigned identity is not ready.")
    if str(uuid.UUID(expected_principal)) != principal.lower():
        raise ValueError("Reviewed principal differs from the current project managed identity.")
    directory = azure("ad", "sp", "show", "--id", principal)
    if (directory.get("id") != principal or directory.get("accountEnabled") is not True
            or directory.get("servicePrincipalType") != "ManagedIdentity"):
        raise ValueError("Exact project managed identity is not enabled in Entra.")
    return {"agent": AGENT_NAME, "principal": principal, "principal_type": "ServicePrincipal",
            "role": "AcrPull", "scope": REGISTRY_ID,
            "blast_radius": "Pull every repository in this registry; no push, delete or role management."}


def project_metadata():
    return azure("rest", "--method", "get", "--url",
                 f"https://management.azure.com{PROJECT_ID}?api-version=2025-06-01")


def verify_caller():
    account = azure("account", "show")
    if account["id"] != SUBSCRIPTION or account["tenantId"] != TENANT:
        raise ValueError("Azure CLI subscription or tenant differs from the approved target.")
    caller = azure("ad", "signed-in-user", "show")["id"]
    assignments = azure("role", "assignment", "list", "--assignee", caller,
                        "--scope", PROJECT_ID, "--include-inherited", "--include-groups")
    roles = {item["roleDefinitionName"] for item in assignments if not item.get("condition")}
    if not (roles & {"Foundry Project Manager", "Azure AI Project Manager", "Foundry Owner", "Azure AI Owner"}
            or (roles & {"Owner", "Contributor"} and roles & {"Foundry User", "Azure AI User"})):
        raise ValueError("Verified project management plus Foundry data-plane permissions are required.")


def verify_registry():
    registry = azure("acr", "show", "--name", REGISTRY)
    if (registry["id"].lower() != REGISTRY_ID.lower()
            or registry["loginServer"] != f"{REGISTRY}.azurecr.io"
            or registry.get("roleAssignmentMode") != "LegacyRegistryPermissions"
            or registry.get("publicNetworkAccess") != "Enabled"):
        raise ValueError("Registry identity, role mode or network configuration requires a new review.")
    policy = azure("acr", "config", "authentication-as-arm", "show", "--registry", REGISTRY)
    if policy.get("status") != "enabled":
        raise ValueError("ACR ARM-audience authentication is not enabled; no policy will be changed.")


def has_pull_access(plan):
    assignments = azure("role", "assignment", "list", "--assignee", plan["principal"],
                        "--scope", REGISTRY_ID, "--include-inherited")
    return any(item["roleDefinitionId"].split("/")[-1].lower() == ACR_PULL
               and not item.get("condition") for item in assignments)


def setup_pull(expected_principal, approve=False):
    raise RuntimeError(
        "Foundry Hosted Agent registry setup is retired; this module cannot change roles.")


def definition(image, commit, registry_connection=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.azurecr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}", image):
        raise ValueError("An approved ACR repository@sha256 digest is required; tags are rejected.")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Repository commit must be a full lowercase SHA.")
    container = {"image": image}
    if registry_connection is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", registry_connection):
            raise ValueError("Registry connection must be an existing connection name.")
        container["registry_connection_id"] = registry_connection
    return {
        "kind": "hosted",
        "cpu": "2",
        "memory": "4Gi",
        "container_configuration": container,
        "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
        "environment_variables": {
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-6-sol",
            "PYTHONNOUSERSITE": "1",
            "FACTORY_HOSTED": "1",
            "FACTORY_REPOSITORY_COMMIT": commit,
            "FACTORY_ENABLE_EXECUTION": "0",
        },
        "session_configuration": {"idle_timeout_seconds": 120},
    }


def verify_region(credential):
    token = credential.get_token("https://management.azure.com/.default").token
    request = urllib.request.Request(
        f"https://management.azure.com{PROJECT_ID}?api-version=2025-06-01",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        project = json.load(response)
    if project["id"].lower() != PROJECT_ID.lower() or project["location"].lower() != "swedencentral":
        raise ValueError("Approved project identity/region changed; refusing deployment.")
    if project["properties"].get("provisioningState") != "Succeeded":
        raise ValueError("Approved project provisioning has not succeeded.")


def deploy(payload, expected_principal):
    raise RuntimeError(
        "Foundry Hosted Agent deployment is retired; use the explicit ACA Sandbox operator.")


def main():
    raise SystemExit(
        "Foundry Hosted Agent deployment is retired. Use the explicit ACA Sandbox operator; "
        "this archived CLI will not create versions or change roles.")


if __name__ == "__main__":
    main()
