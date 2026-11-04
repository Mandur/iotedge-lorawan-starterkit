// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace XunitRetryHelper
{
    using System;
    using System.Collections.Generic;
    using Xunit.Sdk;
    using Xunit.v3;

    public sealed class DelayedMessageBus(IMessageBus innerBus) : IMessageBus, IDisposable
    {
        private readonly IMessageBus innerBus = innerBus;
        private readonly IList<IMessageSinkMessage> delayedMessages = [];

        public bool QueueMessage(IMessageSinkMessage message)
        {
            lock (this.delayedMessages)
            {
                this.delayedMessages.Add(message);
            }

            return true;
        }

        public void Complete()
        {
            lock (this.delayedMessages)
            {
                for (var i = 0; i < this.delayedMessages.Count; i++)
                {
                    this.innerBus.QueueMessage(this.delayedMessages[i]);
                }

                this.delayedMessages.Clear();
            }
        }

        public void Discard()
        {
            lock (this.delayedMessages)
            {
                this.delayedMessages.Clear();
            }
        }

        public void Dispose() => this.Complete();
    }
}
