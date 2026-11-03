# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

[CmdletBinding()]
param(
    [switch] $Deploy
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$subscription = 'f1474e0a-622f-410f-933e-d632635d1e03'
$tenant = 'fea4bf20-a5c7-4467-a97b-4322661134d5'
$resourceGroup = 'rg-lorawan-software-factory'
$location = 'swedencentral'
$sandboxGroupName = 'lorawan-factory-sandboxes'
$workspaceName = 'lorawan-factory-sandbox-law'
$applicationInsightsName = 'lorawan-factory-sandbox-ai'
$roleName = 'Container Apps SandboxGroup Data Owner'
$sandboxGroupId = "/subscriptions/$subscription/resourceGroups/$resourceGroup/providers/Microsoft.App/sandboxGroups/$sandboxGroupName"
$workspaceId = "/subscriptions/$subscription/resourceGroups/$resourceGroup/providers/Microsoft.OperationalInsights/workspaces/$workspaceName"
$insightsId = "/subscriptions/$subscription/resourceGroups/$resourceGroup/providers/Microsoft.Insights/components/$applicationInsightsName"
$managedResourceIds = @($sandboxGroupId, $workspaceId, $insightsId)
$template = Join-Path $PSScriptRoot 'Sandbox.Infrastructure.bicep'
$deploymentName = 'lorawan-sandbox-infrastructure'

function Invoke-AzureCli {
    param([Parameter(Mandatory)][string[]] $Arguments)

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed (exit $LASTEXITCODE): az $($Arguments -join ' ')`n$($output -join "`n")"
    }
    return $output
}

function Invoke-AzureCliJson {
    param([Parameter(Mandatory)][string[]] $Arguments)

    $raw = Invoke-AzureCli $Arguments
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Get-VerifiedInfrastructureState {
    param([Parameter(Mandatory)][string] $PrincipalId)

    $group = Invoke-AzureCliJson -Arguments @(
        'resource', 'show', '--ids', $sandboxGroupId, '--api-version', '2026-02-01-preview',
        '--query', '{id:id,location:location,state:properties.provisioningState,properties:properties}',
        '--output', 'json'
    )
    $logWorkspace = Invoke-AzureCliJson -Arguments @(
        'resource', 'show', '--ids', $workspaceId, '--api-version', '2022-10-01',
        '--query', '{id:id,location:location,state:properties.provisioningState,retentionInDays:properties.retentionInDays,sku:properties.sku.name}',
        '--output', 'json'
    )
    $insights = Invoke-AzureCliJson -Arguments @(
        'resource', 'show', '--ids', $insightsId, '--api-version', '2020-02-02',
        '--query', '{id:id,location:location,state:properties.provisioningState,workspaceId:properties.WorkspaceResourceId}',
        '--output', 'json'
    )
    $roleAssignments = @(Invoke-AzureCliJson -Arguments @(
        'role', 'assignment', 'list',
        '--assignee', $PrincipalId,
        '--scope', $sandboxGroupId,
        '--query', "[?roleDefinitionName=='$roleName'].{role:roleDefinitionName,scope:scope,principalId:principalId}",
        '--output', 'json'
    ))
    $roleAssignment = @($roleAssignments | Where-Object {
        $_.role -eq $roleName -and
        $_.principalId -eq $PrincipalId -and
        [string]::Equals($_.scope.TrimEnd('/'), $sandboxGroupId, [StringComparison]::OrdinalIgnoreCase)
    })

    if ($group.state -ne 'Succeeded' -or $group.location -ne $location -or
        $group.properties.defaultCpu -ne '0.25' -or
        $group.properties.defaultMemory -ne '0.5Gi' -or
        $group.properties.defaultDisk -ne '20Gi' -or
        $group.properties.defaultTimeoutSeconds -ne 3600 -or
        $group.properties.maxSandboxCount -ne 1 -or
        $group.properties.enableDetailedMetrics -ne $false -or
        $logWorkspace.state -ne 'Succeeded' -or $logWorkspace.location -ne $location -or
        $logWorkspace.retentionInDays -ne 30 -or $logWorkspace.sku -ne 'PerGB2018' -or
        $insights.state -ne 'Succeeded' -or $insights.location -ne $location -or
        $insights.workspaceId -ne $workspaceId -or $roleAssignment.Count -eq 0) {
        throw 'Infrastructure verification did not match the requested resource state.'
    }

    return [pscustomobject]@{
        SandboxGroup = $group
        DataOwnerRoleAssignment = $roleAssignment
        LogAnalyticsWorkspace = $logWorkspace
        ApplicationInsights = $insights
    }
}

$account = Invoke-AzureCliJson -Arguments @(
    'account', 'show', '--subscription', $subscription, '--output', 'json'
)
if ($account.id -ne $subscription -or $account.tenantId -ne $tenant) {
    throw 'Azure CLI identity does not match the explicitly approved tenant and subscription.'
}

$caller = Invoke-AzureCliJson -Arguments @(
    'ad', 'signed-in-user', 'show', '--query', '{id:id}', '--output', 'json'
)
if (-not $caller.id) {
    throw 'Could not resolve the current signed-in user object ID.'
}

Invoke-AzureCli @('bicep', 'build', '--file', $template, '--stdout') | Out-Null

$existingResourceIds = @(Invoke-AzureCliJson -Arguments @(
    'resource', 'list', '--resource-group', $resourceGroup, '--subscription', $subscription,
    '--query', '[].id', '--output', 'json'
) | ForEach-Object { [string]$_ })
$existingManagedResourceIds = @($managedResourceIds | Where-Object {
    $_ -in $existingResourceIds
})
if ($existingManagedResourceIds.Count -eq $managedResourceIds.Count) {
    $state = Get-VerifiedInfrastructureState -PrincipalId $caller.id
    [pscustomobject]@{
        DeploymentState = 'Succeeded'
        Result = 'AlreadyProvisioned; no resources were written.'
        SandboxGroup = $state.SandboxGroup
        DataOwnerRoleAssignment = $state.DataOwnerRoleAssignment
        LogAnalyticsWorkspace = $state.LogAnalyticsWorkspace
        ApplicationInsights = $state.ApplicationInsights
    } | ConvertTo-Json -Depth 8
    return
}
if ($existingManagedResourceIds.Count -gt 0) {
    throw 'Only part of the approved sandbox infrastructure exists; refusing an automatic deployment.'
}

$common = @(
    '--name', $deploymentName,
    '--subscription', $subscription,
    '--resource-group', $resourceGroup,
    '--template-file', $template,
    '--parameters', "principalId=$($caller.id)",
    "location=$location",
    "sandboxGroupName=$sandboxGroupName",
    "workspaceName=$workspaceName",
    "applicationInsightsName=$applicationInsightsName",
    '--output', 'json'
)

$whatIfArguments = @('deployment', 'group', 'what-if') + $common + @(
    '--result-format', 'ResourceIdOnly',
    '--no-pretty-print',
    '--only-show-errors'
)
$whatIf = Invoke-AzureCliJson -Arguments $whatIfArguments
$foundryResourceIds = @(
    "/subscriptions/$subscription/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts/lorawan-factory-f1474e0a"
    "/subscriptions/$subscription/resourceGroups/$resourceGroup/providers/Microsoft.CognitiveServices/accounts/lorawan-factory-f1474e0a/projects/lorawan-software-factory"
)
$roleAssignmentPattern = [regex]::Escape("$sandboxGroupId/providers/Microsoft.Authorization/roleAssignments/") +
    '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
$seenManagedResources = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$seenRoleAssignment = $false
$changes = @($whatIf.changes | ForEach-Object {
    if ($_.resourceId -in $foundryResourceIds) {
        if ($_.changeType -ne 'Ignore') {
            throw "What-If would change the existing Foundry account or project: $($_.resourceId)"
        }
    }
    elseif ($_.resourceId -in $managedResourceIds) {
        if ($_.changeType -notin @('Create', 'Ignore')) {
            throw "What-If contains an unsupported infrastructure change ($($_.changeType)): $($_.resourceId)"
        }
        [void]$seenManagedResources.Add($_.resourceId)
    }
    elseif ($_.resourceId -match $roleAssignmentPattern) {
        if ($_.changeType -notin @('Create', 'Ignore')) {
            throw "What-If contains an unsupported role-assignment change ($($_.changeType))."
        }
        $seenRoleAssignment = $true
    }
    else {
        throw "What-If contains an out-of-scope resource: $($_.resourceId)"
    }
    [pscustomobject]@{
        ChangeType = $_.changeType
        ResourceId = $_.resourceId
    }
})
if ($whatIf.status -ne 'Succeeded' -or
    $seenManagedResources.Count -ne $managedResourceIds.Count -or -not $seenRoleAssignment) {
    throw 'What-If did not include every approved infrastructure resource and role assignment.'
}
$changes | ConvertTo-Json -Depth 4
if (-not $Deploy) {
    Write-Output 'No resources were written. Re-run with -Deploy to apply this reviewed template.'
    return
}

$deployment = Invoke-AzureCliJson -Arguments (@('deployment', 'group', 'create') + $common)
if ($deployment.properties.provisioningState -ne 'Succeeded') {
    throw "Infrastructure deployment did not succeed (state: $($deployment.properties.provisioningState))."
}

$state = Get-VerifiedInfrastructureState -PrincipalId $caller.id

[pscustomobject]@{
    DeploymentState = $deployment.properties.provisioningState
    SandboxGroup = $state.SandboxGroup
    DataOwnerRoleAssignment = $state.DataOwnerRoleAssignment
    LogAnalyticsWorkspace = $state.LogAnalyticsWorkspace
    ApplicationInsights = $state.ApplicationInsights
} | ConvertTo-Json -Depth 8
