// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

#nullable enable

namespace LoRaWan.Tests.Common
{
    using System;
    using System.Collections.Concurrent;
    using LoRaTools;
    using Microsoft.Extensions.Logging;
    using Xunit.Abstractions;

    /// <summary>
    /// Logger class that offers integration with XUnit's <see cref="ITestOutputHelper"/>.
    /// It forwards log statements directly to <see cref="ITestOutputHelper"/> without taking into account scope information.
    /// It does not support category names or event IDs.
    /// </summary>
    public class TestOutputLogger(ITestOutputHelper testOutputHelper) : ILogger
    {
        private const LogLevel TestLogLevel = LogLevel.Debug;

        private readonly ITestOutputHelper testOutputHelper = testOutputHelper;

        public IDisposable BeginScope<TState>(TState state) => NoopDisposable.Instance;

        public bool IsEnabled(LogLevel logLevel) => logLevel >= TestLogLevel;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            ArgumentNullException.ThrowIfNull(formatter);
            if (!IsEnabled(logLevel)) return;

            var message = formatter(state, exception);

            try
            {
                this.testOutputHelper.WriteLine(message);
            }
            catch (InvalidOperationException)
            {
                // best-effort logging in case testOutputHelper has already been disposed. Fixes:
                // https://github.com/Azure/iotedge-lorawan-starterkit/issues/1554.
            }
        }
    }

    public sealed class TestOutputLogger<T>(ITestOutputHelper testOutputHelper) : TestOutputLogger(testOutputHelper), ILogger<T>
    {
    }

    public sealed class TestOutputLoggerFactory(ITestOutputHelper testOutputHelper) : ILoggerFactory
    {
        private readonly TestOutputLoggerProvider testOutputLoggerProvider = new TestOutputLoggerProvider(testOutputHelper);

        public void AddProvider(ILoggerProvider provider)
        {
            // Only (and always) supports the TestOutputLoggerProvider.
        }

        public ILogger CreateLogger(string categoryName) =>
            this.testOutputLoggerProvider.CreateLogger(categoryName);

        public void Dispose() => this.testOutputLoggerProvider.Dispose();

        private sealed class TestOutputLoggerProvider(ITestOutputHelper testOutputHelper) : ILoggerProvider
        {
            private readonly ITestOutputHelper testOutputHelper = testOutputHelper;
            private readonly ConcurrentDictionary<string, TestOutputLogger> loggers = new();

            public ILogger CreateLogger(string categoryName) =>
                this.loggers.GetOrAdd(categoryName, _ => new TestOutputLogger(this.testOutputHelper));

            public void Dispose() => this.loggers.Clear();
        }
    }
}
