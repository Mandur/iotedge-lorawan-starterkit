# Contributing

## Shared development environment

Open the repository in a Development Container using `.devcontainer/devcontainer.json`.
On Windows, use Docker Desktop with Linux containers. The initial reference platform
is Linux amd64, including on ARM hosts through emulation.

The image pins the .NET SDK to `global.json` and includes PowerShell and Git.
Initialization and verification tools are also installed at `/opt/lorawan-factory`
in the image. When calling those copies, pass `-Workspace` explicitly. Rebuild the
image after changing tooling; the devcontainer and CI use the installed copies.
Tracked C# and T4 files use LF line endings so Windows-mounted workspaces and
Linux checkouts have the same formatter input.
Workspace initialization restores repository tools and packages; it also runs
without an editor:

```powershell
pwsh -NoProfile -File Tools\SoftwareFactory\Initialize-Workspace.ps1
pwsh -NoProfile -File Tools\SoftwareFactory\Verify-Repository.ps1
```

Verification regenerates T4 outputs, rejects generated-code drift, builds the
solution and decoder sample in Release, and runs unit and CLI tests. It fails on
the first unsuccessful command. It does not deploy Azure resources or run cloud
or hardware E2E tests.

Both commands accept an explicit `-NuGetConfig` path for an approved alternate
feed configuration. There is no automatic source substitution, ignored restore
failure, or disabled vulnerability audit.

`Test-Commands.ps1` and `Test-Workspace.ps1` in the same directory exercise command
failure handling and workspace orchestration without downloading packages.
The orchestration checks mock SDK commands; they do not replace application tests.
The Shared Development Environment workflow runs these checks and attempts the
repository build in the canonical image, without cloud credentials or publishing.

The development container intentionally has no host Docker socket or privileged
mode. Redis integration tests require a separately proven isolated Docker
topology; do not assume that mounting a socket or adding a Redis service is
sufficient. The existing fixture creates a container and connects to
`localhost:6001`. Where that topology is available, explicitly add
`-IncludeIntegration` to the verification command. Without it, integration tests
are reported as not run, not as passing.

The canonical image also includes a custom bounded coding runtime for the
approved GPT-6 Sol deployment. See
[runtime usage, safety boundaries, and deployment status](Tools/SoftwareFactory/Runtime/README.md)
before starting it. Foundry's managed Copilot harness cannot use this image.
The editor does not start the runtime automatically. Foundry supplies the model;
Azure Container Apps Sandboxes supplies remote compute. The earlier Foundry
Hosted Agent compute path is retired. Infrastructure provisioning and local
runtime tests are verified, but remote sandbox coding remains unverified.
Pin local orchestration and sandbox disk-image conversion to the same published
registry digest. Separate builds are not proof of identical images, and disk
conversion requires its own platform validation.

### Foundry infrastructure

`Tools/SoftwareFactory/Foundry.bicep` provisions a dedicated Foundry account,
project, and `gpt-6-sol` model deployment using Entra authentication only.
It does not provision a hosted agent, registry, role assignments, or a factory
controller. FoundryX tenant onboarding is separate from standard Azure Foundry
and is not required to deploy this template.

Before provisioning, explicitly choose the subscription, resource group, and
region, and check the live model catalog and remaining quota. The template pins
model version `2026-09-22`; availability is not guaranteed in every subscription
or region. The default capacity is 10 thousand tokens per minute with
`GlobalStandard` billing, which permits processing outside the resource region.
Choose `DataZoneStandard` explicitly if its data-boundary behavior is required
and supported. Neither setting guarantees hosted-agent regional support.

Compile without creating cloud resources:

```powershell
az bicep build --file Tools\SoftwareFactory\Foundry.bicep --stdout
```

After approving a dedicated target and creating its resource group, preview
the deployment with explicitly chosen parameters:

```powershell
az deployment group what-if --subscription <subscription-id> --resource-group <dedicated-resource-group> --template-file Tools\SoftwareFactory\Foundry.bicep --parameters accountName=<globally-unique-name> location=<approved-region>
```

Review the preview before using the same arguments with `az deployment group
create`. Do not target existing shared Foundry accounts with this template.
Model deployments are billable; infrastructure deployment alone is not evidence
that the custom agent or the same-image local/hosted execution is working.

## Contribution policy

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit <https://cla.microsoft.com>.

When you submit a pull request, a CLA-bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.
