// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer
{
    using Microsoft.Extensions.Logging;

    internal class ExternalGatewayLoRaRequestQueue(LoRaDevice loRaDevice, ILogger<ExternalGatewayLoRaRequestQueue> logger) : ILoRaDeviceRequestQueue
    {
        public void Queue(LoRaRequest request)
        {
            logger.LogDebug("device is not our device, ignore message");
            request.NotifyFailed(loRaDevice, LoRaDeviceRequestFailedReason.BelongsToAnotherGateway);
        }
    }
}
