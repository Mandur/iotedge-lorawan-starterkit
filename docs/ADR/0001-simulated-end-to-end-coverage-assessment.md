# ADR 0001: Simulated end-to-end coverage assessment

- Status: Proposed
- Date: 2026-11-04

## Context

The repository has two integration-style test projects with different purposes:
`Tests/E2E` exercises configured devices and services, including a serial-connected
Arduino where required; `Tests/Simulation` sends LoRaWAN traffic through simulated
devices and Basic Stations to configured network-server endpoints. The simulation
suite avoids radio hardware, but it is not an offline cloud substitute: its fixture
and assertions use configured IoT Hub/Event Hub and Function App services.

This assessment inventories the scenarios present in those projects and identifies
gaps that can be addressed at the simulated protocol boundary versus behaviors that
still need real hardware or cloud services.

## Existing E2E scenario inventory

| Area | Existing scenarios | Test source |
| --- | --- | --- |
| OTAA join | Successful join and reported twin update; rejected joins for wrong DevEUI, AppKey, or AppEUI; custom RX2 data rate, uplink, and rejoin | [`OTAAJoinTest.cs`](../../Tests/E2E/OTAAJoinTest.cs) |
| ABP and uplinks | Confirmed/unconfirmed traffic with ADR; MIC/key failures; duplicate DevAddr; connection timeout; custom RX1 data-rate offset | [`ABPTest.cs`](../../Tests/E2E/ABPTest.cs), [`OTAATest.cs`](../../Tests/E2E/OTAATest.cs) |
| Downlinks and device classes | C2D delivery, confirmed/unconfirmed responses, FPort 2, RX delay/window selection and custom data rate; Class C downlink | [`C2DMessageTest.cs`](../../Tests/E2E/C2DMessageTest.cs), [`ClassCTest.cs`](../../Tests/E2E/ClassCTest.cs) |
| Gateway/concentrator behavior | Multi-gateway deduplication (Drop/Mark), multi-concentrator deduplication, and single/multi-gateway message handling | [`MultiGatewayTests.cs`](../../Tests/E2E/MultiGatewayTests.cs), [`MultiConcentratorTests.cs`](../../Tests/E2E/MultiConcentratorTests.cs) |
| MAC commands and decoding | Device-initiated LinkCheck, C2D MAC commands and ADR update; HTTP- and reflection-based sensor decoding | [`MacTest.cs`](../../Tests/E2E/MacTest.cs), [`SensorDecodingTest.cs`](../../Tests/E2E/SensorDecodingTest.cs) |
| Discovery and CUPS | Discovery distribution and station/network selection, unknown-station errors; concentrator update followed by LNS connection and message exchange | [`LnsDiscoveryTests.cs`](../../Tests/E2E/LnsDiscoveryTests.cs), [`CupsTests.cs`](../../Tests/E2E/CupsTests.cs) |

These are configured-service E2E scenarios, not all strictly hardware tests. Most
device-traffic cases use the Arduino serial adapter, while discovery hosts the
discovery application in a test server but creates and queries real IoT Hub devices
and module twins. The common fixture also provisions IoT Hub devices and can collect
Event Hub telemetry (`Tests/Common/IntegrationTestFixtureBase.cs`).

## Existing simulation coverage and flow map

The simulation helpers encode device frames and exchange Basic Station WebSocket
messages with the configured LNS. Tests then check acknowledgements, network-server
logs, and/or IoT Hub message counts.

| Simulated scenario | Flow covered | Limit of current assertions |
| --- | --- | --- |
| `Single_ABP_Simulated_Device` | ABP confirmed uplink → simulated Basic Station → LNS → IoT Hub; acknowledgement | No unconfirmed-uplink case in an always-run single-device test |
| `Single_OTAA_Simulated_Device` | OTAA join → session setup → confirmed uplinks → IoT Hub; acknowledgement | Successful join only |
| `Five_Devices_Sending_Messages_At_Same_Time`, `Lots_Of_Devices_OTAA_Simulated_Load_Test`, `Connected_Factory_Load_Test_Scenario` | Concurrent ABP/OTAA traffic, multiple stations/LNS endpoints, configured load and Drop deduplication | Load assertions do not cover the full protocol/error matrix or every deduplication mode |
| `Ensures_Disconnect_Happens_For_Losing_Gateway_When_Connection_Switches` | Device traffic switches between simulated stations/LNS connections; connection-close log | Exercises a connection switch, not radio/network failure recovery |
| `Single_ABP_Simulated_Device_Sends_And_Receives_C2D` | ABP uplinks followed by a service-API C2D request | Checks the LNS direct-method log, but not the downlink received by the simulated device or its acknowledgement |
| `Multiple_ABP_and_OTAA_Simulated_Devices_Confirmed` | Mixed ABP/OTAA, confirmed/unconfirmed traffic and joins under load | Explicitly skipped; manual load test only |

Sources: [`SimulatedLoadTests.cs`](../../Tests/Simulation/SimulatedLoadTests.cs),
[`SimulatedCloudTests.cs`](../../Tests/Simulation/SimulatedCloudTests.cs), and
[`SimulationUtils.cs`](../../Tests/Simulation/SimulationUtils.cs). Simulated device
creation supports confirmed/unconfirmed data, MAC-command payloads, and joins
(`Tests/Common/SimulatedDevice.cs`), but those capabilities are not all exercised
by the always-running simulation cases.

## Prioritized gaps and recommended simulated tests

| Priority | Gap and rationale | Recommended follow-up |
| --- | --- | --- |
| P1 | **Downlink delivery is not verified by the simulator.** The current C2D test checks that the LNS logged receipt of the direct method, but does not assert that a downlink reached the simulated device. This leaves an important response path unverified despite the simulator exposing received messages. | Extend the C2D scenario to assert the device receives the expected payload and, for confirmed downlinks, returns the expected acknowledgement. Cover a Class A receive window as well as Class C; assert the selected window/data rate where applicable. |
| P1 | **Negative join and uplink protocol paths are represented only in hardware E2E tests.** Bad identities/keys and MIC validation are important server-side rejection paths that do not inherently require RF hardware. | Simulate invalid OTAA identity/key/MIC joins and assert no join accept/session or successful telemetry; add invalid uplink MIC and frame-counter/replay cases with explicit rejection and no duplicate delivery assertions. |
| P2 | **MAC-command and ADR exchanges are not covered by the simulator suite.** The E2E suite tests LinkCheck and LinkADR behavior, while simulated payload construction can include MAC commands. | Add a simulated device-initiated LinkCheck case and a C2D LinkADR request/response case; assert decoded command contents and resulting data-rate/state changes. |
| P2 | **Deduplication coverage is not a focused mode-by-mode simulation matrix.** Simulated load tests include Drop and multiple stations/LNSs, while E2E explicitly covers Drop and Mark. | Send the same frame through multiple simulated stations and assert exact forwarding/marking behavior for None, Mark, and Drop, including the resulting IoT Hub count and at most one applicable downlink. |
| P3 | **Discovery selection has a service-dependent integration test but little isolated simulation coverage.** The existing tests validate round-robin and network/station selection, but their fixture provisions real IoT Hub twins. | Add deterministic discovery tests using a fake registry/twin source for missing tags, empty candidate sets, registry errors, and cache refresh/expiry. Keep cloud-backed tests for IoT Hub tag integration. |

Priorities reflect correctness risk on common message paths first (P1), protocol
features already represented by hardware tests next (P2), and isolation and
resilience of discovery behavior (P3).

## Boundary: simulation versus external infrastructure

**Suitable for simulation:** LoRaWAN frame parsing/validation, join accept/reject
behavior, frame counters, deduplication, LNS routing and reconnection behavior,
MAC-command exchanges, and assertions over the simulated device's received messages.
These checks can run without radios when the protocol peers and dependencies are
simulated or faked.

**Still requires hardware:** RF propagation/interference, real radio timing and
receive-window behavior, concentrator firmware/driver behavior, serial transport,
and validation that a physical Basic Station applies CUPS firmware/configuration
updates successfully. A protocol simulator can check server-side scheduling and
message contents, but cannot establish that a real radio transmitted or received
them.

**Still requires cloud-backed validation:** Real IoT Hub twin provisioning/reported
properties, service API/direct-method behavior, IoT Hub routing/Event Hub delivery,
and deployed Function App decoder or bundler behavior. Local fakes can cover
application decisions and failure handling deterministically, but cannot replace
validation of those Azure service integrations. The current simulation project
itself still expects configured cloud endpoints, as shown by
`Tests/Simulation/appsettings.json` and `IntegrationTestFixtureBase`.

## Decision

Treat the simulated suite as the preferred layer for protocol and server-flow
coverage that does not depend on radio behavior. Add the P1 follow-ups first, then
expand MAC-command and deduplication cases. Retain hardware- and cloud-backed E2E
tests for the boundaries above; simulated coverage complements rather than replaces
those integration checks.
