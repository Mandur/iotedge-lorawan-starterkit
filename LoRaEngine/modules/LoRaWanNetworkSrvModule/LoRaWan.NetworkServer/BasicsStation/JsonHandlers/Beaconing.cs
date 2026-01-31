// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer.BasicsStation.JsonHandlers
{
    internal class Beaconing(uint dR, uint[] layout, uint[] freqs)
    {
        public uint DR { get; set; } = dR;
        public uint[] Layout { get; set; } = layout;
        public uint[] Freqs { get; set; } = freqs;
    }
}
