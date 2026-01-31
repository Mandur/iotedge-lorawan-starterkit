// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer.BasicsStation
{
    public class JoinRequestFrame(MacHeader mHdr, JoinEui joinEui, DevEui devEui, DevNonce devNonce, Mic mic, RadioMetadata radioMetadata)
    {
        public RadioMetadata RadioMetadata { get; } = radioMetadata;
        public MacHeader MacHeader { get; } = mHdr;
        public JoinEui JoinEui { get; } = joinEui;
        public DevEui DevEui { get; } = devEui;
        public DevNonce DevNonce { get; } = devNonce;
        public Mic Mic { get; } = mic;
    }
}
