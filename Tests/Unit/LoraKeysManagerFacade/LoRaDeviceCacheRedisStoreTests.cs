// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.Tests.Unit.LoraKeysManagerFacade
{
    using System;
    using global::LoraKeysManagerFacade;
    using Moq;
    using StackExchange.Redis;
    using Xunit;

    public class LoRaDeviceCacheRedisStoreTests
    {
        [Theory]
        [InlineData(true)]
        [InlineData(false)]
        public void TryChangeLockTTL_UsesRelativeExpiry(bool expected)
        {
            var expiry = TimeSpan.FromMinutes(1);
            var database = new Mock<IDatabase>(MockBehavior.Strict);
            database.Setup(db => db.KeyExpire("lock", expiry, ExpireWhen.Always, CommandFlags.None)).Returns(expected);
            var cache = new LoRaDeviceCacheRedisStore(database.Object);

            Assert.Equal(expected, cache.TryChangeLockTTL("lock", expiry));

            database.Verify(db => db.KeyExpire("lock", expiry, ExpireWhen.Always, CommandFlags.None), Times.Once);
        }
    }
}
