// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoraKeysManagerFacade
{
    using StackExchange.Redis;
    using System.Threading.Tasks;
    using Microsoft.Extensions.Logging;
    using LoRaTools;
    using System.Text.Json;

    public class RedisChannelPublisher(ConnectionMultiplexer redis, ILogger<RedisChannelPublisher> logger) : IChannelPublisher
    {
        private readonly ConnectionMultiplexer redis = redis;
        private readonly ILogger logger = logger;

        public async Task PublishAsync(string channel, LnsRemoteCall lnsRemoteCall)
        {
            this.logger.LogDebug("Publishing message to channel '{Channel}'.", channel);
            _ = await this.redis.GetSubscriber().PublishAsync(channel, JsonSerializer.Serialize(lnsRemoteCall));
        }
    }
}
