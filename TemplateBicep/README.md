# Deploying infrastructure using Bicep

This folder contains the Bicep files to deploy the Starter-Kit infrastructure.

This guide shows how to manually deploy it.

## Prerequisites

Make sure to have the following tool installed:

* [AZ CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)

## Deploying the infrastructure

Step 1: Login to Azure using the AZ CLI:

```plain
az login --tenant <tenant-id>
```

Step 2: Create target resource group

```plain
az group create --location <location> --resource-group <resource-group-name>
```

Step 3: Start deployment

```plain
az deployment group create --resource-group <resource-group-name> --template-file ./main.bicep --parameters uniqueSolutionPrefix="<unique-name>" resetPin=<based-on-your-setup> deployDevice=true edgeGatewayName="<gateway-device-name>" useDiscoveryService=true
```

## Developing

### Minimal PR CI infrastructure

The `Build Docker Images` job in `.github/workflows/ci.yaml` needs only a
container registry and Key Vault, not the full Starter-Kit deployment. Deploy
`ci.bicep` separately to avoid provisioning IoT Hub, Redis, compute, or monitoring:

```powershell
az group create --name lora --location eastus
az deployment group create --name github-pr-ci --resource-group lora --template-file .\TemplateBicep\ci.bicep
```

Run these commands from the repository root using the intended Azure subscription.
The template uses ACR Basic (the lowest registry tier), Key Vault Standard, and
a user-assigned managed identity with no standing credential. ACR Basic in East US
has a public list price of USD 0.1666/day (about USD 5/month), excluding excess
storage, network transfer, taxes, and Key Vault operations. It remains billable
while idle. This template does not provision the separate hardware-dependent
`LoRa E2E CI` environment.

Set the following GitHub Actions secrets in the repository's **CI** environment
using the corresponding nonsecret deployment outputs:

| Environment secret | Deployment output |
| --- | --- |
| `AZURE_CLIENT_ID` | `clientId` |
| `AZURE_TENANT_ID` | `tenantId` |
| `AZURE_SUBSCRIPTION_ID` | `subscriptionId` |
| `KEYVAULT_NAME` | `keyVaultName` |

The template stores `CI-ACR-NAME` and `CI-ACR-CREDENTIALS` directly in Key Vault.
The registry admin account is enabled for compatibility with the current Docker
login step; its password is never a deployment output. If that password is
rotated, redeploy this template to refresh the vault secret.

GitHub OIDC is restricted to `repo:Mandur/iotedge-lorawan-starterkit:environment:CI`
by default; set the `repository` parameter for a different fork. The identity
can read secrets only in this vault and has no subscription-wide role. A custom
role grants `Microsoft.KeyVault/vaults/read` and `Microsoft.KeyVault/vaults/write`
only on this vault so CI can update its firewall. Azure does not expose a
firewall-only write permission: this also permits other vault configuration
changes, but does not grant role-assignment management.

Key Vault uses **Allow public access from specific virtual networks and IP
addresses** (`publicNetworkAccess: Enabled`, `defaultAction: Deny`) with no
trusted-service bypass. The Docker job discovers its public IPv4 address, adds
only that `/32`, enables the selected-networks mode, and waits for data-plane
access before reading secrets. An `always()` cleanup step removes and verifies
removal of the rule, including after failure or normal cancellation. Pre-existing
rules are preserved. Docker jobs are serialized across branches to avoid removing
a rule used by another run sharing the same IP. Forced runner termination can
prevent cleanup; remove any abandoned `/32` manually. Redeploying the template
resets the vault to its empty allowlist, so do not redeploy during a CI build.

ACR Basic uses an authenticated public endpoint; registry IP filtering requires
the more expensive Premium tier. No private networking or paid self-hosted runner
is provisioned.

An inherited Azure Policy can override `publicNetworkAccess` to `Disabled` even
when the update reports success. In that case, obtain an approved exception
limited to this vault and the public-network policy; CI cannot create exemptions.
For the deployed `lora` group, the user-approved exemption
`lora-ci-runner-ip-access` applies only to vault `lora-ci-vpgdgbnkyeh4u` and
reference `KeyVaultPublicNetworkModify` in the inherited
`mcapsgovdeploypolicies` assignment. It leaves all other policies enforced and is
managed separately from `ci.bicep`. Without that exemption, runner allowlisting
will fail. The workflow explicitly detects a policy override before reading
secrets.

Keep the CI environment's reviewer approval gate: the job executes PR code
with access to registry credentials. Fork PRs do not receive these secrets.
Existing runs waiting for CI approval still need approval before they can start.

### Device creation

For device creation debugging, there are alternatives other than deploying the whole solution:

Option 1: Run bash script locally

```plain
FACADE_SERVER_URL="https://myapp.com/api" IOTHUB_CONNECTION_STRING="<iothub-connection-string>" LORA_CLI_URL="https://github.com/Azure/iotedge-lorawan-starterkit/releases/download/v<current-version>/lora-cli.linux-x64.tar.gz" EDGE_GATEWAY_NAME="<iotedge-device-name>" STATION_DEVICE_NAME="<concentrator-device-name>" DEPLOY_DEVICE=1 RESET_PIN=<concentrator-reset-pin> LORA_VERSION="<lora-starter-kit-release-version>" ./create_device.sh
```

Option 2: Run the device provisioning Bicep

```plain
az deployment group create --resource-group <resource-group-name> --template-file ./devices.bicep --parameters iothubName="<unique-name>" 
resetPin=<based-on-your-setup> edgeGatewayName="<gateway-device-name>" spiSpeed=<based-on-your-setup> spiDev=<based-on-your-setup> functionAppName="<function-name>" region="<lora-region>" stationEui="<concentrator-device-name>" logAnalyticsName="<log-analytics-name>" 
loraCliUrl="<lora-cli-linux-musl-version-download-url>" version="<lora-starter-kit-release-version>" deployDevice=true
```
