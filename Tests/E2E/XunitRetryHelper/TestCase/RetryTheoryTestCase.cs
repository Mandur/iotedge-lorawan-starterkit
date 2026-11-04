// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace XunitRetryHelper
{
    using System;
    using System.Collections.Generic;
    using System.ComponentModel;
    using System.Threading;
    using System.Threading.Tasks;
    using Xunit.Sdk;
    using Xunit.v3;

    public class RetryDelayEnumeratedTestCase : XunitDelayEnumeratedTheoryTestCase, ISelfExecutingXunitTestCase
    {
        [EditorBrowsable(EditorBrowsableState.Never)]
        [Obsolete("Called by the de-serializer; should only be called by deriving classes for de-serialization purposes")]
        public RetryDelayEnumeratedTestCase() { }

        public RetryDelayEnumeratedTestCase(
            int maxRetries,
            IXunitTestMethod testMethod,
            string testCaseDisplayName,
            string uniqueID,
            bool @explicit,
            bool skipTestWithoutData,
            Type[]? skipExceptions = null,
            string? skipReason = null,
            Type? skipType = null,
            string? skipUnless = null,
            string? skipWhen = null,
            Dictionary<string, HashSet<string>>? traits = null,
            string? sourceFilePath = null,
            int? sourceLineNumber = null,
            int? timeout = null)
            : base(testMethod, testCaseDisplayName, uniqueID, @explicit, skipTestWithoutData, skipExceptions, skipReason, skipType, skipUnless, skipWhen, traits, sourceFilePath, sourceLineNumber, timeout)
        {
            this.MaxRetries = maxRetries;
        }

        public int MaxRetries { get; private set; }

        protected override void Deserialize(IXunitSerializationInfo info)
        {
            base.Deserialize(info);
            this.MaxRetries = info.GetValue<int>(nameof(this.MaxRetries));
        }

        public ValueTask<RunSummary> Run(
            ExplicitOption explicitOption,
            IMessageBus messageBus,
            object?[] constructorArguments,
            ExceptionAggregator aggregator,
            CancellationTokenSource cancellationTokenSource) =>
            RetryTestCaseRunner.Run(
                this.MaxRetries,
                this,
                explicitOption,
                messageBus,
                aggregator.Clone(),
                cancellationTokenSource,
                constructorArguments);

        protected override void Serialize(IXunitSerializationInfo info)
        {
            base.Serialize(info);
            info.AddValue(nameof(this.MaxRetries), this.MaxRetries);
        }
    }
}
