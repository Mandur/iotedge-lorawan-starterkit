// Copyright (c) Microsoft. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full license information.

namespace LoRaWan.NetworkServer.Logger
{
    using Microsoft.Extensions.Logging;

    public sealed class TcpLoggerConfiguration(LogLevel logLevel, string logToTcpAddress, int logToTcpPort, string gatewayId)
    {
        // Gets the logging level
        public LogLevel LogLevel { get; } = logLevel;

        // Gets TCP address to send log
        public string LogToTcpAddress { get; } = logToTcpAddress;

        // Gets/sets TCP port to send logs
        public int LogToTcpPort { get; } = logToTcpPort;

        /// <summary>
        /// Gets or sets the id of the gateway running the logger.
        /// </summary>
        public string GatewayId { get; } = gatewayId;
    }
}
