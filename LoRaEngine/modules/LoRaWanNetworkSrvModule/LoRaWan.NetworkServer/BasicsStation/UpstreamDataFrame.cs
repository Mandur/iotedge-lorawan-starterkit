// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer.BasicsStation
{
    public class UpstreamDataFrame(MacHeader macHeader,
                             DevAddr devAddress,
                             FrameControlFlags fctrlFlags,
                             ushort counter,
                             string options,
                             FramePort? port,
                             string payload,
                             Mic mic,
                             RadioMetadata radioMetadata)
    {
        public MacHeader MacHeader { get; } = macHeader;
        public DevAddr DevAddr { get; } = devAddress;
        public FrameControlFlags FrameControlFlags { get; } = fctrlFlags;
        public ushort Counter { get; } = counter;
        public string Options { get; } = options;
        public FramePort? Port { get; } = port;
        public string Payload { get; } = payload;
        public Mic Mic { get; } = mic;
        public RadioMetadata RadioMetadata { get; } = radioMetadata;
    }
}
