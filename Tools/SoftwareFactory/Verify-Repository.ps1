# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

[CmdletBinding()]
param(
    [string] $Workspace = (Join-Path $PSScriptRoot '..' '..'),
    [string] $NuGetConfig,
    [switch] $IncludeIntegration
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Factory.Commands.psm1') -Force

$Workspace = (Resolve-Path -LiteralPath $Workspace).Path
& (Join-Path $PSScriptRoot 'Initialize-Workspace.ps1') -Workspace $Workspace -NuGetConfig $NuGetConfig

Push-Location $Workspace
try {
    # Worktree .git files can reference a host path unavailable inside the container.
    $templates = @(Get-ChildItem -LiteralPath (Join-Path $Workspace 'LoRaEngine') -Filter '*.tt' -Recurse -File)
    if ($templates.Count -eq 0) {
        throw 'No T4 templates were found; generated-code validation cannot run.'
    }
    foreach ($template in $templates) {
        $generatedFile = [System.IO.Path]::ChangeExtension($template.FullName, '.cs')
        $before = (Get-Content -LiteralPath $generatedFile -Raw).Replace("`r`n", "`n")
        Invoke-FactoryCommand dotnet @('t4', $template.FullName, '-o', $generatedFile)
        $after = (Get-Content -LiteralPath $generatedFile -Raw).Replace("`r`n", "`n")
        if ($before -cne $after) {
            throw "Generated code is stale: $generatedFile. Regenerate and review it before retrying."
        }
    }

    Invoke-FactoryCommand dotnet @('build', 'LoRaEngine.sln', '--configuration', 'Release', '--no-restore')
    Invoke-FactoryCommand dotnet @('build', 'Samples/DecoderSample', '--configuration', 'Release', '--no-restore')
    Invoke-FactoryCommand dotnet @('test', 'Tests/Unit/LoRaWan.Tests.Unit.csproj', '--configuration', 'Release', '--no-build', '--logger', 'trx', '--results-directory', 'Tests/TestResults/Unit')
    Invoke-FactoryCommand dotnet @('test', 'Tools/Cli-LoRa-Device-Provisioning/Tests/LoRaWan.Tools.CLI.Tests.Unit/LoRaWan.Tools.CLI.Tests.Unit.csproj', '--configuration', 'Release', '--no-restore', '--logger', 'trx', '--results-directory', 'Tests/TestResults/Cli.Unit')

    if ($IncludeIntegration) {
        Invoke-FactoryCommand dotnet @('test', 'Tests/Integration/LoRaWan.Tests.Integration.csproj', '--configuration', 'Release', '--no-build', '--logger', 'trx', '--results-directory', 'Tests/TestResults/Integration')
    }
    else {
        Write-Warning 'Docker/Redis integration tests were NOT run. This result is not full factory merge-readiness evidence.'
    }
}
finally {
    Pop-Location
}
