// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

@description('Microsoft Entra object ID of the operator who needs sandbox data-plane access.')
param principalId string

@description('Azure region for the sandbox group and monitoring resources.')
param location string = 'swedencentral'

@description('Sandbox group name in the existing software-factory resource group.')
param sandboxGroupName string = 'lorawan-factory-sandboxes'

@description('Dedicated Log Analytics workspace name.')
param workspaceName string = 'lorawan-factory-sandbox-law'

@description('Dedicated Application Insights component name.')
param applicationInsightsName string = 'lorawan-factory-sandbox-ai'

var sandboxDataOwnerRoleId = 'c24cf47c-5077-412d-a19c-45202126392c'
var factoryTags = {
  workload: 'lorawan-software-factory'
  managedBy: 'bicep'
}

resource sandboxGroup 'Microsoft.App/sandboxGroups@2026-02-01-preview' = {
  name: sandboxGroupName
  location: location
  tags: factoryTags
  properties: {
    defaultCpu: '0.25'
    defaultMemory: '0.5Gi'
    defaultDisk: '20Gi'
    maxSandboxCount: 1
    defaultTimeoutSeconds: 3600
    enableDetailedMetrics: false
  }
}

resource sandboxDataOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sandboxGroup.id, principalId, sandboxDataOwnerRoleId)
  scope: sandboxGroup
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', sandboxDataOwnerRoleId)
    principalId: principalId
    principalType: 'User'
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: workspaceName
  location: location
  tags: factoryTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  kind: 'web'
  tags: factoryTags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

output sandboxGroupId string = sandboxGroup.id
output sandboxGroupLocation string = sandboxGroup.location
output workspaceId string = workspace.id
output applicationInsightsId string = applicationInsights.id
