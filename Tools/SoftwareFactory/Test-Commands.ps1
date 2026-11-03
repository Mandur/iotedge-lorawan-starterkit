# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Factory.Commands.psm1') -Force

$powerShell = (Get-Process -Id $PID).Path
Invoke-FactoryCommand $powerShell @('-NoProfile', '-Command', 'exit 0')

$rejected = $false
try {
    Invoke-FactoryCommand $powerShell @('-NoProfile', '-Command', 'exit 17')
}
catch {
    if ($_.Exception.Message -notlike 'Command failed with exit code 17:*') {
        throw
    }
    $rejected = $true
}
if (-not $rejected) {
    throw 'A failing native command was incorrectly accepted.'
}

$rejected = $false
try {
    Invoke-FactoryCommand 'software-factory-command-that-does-not-exist' @('--version')
}
catch [System.Management.Automation.CommandNotFoundException] {
    $rejected = $true
}
if (-not $rejected) {
    throw 'A missing executable was incorrectly accepted.'
}
Write-Host 'Command execution checks passed.'
