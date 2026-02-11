# 🤖 Copilot Instructions — IoT Edge LoRaWAN Starter Kit

## 🧭 Architecture cheat sheet
- **Modules** (`LoRaEngine/modules/`):
  - `LoRaWanNetworkSrvModule` = LNS core. Entry via `BasicsStationNetworkServer.RunServerAsync` + `MessageDispatcher` → `LoRaDeviceRegistry` → `DefaultLoRaDataRequestHandler`.
  - `LoRaWan.NetworkServerDiscovery` = minimal ASP.NET Core app serving `/router-info` WebSocket; resolves LNS URIs via IoT Hub twin tags (see `TagBasedLnsDiscovery`).
  - `LoRaBasicsStationModule` = actual Basic Station container (config files + start scripts).
  - `LoraKeysManagerFacade` (Azure Function) = key mgmt, FCnt/ADR/dedup bundler, Redis-backed caches (`LoRaDeviceCacheRedisStore`, `LoRaADRRedisStore`).
- **Shared libraries**:
  - `LoRaWan/` = strongly-typed primitives (`DevAddr`, `DevEui`, `Mic`, `RxDelay`, `NetId`, `Id6`, etc.). Use them instead of raw strings/ints.
  - `LoraTools/` = protocol helpers (MAC commands, regions, IoT Hub abstractions, logging scopes) + discovery contracts (`ILnsDiscovery`).
- **Flow**: LBS → discovery (`/router-info`) → LNS WebSockets (`/router-data`) → `LnsProtocolMessageProcessor` → `MessageDispatcher` → per-device queues (`DeviceLoaderSynchronizer`, `LoRaDeviceCache`) → handler (`DefaultLoRaDataRequestHandler`) → optional FunctionBundler call via `LoRaDeviceApiService`.

## 🔧 Build & test workflows (mirror CI: `.github/workflows/ci.yaml`)
- SDK: `.NET 10` (`global.json`), C# `13.0` (see `Directory.Build.props`). Run `dotnet --info` to verify preview installed.
- Refresh T4-generated code before commit: `dotnet tool restore && git ls-files *.tt | xargs -n1 dotnet t4` (CI diff-checks this).
- Build solution: `dotnet build --configuration Release` (root `LoRaEngine.sln`).
- Unit tests: `dotnet test Tests/Unit/LoRaWan.Tests.Unit.csproj --no-build --logger trx -r Tests/TestResults/Unit`.
- Integration tests (needs Docker): `dotnet test Tests/Integration/LoRaWan.Tests.Integration.csproj --no-build ...`; spins up a Redis 6.0-alpine container on port **6001** via `RedisFixture`.
  - > Ensure Docker daemon is running; tests wait for `LoRaDevAddrCache` locks before teardown.
- CLI tests: `dotnet test Tools/Cli-LoRa-Device-Provisioning/Tests/LoRaWan.Tools.CLI.Tests.Unit/LoRaWan.Tools.CLI.Tests.Unit.csproj`.
- Containers: `CONTAINER_REGISTRY_ADDRESS=<acr>.azurecr.io docker buildx bake --set *.args.CONTAINER_REGISTRY_ADDRESS=<acr>` (see `LoRaEngine/docker-bake.hcl`, `compose.yaml`).

## 🛠️ Coding conventions & patterns
- **Headers & style**: `.editorconfig` enforces Microsoft header (IDE0073), `#nullable enable`, `using` inside namespace, prefer `var`, treat warnings as errors (`Directory.Build.props`).
- **Guards & exceptions**: prefer `ArgumentNullException.ThrowIfNull` and domain-specific `LoRaProcessingException` with `LoRaProcessingErrorCode`.
- **Logging**: use `ILogger` scopes via `ILoggerExtensions.BeginDeviceAddressScope` (see `LoraTools/ILoggerExtensions.cs`). Logging templates should stay stable; CA2254 is suggested.
- **Metrics**: use `System.Diagnostics.Metrics` (`Meter`, `Histogram`) + `MetricRegistry`; Prometheus exposed via `app.MapMetrics()` in discovery service.
- **Concurrency/caching**: hydrate devices via `LoRaDeviceRegistry` → `DeviceLoaderSynchronizer`/`JoinDeviceLoader`; never bypass `LoRaDeviceCache`. Locks use `Lock` helper and `CancellationChangeToken` for cache eviction.
- **Network/server config**: `NetworkServerConfiguration` carries `GatewayID`, `NetId`, `AllowedDevAddresses`, TLS settings. Basics Station HTTPS config in `BasicsStationNetworkServer.ConfigureHttpsSettings` expects pfx paths/passwords.
- **Discovery**: `TagBasedLnsDiscovery` reads IoT Hub twin tags (`networkId`, host address) with caching (`MemoryCache`, 6h TTL) and round-robin across candidates. For managed identity, set `HostName` config; otherwise `ConnectionStrings__IotHub`.
- **Regions**: `LoraTools/Regions/*` + `RegionManager`. Add tests under `Tests/Unit/LoRaTools/Regions*` when adding a region; ensure downstream frequency mapping is correct (`RegionCN470RP2` has good examples).
- **MAC commands**: extend `LoraTools/Mac` (`MacCommandType`, serializers) and add tests in `Tests/Unit/LoRaTools/Mac/*`. Prefer `Span`/`ByteSpanReader` utilities.
- **Function bundler**: new server-side checks should be added as `IFunctionBundlerExecutionItem` in `LoraKeysManagerFacade.FunctionBundler` and wired in `FacadeStartup`. Keep payload DTOs in sync with network server expectations.
- **IoT Hub interactions**: go through `LoRaDeviceAPIServiceBase` / `IoTHubRegistryManager` abstractions. For discovery, use `IDeviceRegistryManager` queries; avoid direct `RegistryManager` usage.
- **Tests**: xUnit + Moq. Use `TheoryDataFactory.From([...])` (see `DiscoveryServiceTests`) and shared fixtures (`MessageProcessorTestBase`, `TestLoRaDeviceFactory`, `TestMeter`). Default region defaults to `REGION` env var (falls back to EU868).

## 🗂️ Key files to skim
- `LoRaEngine/modules/LoRaWanNetworkSrvModule/LoRaWan.NetworkServer/MessageDispatcher.cs`, `LoRaDeviceRegistry.cs`, `BasicsStation/...` processors.
- `LoRaEngine/modules/LoRaWan.NetworkServerDiscovery/TagBasedLnsDiscovery.cs` + `Program.cs` (minimal API wiring).
- `LoRaEngine/LoraKeysManagerFacade/FacadeStartup.cs` and `FunctionBundler/*` for server-side logic.
- `Tests/Common/MessageProcessorTestBase.cs`, `Tests/Integration/RedisFixture.cs` for test patterns.
- `.editorconfig`, `Directory.Build.props`, `.github/workflows/ci.yaml` for tooling expectations.

## 🧪 Quick sanity checklist before PR
- `dotnet t4` yields no diffs; headers present.
- Unit + integration tests pass (Docker running); Redis container cleaned up.
- New config options surfaced in `NetworkServerConfiguration` and bound in startups (LNS and discovery). Include tests for config binding/parsing.
- Strongly typed `LoRaWan` primitives used; added metrics/log scopes wired and tested.

> Questions or gaps? Suggest edits directly to this file or ping maintainers. Let us know if any section is unclear or missing critical edge cases (e.g., multi-gateway dedup, ADR, discovery caching).
