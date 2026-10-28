# Device Provisioning

Main documentation is found here: <https://github.com/Azure/iotedge-lorawan-starterkit/blob/docs/main/docs/tools/device-provisioning.md>.

## IoT Edge runtime

Gateway deployments default to Azure IoT Edge **1.6.4** for both Edge Agent and Edge Hub.
Use `--azure-iot-edge-version` with `add-gateway` to override both image tags.
The deployment examples and E2E workflow use the same pinned version.

Updating these image tags does not upgrade the host's `aziot-edge` package or EFLOW VM.
Before deploying, [upgrade the device runtime](https://learn.microsoft.com/en-us/azure/iot-edge/how-to-update-iot-edge)
to a compatible 1.6 release on a supported operating system; update EFLOW through its supported update process.

IoT Edge [1.6.4](https://github.com/Azure/azure-iotedge/releases/tag/1.6.4) tightens Docker restrictions
when `allow_elevated_docker_permissions = false` in the host's `config.toml`:
required host bind sources must be listed in the top-level `allowed_bind_sources` setting,
and privileged Docker properties are removed. The LoRa Basics Station module requires privileged
hardware access, so gateways running it must permit elevated Docker permissions.

## Build release artifacts

To build release artifacts use the PowerShell script provided (BuildForRelease.ps1).
It creats a self-container package of the cli for different platforms (Windows, Linux and MacOS).
