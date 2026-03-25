// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaTools.IoTHubImpl
{
    using LoRaTools.Utils;
    using Microsoft.Azure.Devices.Shared;

    public class IoTHubStationTwin(Twin twinInstance) : IoTHubDeviceTwin(twinInstance), IStationTwin
    {
        public string NetworkId => base.TwinInstance.Tags.ReadRequired<string>(Constants.NetworkTagName);
    }
}
