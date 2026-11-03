# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $Image,
    [string] $Workspace,
    [ValidateRange(1024, 65535)]
    [int] $Port = 8088,
    [switch] $AllowUnpublishedImage,
    [switch] $EnableExecution,
    [string] $SandboxId,
    [string] $TaskId,
    [string] $RepositoryCommit,
    [string] $SandboxGroup,
    [string] $ResourceGroup = 'rg-lorawan-software-factory',
    [ValidateSet('swedencentral')]
    [string] $Region = 'swedencentral'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$subscription = 'f1474e0a-622f-410f-933e-d632635d1e03'
$tenant = 'fea4bf20-a5c7-4467-a97b-4322661134d5'
$usingSandbox = -not [string]::IsNullOrWhiteSpace($SandboxId)

if (-not $AllowUnpublishedImage -and $Image -notmatch '^[a-z0-9]+\.azurecr\.io/.+@sha256:[0-9a-f]{64}$') {
    throw 'Pass the published immutable ACR reference, or explicitly use -AllowUnpublishedImage for local development only.'
}
if ($usingSandbox) {
    if ($AllowUnpublishedImage) {
        throw 'ACA Sandbox execution requires the published immutable image digest; unpublished images are local-only.'
    }
    if ($Image -notmatch '^loracivpgdgbnkyeh4u\.azurecr\.io/lorawan/factory@sha256:[0-9a-f]{64}$') {
        throw 'ACA Sandbox execution is bound to the approved immutable lorawan/factory ACR image.'
    }
    $parsedTaskId = [Guid]::Empty
    if ([string]::IsNullOrWhiteSpace($TaskId) -or
        -not [Guid]::TryParse($TaskId, [ref]$parsedTaskId) -or
        [string]::IsNullOrWhiteSpace($RepositoryCommit) -or
        $RepositoryCommit -notmatch '^[0-9a-f]{40}$' -or
        [string]::IsNullOrWhiteSpace($SandboxGroup) -or
        $SandboxGroup -notmatch '^[A-Za-z0-9._-]{1,90}$' -or
        $SandboxId -notmatch '^[A-Za-z0-9._-]{1,90}$' -or
        $ResourceGroup -notmatch '^[A-Za-z0-9._()-]{1,90}$') {
        throw 'ACA Sandbox execution requires -SandboxGroup, -TaskId (UUID), and -RepositoryCommit (full lowercase SHA).'
    }
    if ($PSBoundParameters.ContainsKey('Workspace')) {
        throw 'ACA Sandbox execution never mounts a local workspace; omit -Workspace.'
    }
}
if (-not $usingSandbox -and ($PSBoundParameters.ContainsKey('TaskId') -or
        $PSBoundParameters.ContainsKey('RepositoryCommit') -or
        $PSBoundParameters.ContainsKey('SandboxGroup'))) {
    throw 'Sandbox task settings require -SandboxId.'
}
if (-not $usingSandbox -and -not $PSBoundParameters.ContainsKey('Workspace')) {
    $Workspace = Join-Path $PSScriptRoot '..\..'
}

if ($EnableExecution) {
    Write-Warning 'Builds execute repository code in the selected workspace. Use only a trusted disposable task; this is NOT a credential-isolation boundary.'
}
if (-not $usingSandbox) {
    $Workspace = (Resolve-Path -LiteralPath $Workspace).Path
}

$environmentNames = @(
    'FACTORY_MODEL_TOKEN', 'FACTORY_SANDBOX_TOKEN', 'FACTORY_SANDBOX_TOKEN_EXPIRES_ON',
    'AZURE_SUBSCRIPTION_ID', 'AZURE_TENANT_ID'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $accountJson = & az account show --subscription $subscription --output json
    if ($LASTEXITCODE -ne 0 -or -not $accountJson) {
        throw 'Unable to verify the approved Azure CLI account.'
    }
    $account = ($accountJson -join "`n") | ConvertFrom-Json
    if ($account.id -ne $subscription -or $account.tenantId -ne $tenant) {
        throw 'Azure CLI subscription or tenant differs from the approved target.'
    }

    $modelTokenJson = & az account get-access-token --subscription $subscription --resource https://ai.azure.com --output json
    if ($LASTEXITCODE -ne 0 -or -not $modelTokenJson) {
        throw 'Unable to obtain the approved Foundry inference token.'
    }
    $modelToken = (($modelTokenJson -join "`n") | ConvertFrom-Json).accessToken
    if (-not $modelToken) { throw 'Azure CLI returned no Foundry inference token.' }
    $env:FACTORY_MODEL_TOKEN = $modelToken

    $arguments = @(
        'run', '--rm', '--init', '--cap-drop=ALL', '--security-opt=no-new-privileges',
        '--publish', "127.0.0.1:${Port}:8088",
        '--env', 'FACTORY_MODEL_TOKEN',
        '--env', "FACTORY_ENABLE_EXECUTION=$([int]$EnableExecution.IsPresent)"
    )
    if ($usingSandbox) {
        $sandboxTokenJson = & az account get-access-token --subscription $subscription --resource https://dynamicsessions.io --output json
        if ($LASTEXITCODE -ne 0 -or -not $sandboxTokenJson) {
            throw 'Unable to obtain the ACA Sandbox data-plane token.'
        }
        $sandboxToken = ($sandboxTokenJson -join "`n") | ConvertFrom-Json
        if (-not $sandboxToken.accessToken) {
            throw 'Azure CLI returned no ACA Sandbox data-plane token.'
        }
        $expiresOn = $sandboxToken.expires_on
        if (-not $expiresOn) {
            try {
                $expiresOn = [DateTimeOffset]::Parse($sandboxToken.expiresOn).ToUnixTimeSeconds()
            }
            catch {
                throw 'Azure CLI returned no parseable ACA Sandbox token expiry.'
            }
        }
        $env:FACTORY_SANDBOX_TOKEN = $sandboxToken.accessToken
        $env:FACTORY_SANDBOX_TOKEN_EXPIRES_ON = [string]$expiresOn
        $env:AZURE_SUBSCRIPTION_ID = $subscription
        $env:AZURE_TENANT_ID = $tenant
        $arguments += @(
            '--env', 'FACTORY_SANDBOX_TOKEN',
            '--env', 'FACTORY_SANDBOX_TOKEN_EXPIRES_ON',
            '--env', 'AZURE_SUBSCRIPTION_ID',
            '--env', 'AZURE_TENANT_ID',
            '--env', 'FACTORY_EXECUTION_BACKEND=aca',
            '--env', "ACA_REGION=$Region",
            '--env', "ACA_RESOURCE_GROUP=$ResourceGroup",
            '--env', "ACA_SANDBOX_GROUP=$SandboxGroup",
            '--env', "ACA_SANDBOX_ID=$SandboxId",
            '--env', "FACTORY_TASK_ID=$TaskId",
            '--env', "FACTORY_REPOSITORY_COMMIT=$RepositoryCommit"
        )
    }
    else {
        $arguments += @(
            '--mount', "type=bind,source=${Workspace},target=/workspaces/iotedge-lorawan-starterkit"
        )
    }
    $arguments += $Image
    & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "Runtime container failed with exit code $LASTEXITCODE." }
}
finally {
    foreach ($name in $environmentNames) {
        $environmentPath = "Env:\$name"
        if ($null -eq $previousEnvironment[$name]) {
            Remove-Item -LiteralPath $environmentPath -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -LiteralPath $environmentPath -Value $previousEnvironment[$name]
        }
    }
    foreach ($name in @('accountJson', 'account', 'modelTokenJson', 'modelToken',
                        'sandboxTokenJson', 'sandboxToken', 'expiresOn')) {
        Remove-Variable $name -ErrorAction SilentlyContinue
    }
}
