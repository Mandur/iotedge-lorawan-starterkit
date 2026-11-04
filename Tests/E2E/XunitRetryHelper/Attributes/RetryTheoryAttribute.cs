// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace XunitRetryHelper
{
    using System.Runtime.CompilerServices;
    using Xunit;
    using Xunit.v3;

    [XunitTestCaseDiscoverer(typeof(RetryTheoryTestDiscoverer))]
    public sealed class RetryTheoryAttribute(
        [CallerFilePath] string? sourceFilePath = null,
        [CallerLineNumber] int sourceLineNumber = -1)
        : TheoryAttribute(sourceFilePath, sourceLineNumber)
    {
        public int MaxRetries { get; set; } = Constants.DefaultMaxRetries;
    }
}
