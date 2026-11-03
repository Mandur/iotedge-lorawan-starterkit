# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

[CmdletBinding()]
param(
    [string] $Workspace = (Join-Path $PSScriptRoot '..' '..'),
    [string] $NuGetConfig
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Factory.Commands.psm1') -Force

$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
$restoreOptions = @()
if ($NuGetConfig) {
    $restoreOptions = @('--configfile', (Resolve-Path -LiteralPath $NuGetConfig).Path)
}
$configuration = Get-Content -LiteralPath (Join-Path $Workspace 'global.json') -Raw | ConvertFrom-Json
Push-Location $Workspace
try {
    $sdk = & dotnet --version
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to determine the active .NET SDK.'
    }
    if ($sdk.Trim() -ne $configuration.sdk.version) {
        throw "Expected SDK $($configuration.sdk.version), but found $sdk. Rebuild the devcontainer after updating global.json and its pinned base image."
    }

    Invoke-FactoryCommand dotnet (@('tool', 'restore') + $restoreOptions)
    Invoke-FactoryCommand dotnet (@('restore', 'LoRaEngine.sln') + $restoreOptions)
    Invoke-FactoryCommand dotnet (@('restore', 'Samples/DecoderSample') + $restoreOptions)
    Invoke-FactoryCommand dotnet (@('restore', 'Tools/Cli-LoRa-Device-Provisioning/Tests/LoRaWan.Tools.CLI.Tests.Unit/LoRaWan.Tools.CLI.Tests.Unit.csproj') + $restoreOptions)
}
finally {
    Pop-Location
}
