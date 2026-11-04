// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace XunitRetryHelper
{
    using System;
    using System.Collections.Generic;
    using System.Threading.Tasks;
    using Xunit.Internal;
    using Xunit.Sdk;
    using Xunit.v3;

    public class RetryFactTestDiscoverer : IXunitTestCaseDiscoverer
    {
        public ValueTask<IReadOnlyCollection<IXunitTestCase>> Discover(
            ITestFrameworkDiscoveryOptions discoveryOptions,
            IXunitTestMethod testMethod,
            IFactAttribute factAttribute)
        {
            var maxRetries = Math.Max(1, (factAttribute as RetryFactAttribute)?.MaxRetries ?? Constants.DefaultMaxRetries);
            var (
                testCaseDisplayName,
                @explicit,
                skipExceptions,
                skipReason,
                skipType,
                skipUnless,
                skipWhen,
                sourceFilePath,
                sourceLineNumber,
                timeout,
                uniqueId,
                resolvedTestMethod) = TestIntrospectionHelper.GetTestCaseDetails(discoveryOptions, testMethod, factAttribute);
            var testCase = new RetryTestCase(
                maxRetries,
                resolvedTestMethod,
                testCaseDisplayName,
                uniqueId,
                @explicit,
                skipExceptions,
                skipReason,
                skipType,
                skipUnless,
                skipWhen,
                testMethod.Traits.ToReadWrite(StringComparer.OrdinalIgnoreCase),
                sourceFilePath: sourceFilePath,
                sourceLineNumber: sourceLineNumber,
                timeout: timeout);

            return new([testCase]);
        }
    }
}
