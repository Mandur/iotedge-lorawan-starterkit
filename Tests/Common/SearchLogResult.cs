// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.Tests.Common
{
    using System.Collections.Generic;

    public class SearchLogResult(bool found, HashSet<SearchLogEvent> logs, string foundElement = null)
    {
        // Indicates if the message was found
        public bool Found { get; } = found;

        // Returns the contents of the log (to diagnose problems)
        public IReadOnlyCollection<SearchLogEvent> Logs { get; } = logs;

        public SearchLogEvent MatchedEvent { get; set; }

        public string FoundLogResult { get; set; } = foundElement;
    }
}
