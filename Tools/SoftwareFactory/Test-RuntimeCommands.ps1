# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$originalDocker = Get-Item Function:docker -ErrorAction SilentlyContinue
$originalAz = Get-Item Function:az -ErrorAction SilentlyContinue
$originalToken = [Environment]::GetEnvironmentVariable('FACTORY_MODEL_TOKEN', 'Process')
$originalSandboxToken = [Environment]::GetEnvironmentVariable('FACTORY_SANDBOX_TOKEN', 'Process')
$originalSandboxExpiry = [Environment]::GetEnvironmentVariable('FACTORY_SANDBOX_TOKEN_EXPIRES_ON', 'Process')
$originalSubscription = [Environment]::GetEnvironmentVariable('AZURE_SUBSCRIPTION_ID', 'Process')
$originalTenant = [Environment]::GetEnvironmentVariable('AZURE_TENANT_ID', 'Process')
$originalExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$global:FactoryRuntimeTest = @{
    Calls = [System.Collections.Generic.List[string]]::new()
    Architecture = 'amd64'
    PullId = 'sha256:original'
    FailCommand = ''
    RuntimeToken = ''
    SandboxToken = ''
}

function global:docker {
    $command = $args -join ' '
    $global:FactoryRuntimeTest.Calls.Add("docker $command")
    $global:LASTEXITCODE = 0
    if ($command -like $global:FactoryRuntimeTest.FailCommand) {
        $global:LASTEXITCODE = 19
        return
    }
    if ($command -eq 'image inspect local:tested') {
        return (@{ Id = 'sha256:original'; Os = 'linux'; Architecture = $global:FactoryRuntimeTest.Architecture } | ConvertTo-Json)
    }
    if ($command -like 'buildx imagetools inspect *') {
        return (@{ digest = "sha256:$('a' * 64)" } | ConvertTo-Json)
    }
    if ($command -like 'image inspect *@sha256:*') {
        return $global:FactoryRuntimeTest.PullId
    }
    if ($args[0] -eq 'run') {
        $global:FactoryRuntimeTest.RuntimeToken = $env:FACTORY_MODEL_TOKEN
        $global:FactoryRuntimeTest.SandboxToken = $env:FACTORY_SANDBOX_TOKEN
    }
}

function global:az {
    $global:FactoryRuntimeTest.Calls.Add("az $($args -join ' ')")
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'account' -and $args[1] -eq 'show') {
        return (@{ id = 'f1474e0a-622f-410f-933e-d632635d1e03'; tenantId = 'fea4bf20-a5c7-4467-a97b-4322661134d5' } | ConvertTo-Json -Compress)
    }
    if ($args[0] -eq 'account' -and $args[1] -eq 'get-access-token') {
        if ($args -contains 'https://dynamicsessions.io') {
            return (@{ accessToken = 'temporary-sandbox-token'; expires_on = [DateTimeOffset]::UtcNow.AddHours(1).ToUnixTimeSeconds() } | ConvertTo-Json -Compress)
        }
        return (@{ accessToken = 'temporary-test-token' } | ConvertTo-Json -Compress)
    }
    throw 'Unexpected Azure CLI operation in runtime command test.'
}

function Assert-RuntimeFailure {
    param([scriptblock] $Action, [string] $Pattern)
    try { & $Action }
    catch {
        if ($_.Exception.Message -notlike $Pattern) { throw }
        return
    }
    throw "Expected failure matching: $Pattern"
}

try {
    $publish = Join-Path $PSScriptRoot 'Publish-Image.ps1'
    $start = Join-Path $PSScriptRoot 'Start-Runtime.ps1'
    $options = @{ RegistryServer = 'approved.azurecr.io'; Repository = 'factory/runtime'; Tag = 'test'; LocalImage = 'local:tested' }
    $pinned = & $publish @options
    if ($pinned -cne "approved.azurecr.io/factory/runtime@sha256:$('a' * 64)") {
        throw 'Publisher did not emit exactly the immutable reference.'
    }
    if (@($global:FactoryRuntimeTest.Calls | Where-Object { $_ -like '*build --*' }).Count) {
        throw 'Publisher rebuilt rather than publishing the original image.'
    }

    $global:FactoryRuntimeTest.Architecture = 'arm64'
    Assert-RuntimeFailure { & $publish @options } '*Linux amd64*'
    $global:FactoryRuntimeTest.Architecture = 'amd64'
    $global:FactoryRuntimeTest.PullId = 'sha256:different'
    Assert-RuntimeFailure { & $publish @options } '*original local image ID*'
    $global:FactoryRuntimeTest.PullId = 'sha256:original'
    $global:FactoryRuntimeTest.FailCommand = 'push *'
    $global:FactoryRuntimeTest.Calls.Clear()
    Assert-RuntimeFailure { & $publish @options } '*exit code 19*'
    if (@($global:FactoryRuntimeTest.Calls | Where-Object { $_ -like 'docker pull *' }).Count) {
        throw 'Publication continued after a failed push.'
    }
    $global:FactoryRuntimeTest.FailCommand = ''

    $global:FactoryRuntimeTest.Calls.Clear()
    Assert-RuntimeFailure { & $start -Image 'mutable:tag' } '*immutable ACR reference*'
    if ($global:FactoryRuntimeTest.Calls.Count) { throw 'Invalid image accessed Azure or Docker.' }

    $env:FACTORY_MODEL_TOKEN = 'previous-test-token'
    & $start -Image $pinned -Workspace $PSScriptRoot
    if ($env:FACTORY_MODEL_TOKEN -cne 'previous-test-token' -or
        $global:FactoryRuntimeTest.RuntimeToken -cne 'temporary-test-token') {
        throw 'Token environment forwarding/restoration failed.'
    }
    $calls = $global:FactoryRuntimeTest.Calls -join "`n"
    if ($calls -like '*temporary-test-token*' -or $calls -notlike '*127.0.0.1:8088:8088*' -or
        $calls -notlike '*FACTORY_ENABLE_EXECUTION=0*' -or
        $calls -notlike '*--subscription f1474e0a-622f-410f-933e-d632635d1e03*' -or
        $calls -notlike '*account show*') {
        throw 'Startup changed the credential, listener, execution, or subscription boundary.'
    }

    $sandboxImage = "loracivpgdgbnkyeh4u.azurecr.io/lorawan/factory@sha256:$('b' * 64)"
    $sandboxId = 'sandbox-012345'
    $taskId = '11111111-2222-4333-8444-555555555555'
    $commit = 'c' * 40
    $global:FactoryRuntimeTest.Calls.Clear()
    & $start -Image $sandboxImage -SandboxId $sandboxId -SandboxGroup 'factory-group' `
        -TaskId $taskId -RepositoryCommit $commit
    if ($global:FactoryRuntimeTest.RuntimeToken -cne 'temporary-test-token' -or
        $global:FactoryRuntimeTest.SandboxToken -cne 'temporary-sandbox-token') {
        throw 'ACA token environment forwarding failed.'
    }
    $sandboxCalls = $global:FactoryRuntimeTest.Calls -join "`n"
    if ($sandboxCalls -notlike '*FACTORY_EXECUTION_BACKEND=aca*' -or
        $sandboxCalls -notlike "*ACA_SANDBOX_ID=$sandboxId*" -or
        $sandboxCalls -notlike '*FACTORY_TASK_ID=11111111-2222-4333-8444-555555555555*' -or
        $sandboxCalls -like '*temporary-sandbox-token*' -or
        $sandboxCalls -like '*--mount*') {
        throw 'ACA startup mounted local files or changed the sandbox credential boundary.'
    }
    $changedEnvironment = @(
        if ($env:FACTORY_SANDBOX_TOKEN -cne $originalSandboxToken) { 'FACTORY_SANDBOX_TOKEN' }
        if ($env:FACTORY_SANDBOX_TOKEN_EXPIRES_ON -cne $originalSandboxExpiry) { 'FACTORY_SANDBOX_TOKEN_EXPIRES_ON' }
        if ($env:AZURE_SUBSCRIPTION_ID -cne $originalSubscription) { 'AZURE_SUBSCRIPTION_ID' }
        if ($env:AZURE_TENANT_ID -cne $originalTenant) { 'AZURE_TENANT_ID' }
    )
    if ($changedEnvironment.Count) {
        throw "ACA startup did not restore environment variable(s): $($changedEnvironment -join ', ')."
    }

    $global:FactoryRuntimeTest.FailCommand = 'run *'
    Assert-RuntimeFailure { & $start -Image $pinned -Workspace $PSScriptRoot } '*exit code 19*'
    if ($env:FACTORY_MODEL_TOKEN -cne 'previous-test-token') {
        throw 'Failed startup leaked its temporary token into the caller environment.'
    }
    Write-Host 'Runtime command checks passed (mocked Docker/Azure; no publication or cloud calls).'
}
finally {
    Remove-Item Function:docker
    Remove-Item Function:az
    if ($null -ne $originalDocker) { Set-Item Function:docker -Value $originalDocker.ScriptBlock }
    if ($null -ne $originalAz) { Set-Item Function:az -Value $originalAz.ScriptBlock }
    [Environment]::SetEnvironmentVariable('FACTORY_MODEL_TOKEN', $originalToken, 'Process')
    [Environment]::SetEnvironmentVariable('FACTORY_SANDBOX_TOKEN', $originalSandboxToken, 'Process')
    [Environment]::SetEnvironmentVariable('FACTORY_SANDBOX_TOKEN_EXPIRES_ON', $originalSandboxExpiry, 'Process')
    [Environment]::SetEnvironmentVariable('AZURE_SUBSCRIPTION_ID', $originalSubscription, 'Process')
    [Environment]::SetEnvironmentVariable('AZURE_TENANT_ID', $originalTenant, 'Process')
    Remove-Variable FactoryRuntimeTest -Scope Global
    if ($null -ne $originalExitCode) { $global:LASTEXITCODE = $originalExitCode.Value }
    else { Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue }
}
