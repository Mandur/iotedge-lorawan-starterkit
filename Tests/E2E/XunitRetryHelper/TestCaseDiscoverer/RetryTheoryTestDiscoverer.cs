// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace XunitRetryHelper
{
    using System;
    using System.Collections.Generic;
    using System.Threading.Tasks;
    using Xunit;
    using Xunit.Internal;
    using Xunit.Sdk;
    using Xunit.v3;

    public class RetryTheoryTestDiscoverer : TheoryDiscoverer
    {
        protected override ValueTask<IReadOnlyCollection<IXunitTestCase>> CreateTestCasesForDataRow(
            ITestFrameworkDiscoveryOptions discoveryOptions,
            IXunitTestMethod testMethod,
            ITheoryAttribute theoryAttribute,
            ITheoryDataRow dataRow,
            object?[] testMethodArguments)
        {
            var maxRetries = Math.Max(1, (theoryAttribute as RetryTheoryAttribute)?.MaxRetries ?? Constants.DefaultMaxRetries);
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
                resolvedTestMethod) = TestIntrospectionHelper.GetTestCaseDetailsForTheoryDataRow(
                    discoveryOptions,
                    testMethod,
                    theoryAttribute,
                    dataRow,
                    testMethodArguments);
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
                TestIntrospectionHelper.GetTraits(testMethod, dataRow),
                testMethodArguments,
                sourceFilePath: sourceFilePath,
                sourceLineNumber: sourceLineNumber,
                timeout: timeout);

            return new([testCase]);
        }

        protected override ValueTask<IReadOnlyCollection<IXunitTestCase>> CreateTestCasesForTheory(
            ITestFrameworkDiscoveryOptions discoveryOptions,
            IXunitTestMethod testMethod,
            ITheoryAttribute theoryAttribute)
        {
            var maxRetries = Math.Max(1, (theoryAttribute as RetryTheoryAttribute)?.MaxRetries ?? Constants.DefaultMaxRetries);
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
                resolvedTestMethod) = TestIntrospectionHelper.GetTestCaseDetails(discoveryOptions, testMethod, theoryAttribute);
            IXunitTestCase testCase =
                skipReason is not null && skipUnless is null && skipWhen is null
                    ? new XunitTestCase(
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
                        timeout: timeout)
                    : new RetryDelayEnumeratedTestCase(
                        maxRetries,
                        resolvedTestMethod,
                        testCaseDisplayName,
                        uniqueId,
                        @explicit,
                        theoryAttribute.SkipTestWithoutData,
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
