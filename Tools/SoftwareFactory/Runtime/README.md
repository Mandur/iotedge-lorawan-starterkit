# Custom coding runtime

The software-factory runtime uses the existing Foundry `gpt-6-sol` deployment
for model inference and Azure Container Apps Sandboxes for remote coding
workspaces. It is not the managed Copilot harness or a complete
controller/reviewer factory. Issue orchestration, independent reviews, PR
creation, and deterministic CI gates remain future work. Humans approve all
merges.

Foundry Hosted Agent compute is superseded. The legacy deployment CLI and
`smoke.py --hosted` are disabled. Earlier failed hosting experiments do not
establish a working remote coding runtime.

## Trust and execution boundaries

The trusted local orchestrator holds short-lived model and sandbox-management
tokens in memory. Those credentials are never passed to the sandbox worker.
Do not mount credentials, unrelated directories, a Docker socket, or a
credential-bearing checkout. There is no privileged or root fallback.

The unauthenticated local Responses listener must be published only to
loopback, never a shared host or the internet. Concurrent coding requests are
rejected. Interrupted work and model conversation history are not replayed.

File tools list directories and read/replace UTF-8 files up to 64 KiB. Writes
require the previous content's SHA256, or `new`. Hidden paths, common credential
files, symlinks, hardlinks, special files, and build outputs are excluded.
There is no arbitrary shell, delete, Git push, PR, merge, or cloud-management
tool. Enumeration, tool calls, output, model calls, and elapsed time are bounded.
Responses contain actual tool outcomes and content hashes, separate from model
prose.

These application checks are not an OS sandbox or a secret scanner. Local
execution shares the orchestrator's container identity. Optional fixed
`initialize` and `repository` verification lanes execute repository-controlled
MSBuild, T4, restore, and test code; they are disabled by default. Enabling
them is explicit trust in that repository code. They never implicitly run
Redis integration, cloud E2E, or hardware E2E.

The image installs application code and dependencies in root-owned `/opt`,
runs as `app` (UID 1654), and uses Python isolated mode. The sandbox worker
does not assume the service preserves OCI `USER`. It checks actual effective
UID, workspace owner, private mode, and writability; failures report numeric
UID/GID, owner/mode, HOME metadata, and errno. It never uses `chown`, repairs
permissions, recursively resets contents, or falls back to ephemeral storage.

## Build and local use

From the repository root with Docker Desktop Linux containers:

```powershell
docker build --platform linux/amd64 --file .devcontainer\Dockerfile --tag lorawan-factory-dev:local .
docker run --rm --init --cap-drop=ALL --security-opt=no-new-privileges --workdir /opt/lorawan-factory/Runtime lorawan-factory-dev:local python -m unittest -v test_runtime test_protocol test_hosted_startup test_sandbox
docker run --rm --init --cap-drop=ALL --security-opt=no-new-privileges lorawan-factory-dev:local pwsh -NoProfile -File /opt/lorawan-factory/Test-RuntimeCommands.ps1
```

The canonical image includes .NET SDK 10.0.100, Git, PowerShell, Python, the
runtime, and shared repository verification scripts. Python dependencies are
pinned with SHA256 hashes in `requirements.lock`; installation enforces hashes.
Use uv 0.10.11 to update the lock:

```powershell
uv pip compile --index-url https://packagefeedproxy.microsoft.io/pypi/simple/ --python-platform x86_64-manylinux_2_39 --python-version 3.12 --generate-hashes --no-header --output-file Tools\SoftwareFactory\Runtime\requirements.lock Tools\SoftwareFactory\Runtime\requirements.in
```

The configured mirror can supply additional MD5 hashes; remove those entries
while retaining each package's SHA256 hashes before using pip, which rejects
MD5 in hash-enforced requirements. Never disable TLS or hash validation.
Do not install packages into mounted workspaces or the user's site directory.

Start the runtime with an explicitly chosen disposable local checkout:

```powershell
pwsh -NoProfile -File Tools\SoftwareFactory\Start-Runtime.ps1 -Image lorawan-factory-dev:local -AllowUnpublishedImage -Workspace C:\path\to\disposable-checkout
```

The helper verifies the approved Azure tenant/subscription and obtains a
short-lived Foundry inference token through Azure CLI. Tokens are forwarded by
environment name, not command-line value or file. Docker administrators can
inspect container environments. Tokens are not refreshed; restart after expiry.
The devcontainer does not start the listener automatically.

Readiness checks process availability, not model authorization or coding:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/readiness
```

In a Python environment containing the pinned dependencies, run the explicit
billable coding smoke:

```powershell
python Tools\SoftwareFactory\Runtime\smoke.py
```

This writes and reads one uniquely named file and checks actual tool evidence
against its expected SHA256. It does not remove that file or run verification.

## Sandbox infrastructure

`Tools\SoftwareFactory\Sandbox.Infrastructure.bicep` and
`Deploy-SandboxInfrastructure.ps1` target the existing approved subscription
and resource group. They provision:

- `lorawan-factory-sandboxes` in Sweden Central, capped at one sandbox, with
  0.25 CPU, 0.5 GiB memory, 20 GiB disk defaults and a 3600-second timeout.
- SandboxGroup Data Owner access for the current signed-in user, scoped only
  to that group.
- `lorawan-factory-sandbox-law` with 30-day retention and linked workspace-based
  Application Insights `lorawan-factory-sandbox-ai`.

These resources were provisioned successfully. The operator verifies existing
resources read-only and refuses automatic repair of partial or mismatched
infrastructure. For a new target deployment, it compiles Bicep, validates the
exact What-If resource set, and requires `-Deploy` to write:

```powershell
pwsh -NoProfile -File Tools\SoftwareFactory\Deploy-SandboxInfrastructure.ps1
pwsh -NoProfile -File Tools\SoftwareFactory\Deploy-SandboxInfrastructure.ps1 -Deploy
```

The documented Sandbox Group API is `2026-02-01-preview`. Local Bicep type
metadata for it is unavailable (BCP081), so actual ARM provisioning and returned
properties are checked. No Container Apps managed environment is required.
Existing Foundry resources and model capacity are not modified.

The group reserves no warm compute. Monitoring ingestion and retention are
usage-billed. Running sandboxes incur CPU/memory charges; retained custom
images, snapshots, and volumes can incur storage charges. Provisioning does
not create any sandbox, disk image, or telemetry export.

## Publish once, consume the same digest

With registry authentication already configured, explicitly publish the tested
local image using `Publish-Image.ps1`. This is a separate cloud write:

```powershell
pwsh -NoProfile -File Tools\SoftwareFactory\Publish-Image.ps1 -RegistryServer loracivpgdgbnkyeh4u.azurecr.io -Repository lorawan/factory -Tag <unique-tag> -LocalImage lorawan-factory-dev:local
```

The helper tags the exact local image ID, pushes without rebuilding, resolves
the registry manifest digest, pulls it, and checks its config/image ID against
the original. Use the returned immutable repository digest for both local
orchestration and disk-image conversion. Two independent builds never prove
image parity. OCI-to-disk conversion is a service transformation, not proof of
identical filesystem or user behavior.

## Explicit sandbox image and lifecycle operations

Use the new `Microsoft.App/sandboxGroups` service and pinned
`azure-containerapps-sandbox`, not older Dynamic Sessions/session pools.
The SDK uses `https://dynamicsessions.io/.default` as its token audience but
routes to `https://management.swedencentral.azuredevcompute.io`.

After separately approving image publication/import and workload creation:

```powershell
$image = 'loracivpgdgbnkyeh4u.azurecr.io/lorawan/factory@sha256:<64-hex-digest>'
python Tools\SoftwareFactory\Runtime\sandbox_operator.py --sandbox-group lorawan-factory-sandboxes create-image --image $image --name <unique-name> --approve
python Tools\SoftwareFactory\Runtime\sandbox_operator.py --sandbox-group lorawan-factory-sandboxes create-sandbox --image $image --disk-image-id <returned-full-id> --task-id <task-uuid> --commit <full-lowercase-sha> --tier L --approve
```

The operator verifies the ready disk image's immutable source and full ID,
binds a sandbox to task UUID/commit labels, and initializes only the fixed public
repository at that commit. Existing edits are preserved only when HEAD matches.
Creation sets deny-default egress with explicit public GitHub/package hosts and
300-second disk-mode idle suspension. No model or orchestrator credential is
delivered to the worker.

Tier L explicitly selects 2 CPU/4 GiB; review current pricing before use.
`status`, `resume`, `stop`, and `delete` require sandbox/task/commit identity;
mutations require `--confirm-sandbox-id` with the exact sandbox ID. Startup
never implicitly creates or resumes a sandbox. No automatic cleanup or blind
retry is performed; a request timeout does not prove remote cancellation.

Connect the local orchestrator to an already running sandbox without mounting
a local checkout:

```powershell
pwsh -NoProfile -File Tools\SoftwareFactory\Start-Runtime.ps1 -Image $image -SandboxId <sandbox-id> -SandboxGroup lorawan-factory-sandboxes -TaskId <task-uuid> -RepositoryCommit <full-lowercase-sha>
```

The sandbox runtime requires both task/commit labels and workspace preflight
to match. Verification still requires explicit `-EnableExecution`.

## Verification and observability boundaries

Local runtime validation completed 55 tests with one intentionally skipped
mounted-HOME test; mocked PowerShell startup tests passed. These checks do not
prove remote image import, runtime UID/ownership, egress enforcement, file
behavior, or preservation across stop/resume. Those remain bounded remote
validation prerequisites. Infrastructure provisioning is not coding evidence.
Redis integration was not established by this runtime slice.

Sandbox telemetry is opt-in in each sandbox's `telemetryConfig`. Monitoring
resources alone do not enable exports or prove ingestion. Application Insights
uses a sandbox-group secret resolved outside the worker; Log Analytics direct
ingestion needs additional documented DCE/DCR and identity configuration.
No telemetry secret or export was created. Application Insights ingestion is
distinct from Foundry trace UI visibility; neither is claimed verified.

See the official [overview](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview),
[Bicep quickstart](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-quickstart-bicep),
[regions](https://sandboxes.azure.com/docs/sandboxes/regions),
[telemetry](https://sandboxes.azure.com/docs/sandboxes/telemetry),
and [cost](https://sandboxes.azure.com/docs/sandboxes/cost) documentation before
remote operation.
