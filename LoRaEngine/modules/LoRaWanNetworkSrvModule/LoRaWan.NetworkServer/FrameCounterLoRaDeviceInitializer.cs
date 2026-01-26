// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer
{
    using System;

    public class FrameCounterLoRaDeviceInitializer(string gatewayID, ILoRaDeviceFrameCounterUpdateStrategyProvider frameCounterUpdateStrategyProvider) : ILoRaDeviceInitializer
    {

        public void Initialize(LoRaDevice loRaDevice)
        {
            if (loRaDevice is null) throw new ArgumentNullException(nameof(loRaDevice));

            if (loRaDevice.IsOurDevice)
            {
                var strategy = frameCounterUpdateStrategyProvider.GetStrategy(loRaDevice.GatewayID);
                if (strategy is not null and ILoRaDeviceInitializer initializer)
                {
                    initializer.Initialize(loRaDevice);
                }
            }
        }
    }
}
