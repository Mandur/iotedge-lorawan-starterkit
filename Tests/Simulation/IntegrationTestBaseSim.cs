// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.Tests.Simulation
{
    using LoRaWan.Tests.Common;
    using Xunit;

    public class IntegrationTestBaseSim(IntegrationTestFixtureSim testFixture) : IntegrationTestBase(testFixture), IClassFixture<IntegrationTestFixtureSim>
    {
        protected IntegrationTestFixtureSim TestFixtureSim => (IntegrationTestFixtureSim)TestFixture;
    }
}
