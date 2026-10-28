@description('GitHub repository allowed to authenticate through the CI environment.')
param repository string = 'Mandur/iotedge-lorawan-starterkit'

param location string = resourceGroup().location

var suffix = uniqueString(resourceGroup().id)

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'loraci${suffix}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'lora-ci-${suffix}'
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
    }
    accessPolicies: []
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'lora-github-ci'
  location: location
}

resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identity
  name: 'github-ci-environment'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${repository}:environment:CI'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

resource secretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'Key Vault Secrets User')
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource firewallRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'ci-keyvault-firewall')
  properties: {
    roleName: 'LoRa CI Key Vault firewall (${suffix})'
    description: 'Read and update the CI vault configuration to manage temporary runner firewall rules.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.KeyVault/vaults/read'
          'Microsoft.KeyVault/vaults/write'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
    assignableScopes: [
      resourceGroup().id
    ]
  }
}

resource firewallManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'ci-keyvault-firewall')
  scope: vault
  properties: {
    roleDefinitionId: firewallRole.id
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource registryName 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'CI-ACR-NAME'
  properties: {
    value: registry.name
  }
}

resource registryPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'CI-ACR-CREDENTIALS'
  properties: {
    value: registry.listCredentials().passwords[0].value
  }
}

output clientId string = identity.properties.clientId
output tenantId string = tenant().tenantId
output subscriptionId string = subscription().subscriptionId
output keyVaultName string = vault.name
output registryLoginServer string = registry.properties.loginServer
