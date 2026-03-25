// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer.BasicsStation.ModuleConnection
{
    using Microsoft.Azure.Devices.Client;
    using Microsoft.Azure.Devices.Shared;
    using System;
    using System.Threading;
    using System.Threading.Tasks;

    public sealed class LoRaModuleClient(ModuleClient moduleClient) : ILoraModuleClient
    {
        public TimeSpan OperationTimeout { get; set; }


        public async ValueTask DisposeAsync()
        {
            if (moduleClient != null)
            {
                await moduleClient.CloseAsync();
                moduleClient.Dispose();
            }
        }

        public ModuleClient GetModuleClient() => moduleClient;

        public Task<Twin> GetTwinAsync(CancellationToken cancellationToken)
        {
            return moduleClient.GetTwinAsync(cancellationToken);
        }

        public async Task UpdateReportedPropertyAsync(string key, string value)
        {
            var twinCollection = new TwinCollection();
            twinCollection[key] = value;
            await moduleClient.UpdateReportedPropertiesAsync(twinCollection);
        }

        public async Task SetDesiredPropertyUpdateCallbackAsync(DesiredPropertyUpdateCallback onDesiredPropertiesUpdate, object usercontext)
        {
            await moduleClient.SetDesiredPropertyUpdateCallbackAsync(onDesiredPropertiesUpdate, usercontext);
        }

        public async Task SetMethodDefaultHandlerAsync(MethodCallback onDirectMethodCalled, object usercontext)
        {
            await moduleClient.SetMethodDefaultHandlerAsync(onDirectMethodCalled, usercontext);
        }
    }
}
