// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace LoRaWan.NetworkServer
{
    using System.Linq;
    using System.Threading;
    using System.Threading.Tasks;
    using Microsoft.Extensions.Hosting;

    internal class CloudControlHost(ILnsRemoteCallListener lnsRemoteCallListener,
                                     ILnsRemoteCallHandler lnsRemoteCallHandler,
                                     NetworkServerConfiguration networkServerConfiguration) : IHostedService
    {
        private readonly string[] subscriptionChannels = new string[] { networkServerConfiguration.GatewayID, Constants.CloudToDeviceClearCache };

        public Task StartAsync(CancellationToken cancellationToken) =>
            Task.WhenAll(subscriptionChannels.Select(c => lnsRemoteCallListener.SubscribeAsync(c,
                                                                                                         remoteCall => lnsRemoteCallHandler.ExecuteAsync(remoteCall, cancellationToken),
                                                                                                         cancellationToken)));

        public Task StopAsync(CancellationToken cancellationToken) =>
            Task.WhenAll(subscriptionChannels.Select(c => lnsRemoteCallListener.UnsubscribeAsync(c, cancellationToken)));
    }
}
