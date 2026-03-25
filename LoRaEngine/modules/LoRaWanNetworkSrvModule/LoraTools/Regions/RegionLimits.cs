// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace LoRaTools.Regions
{
    using System.Collections.Generic;
    using LoRaWan;

    public class RegionLimits((Hertz Min, Hertz Max) frequencyRange, ISet<DataRate> upstreamValidDR, ISet<DataRate> downstreamValidDR,
                        DataRateIndex startUpstreamDRIndex, DataRateIndex startDownstreamDRIndex)
    {
        /// <summary>
        /// Gets or sets The maximum and minimum datarate of a given region.
        /// </summary>
        public (Hertz Min, Hertz Max) FrequencyRange { get; set; } = frequencyRange;

        private readonly ISet<DataRate> downstreamValidDR = downstreamValidDR;

        private readonly ISet<DataRate> upstreamValidDR = upstreamValidDR;

        private readonly DataRateIndex startUpstreamDRIndex = startUpstreamDRIndex;

        private readonly DataRateIndex startDownstreamDRIndex = startDownstreamDRIndex;

        public bool IsCurrentUpstreamDRIndexWithinAcceptableValue(DataRateIndex dr) => (dr >= this.startUpstreamDRIndex) && dr < this.startUpstreamDRIndex + this.upstreamValidDR.Count;

        public bool IsCurrentDownstreamDRIndexWithinAcceptableValue(DataRateIndex dr) => (dr >= this.startDownstreamDRIndex) && dr < this.startDownstreamDRIndex + this.downstreamValidDR.Count;
    }
}
