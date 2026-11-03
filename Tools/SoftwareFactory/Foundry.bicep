targetScope = 'resourceGroup'

@description('Globally unique name for a new, dedicated Foundry account. Do not target a shared account.')
@minLength(2)
@maxLength(64)
param accountName string

@description('Explicitly selected Azure region supporting the requested model and hosted agents.')
param location string

@description('Name of the software factory project within the dedicated account.')
param projectName string = 'lorawan-software-factory'

@description('GPT-6 Sol version observed in the Azure catalog. Recheck availability before deployment.')
param modelVersion string = '2026-09-22'

@description('Model deployment name consumed by the agent runtime.')
param modelDeploymentName string = 'gpt-6-sol'

@description('Standard billing scope. GlobalStandard may process requests outside the resource region.')
@allowed([
  'GlobalStandard'
  'DataZoneStandard'
])
param modelSku string = 'GlobalStandard'

@description('Model capacity in thousands of tokens per minute. Check live regional quota before deployment.')
@minValue(1)
param modelCapacity int = 10

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  // Account child writes conflict when model and project provisioning overlap.
  dependsOn: [
    model
  ]
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'LoRaWAN software factory'
    description: 'Custom hosted coding agents using the shared repository toolchain image.'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelDeploymentName
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-6-sol'
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

output accountResourceId string = account.id
output projectResourceId string = project.id
output modelDeployment string = model.name
