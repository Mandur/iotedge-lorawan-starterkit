# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

"""Billable coding smoke: verifies runtime tool evidence, not just model prose."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid

# Python isolated mode deliberately omits the script directory from imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from deploy import AGENT_NAME, PROJECT_ENDPOINT


def verify_evidence(text, path, content):
    result = json.loads(text)
    if result["model"] != "gpt-6-sol":
        raise ValueError("Unexpected model in runtime evidence.")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    for name in ("write_file", "read_file"):
        if not any(item["name"] == name and item["ok"] and item.get("path") == path
                   and item.get("sha256") == digest for item in result["tools"]):
            raise ValueError(f"No successful {name} evidence for the expected file and content.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.hosted:
        parser.error("Foundry Hosted Agent smoke is retired; use the local runtime connected to an ACA Sandbox.")
    from openai import OpenAI

    path = f"factory-smoke-{uuid.uuid4().hex}.txt"
    content = f"factory-smoke-{uuid.uuid4().hex}"
    prompt = (f"Using write_file, create {path} with exactly this UTF-8 content and no newline: {content}. "
              "Then use read_file to read it back. Do not edit any other file or run verification.")
    if args.hosted:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        credential = DefaultAzureCredential()
        token = get_bearer_token_provider(credential, "https://ai.azure.com/.default")
        base_url = f"{PROJECT_ENDPOINT}/agents/{AGENT_NAME}/endpoint/protocols/openai"
    else:
        credential = None
        token = "local-no-auth"
        base_url = "http://127.0.0.1:8088"
    try:
        with OpenAI(base_url=base_url, api_key=token, timeout=900, max_retries=0) as client:
            response = client.responses.create(
                model="gpt-6-sol", input=prompt, stream=False, store=False)
            if response.status != "completed":
                raise RuntimeError(f"Coding smoke did not complete: {response.status}")
            result = verify_evidence(response.output_text, path, content)
            print(json.dumps({"response_id": response.id, "file": path, "evidence": result}, indent=2))
    finally:
        if credential:
            credential.close()


if __name__ == "__main__":
    main()
