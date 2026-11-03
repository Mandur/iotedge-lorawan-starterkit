# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for full license information.

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9]+\.azurecr\.io$')]
    [string] $RegistryServer,
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9][a-z0-9._/-]*$')]
    [string] $Repository,
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$')]
    [string] $Tag,
    [string] $LocalImage = 'lorawan-factory-dev:runtime'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'Factory.Commands.psm1') -Force

# Authentication must already be configured by the operator. Never obtain/store credentials.
$images = & docker image inspect $LocalImage | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect local image.' }
$original = @($images)[0]
if ($original.Os -ne 'linux' -or $original.Architecture -ne 'amd64') {
    throw 'Only the verified Linux amd64 image may be published.'
}
$target = "${RegistryServer}/${Repository}:${Tag}"
Invoke-FactoryCommand docker @('tag', $original.Id, $target)
Invoke-FactoryCommand docker @('push', $target)
$manifest = & docker buildx imagetools inspect $target --format '{{json .Manifest}}' | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $manifest.digest -notmatch '^sha256:[0-9a-f]{64}$') {
    throw 'Cannot resolve the published manifest digest.'
}
$pinned = "${RegistryServer}/${Repository}@$($manifest.digest)"
Invoke-FactoryCommand docker @('pull', '--platform', 'linux/amd64', $pinned)
$pulled = & docker image inspect $pinned --format '{{.Id}}'
if ($LASTEXITCODE -ne 0 -or $pulled.Trim() -ne $original.Id) {
    throw 'Published manifest does not resolve to the original local image ID.'
}
Write-Output $pinned
