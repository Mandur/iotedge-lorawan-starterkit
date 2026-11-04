// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace XunitRetryHelper
{
    using System;
    using System.Threading;
    using System.Threading.Tasks;
    using Xunit;
    using Xunit.Sdk;
    using Xunit.v3;

    public static class RetryTestCaseRunner
    {
        public static async ValueTask<RunSummary> Run(
            int maxRetries,
            IXunitTestCase testCase,
            ExplicitOption explicitOption,
            IMessageBus messageBus,
            ExceptionAggregator aggregator,
            CancellationTokenSource cancellationTokenSource,
            object?[] constructorArguments)
        {
            var tests = await aggregator.RunAsync(testCase.CreateTests, []);
            if (aggregator.ToException() is Exception exception)
            {
                if (exception.Message.StartsWith(DynamicSkipToken.Value, StringComparison.Ordinal))
                {
                    return XunitRunnerHelper.SkipTestCases(
                        messageBus,
                        cancellationTokenSource,
                        [testCase],
                        exception.Message[DynamicSkipToken.Value.Length..],
                        sendTestCaseMessages: false);
                }

                return XunitRunnerHelper.FailTestCases(
                    messageBus,
                    cancellationTokenSource,
                    [testCase],
                    exception,
                    sendTestCaseMessages: false);
            }

            var retryCount = 0;
            maxRetries = Math.Max(1, maxRetries);

            while (true)
            {
                using var delayedMessageBus = new DelayedMessageBus(messageBus);
                var attemptAggregator = aggregator.Clone();
                var result = await XunitTestCaseRunner.Instance.Run(
                    testCase,
                    tests,
                    delayedMessageBus,
                    attemptAggregator,
                    cancellationTokenSource,
                    testCase.TestCaseDisplayName,
                    testCase.SkipReason,
                    explicitOption,
                    constructorArguments);

                if (attemptAggregator.HasExceptions
                    || result.Failed == 0
                    || retryCount >= maxRetries
                    || cancellationTokenSource.IsCancellationRequested)
                {
                    delayedMessageBus.Complete();
                    return result;
                }

                delayedMessageBus.Discard();
                retryCount++;
                TestContext.Current.SendDiagnosticMessage(
                    "Execution of '{0}' failed (retry {1}/{2}); retrying",
                    testCase.TestCaseDisplayName,
                    retryCount,
                    maxRetries);

                var delayMilliseconds = Math.Min(180_000, Math.Pow(2, retryCount) * Random.Shared.Next(5_000, 30_000));
                await Task.Delay(TimeSpan.FromMilliseconds(delayMilliseconds), cancellationTokenSource.Token);
            }
        }
    }
}
