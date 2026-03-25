// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer
{
    using LoRaTools.LoRaMessage;

    public class FunctionBundlerExecutionContext(string gatewayId, uint fCntUp, uint fCntDown,
                                               LoRaPayloadData loRaPayload, LoRaDevice loRaDevice,
                                               IDeduplicationStrategyFactory deduplicationFactory, LoRaRequest request)
    {
        public string GatewayId { get; } = gatewayId;

        public uint FCntUp { get; } = fCntUp;

        public uint FCntDown { get; } = fCntDown;

        public LoRaPayloadData LoRaPayload { get; } = loRaPayload;

        public LoRaDevice LoRaDevice { get; } = loRaDevice;

        public IDeduplicationStrategyFactory DeduplicationFactory { get; } = deduplicationFactory;

        public LoRaRequest Request { get; } = request;
    }
}
