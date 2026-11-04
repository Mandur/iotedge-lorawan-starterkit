// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace XunitRetryHelper
{
    using System.Runtime.CompilerServices;
    using Xunit;
    using Xunit.v3;

    [XunitTestCaseDiscoverer(typeof(RetryFactTestDiscoverer))]
    public sealed class RetryFactAttribute(
        [CallerFilePath] string? sourceFilePath = null,
        [CallerLineNumber] int sourceLineNumber = -1)
        : FactAttribute(sourceFilePath, sourceLineNumber)
    {
        public int MaxRetries { get; set; } = Constants.DefaultMaxRetries;
    }
}
