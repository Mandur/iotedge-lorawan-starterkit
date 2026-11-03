# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-ExpectedFailure {
    param([scriptblock] $Action, [string] $MessagePattern)

    $rejected = $false
    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -notlike $MessagePattern) {
            throw
        }
        $rejected = $true
    }
    if (-not $rejected) {
        throw "Expected a failure matching: $MessagePattern"
    }
}

$originalDotnet = Get-Item Function:dotnet -ErrorAction SilentlyContinue
$originalExitCode = Get-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
$workspace = Join-Path ([System.IO.Path]::GetTempPath()) "lorawan-factory-$([Guid]::NewGuid().ToString('N'))"
$global:FactoryWorkspaceTest = @{
    Calls = [System.Collections.Generic.List[string]]::new()
    Sdk = '10.0.100'
    FailCommand = ''
    Drift = $false
}

function global:dotnet {
    $command = $args -join ' '
    $global:FactoryWorkspaceTest.Calls.Add($command)
    $global:LASTEXITCODE = 0
    if ($command -eq '--version') {
        return $global:FactoryWorkspaceTest.Sdk
    }
    if ($command -eq $global:FactoryWorkspaceTest.FailCommand) {
        $global:LASTEXITCODE = 19
    }
    if ($args[0] -eq 't4' -and $global:FactoryWorkspaceTest.Drift) {
        Set-Content -LiteralPath $args[3] -Value 'changed generated output'
    }
}

try {
    $templates = Join-Path $workspace 'LoRaEngine'
    New-Item -ItemType Directory -Path $templates | Out-Null
    Set-Content -LiteralPath (Join-Path $workspace 'global.json') -Value '{"sdk":{"version":"10.0.100"}}'
    Set-Content -LiteralPath (Join-Path $templates 'Example.tt') -Value '<#@ output extension=".cs" #>'
    Set-Content -LiteralPath (Join-Path $templates 'Example.cs') -Value 'original generated output'

    & (Join-Path $PSScriptRoot 'Verify-Repository.ps1') -Workspace $workspace
    $calls = $global:FactoryWorkspaceTest.Calls
    if ($calls.Count -ne 10 -or @($calls | Where-Object { $_ -like '*Tests/Integration/*' }).Count -ne 0) {
        throw 'Default verification did not run exactly the expected non-Docker lanes.'
    }
    if (@($calls | Where-Object { $_ -like 'test *--no-build*' -and $_ -notlike '*--configuration Release*' }).Count -ne 0) {
        throw 'A no-build test used a configuration other than Release.'
    }

    $calls.Clear()
    & (Join-Path $PSScriptRoot 'Verify-Repository.ps1') -Workspace $workspace -IncludeIntegration
    if ($calls.Count -ne 11 -or $calls[10] -notlike 'test Tests/Integration/*--configuration Release --no-build*') {
        throw 'Explicit integration validation was not run.'
    }

    $calls.Clear()
    $config = Join-Path $workspace 'NuGet.Config'
    Set-Content -LiteralPath $config -Value '<configuration />'
    & (Join-Path $PSScriptRoot 'Initialize-Workspace.ps1') -Workspace $workspace -NuGetConfig $config
    if ($calls.Count -ne 5 -or @($calls | Where-Object { $_ -like "*--configfile $config" }).Count -ne 4) {
        throw 'An explicit package configuration was not forwarded to every restore.'
    }

    $calls.Clear()
    Assert-ExpectedFailure {
        & (Join-Path $PSScriptRoot 'Initialize-Workspace.ps1') -Workspace $workspace -NuGetConfig (Join-Path $workspace 'missing.config')
    } '*does not exist*'
    if ($calls.Count -ne 0) {
        throw 'An invalid package configuration fell back to the default.'
    }

    $calls.Clear()
    $global:FactoryWorkspaceTest.Sdk = '10.0.403'
    Assert-ExpectedFailure {
        & (Join-Path $PSScriptRoot 'Initialize-Workspace.ps1') -Workspace $workspace
    } 'Expected SDK 10.0.100, but found*'
    if ($calls.Count -ne 1) {
        throw 'An SDK mismatch did not stop initialization before restore.'
    }

    $calls.Clear()
    $global:FactoryWorkspaceTest.Sdk = '10.0.100'
    $global:FactoryWorkspaceTest.FailCommand = 'tool restore'
    Assert-ExpectedFailure {
        & (Join-Path $PSScriptRoot 'Verify-Repository.ps1') -Workspace $workspace
    } 'Command failed with exit code 19:*'
    if ($calls.Count -ne 2) {
        throw 'A failed restore did not prevent subsequent commands.'
    }

    $calls.Clear()
    $global:FactoryWorkspaceTest.FailCommand = ''
    $global:FactoryWorkspaceTest.Drift = $true
    Assert-ExpectedFailure {
        & (Join-Path $PSScriptRoot 'Verify-Repository.ps1') -Workspace $workspace
    } 'Generated code is stale:*'
    if ($calls.Count -ne 6) {
        throw 'Generated-code drift did not prevent subsequent build/test commands.'
    }
    Write-Host 'Workspace orchestration checks passed (mocked SDK commands, not application tests).'
}
finally {
    Remove-Item Function:dotnet
    if ($null -ne $originalDotnet) {
        Set-Item Function:dotnet -Value $originalDotnet.ScriptBlock
    }
    Remove-Variable FactoryWorkspaceTest -Scope Global
    if ($null -ne $originalExitCode) {
        $global:LASTEXITCODE = $originalExitCode.Value
    }
    else {
        Remove-Variable LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $workspace) {
        Remove-Item -LiteralPath $workspace -Recurse -Force
    }
}
