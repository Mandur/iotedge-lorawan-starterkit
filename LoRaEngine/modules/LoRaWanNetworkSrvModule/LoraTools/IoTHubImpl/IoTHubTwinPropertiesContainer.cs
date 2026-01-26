// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaTools.IoTHubImpl
{
    using Microsoft.Azure.Devices.Shared;

    public class IoTHubTwinPropertiesContainer(Twin twin) : ITwinPropertiesContainer
    {
        public ITwinProperties Desired { get; } = new IoTHubTwinProperties(twin?.Properties?.Desired ?? new TwinCollection());

        public ITwinProperties Reported { get; } = new IoTHubTwinProperties(twin?.Properties?.Reported ?? new TwinCollection());
    }
}
