FROM mcr.microsoft.com/dotnet/sdk:10.0.100-noble@sha256:b84b696efd5c236918761d35975209ad15918c4216cc6f41a573ff62e962ce72

LABEL org.opencontainers.image.source="https://github.com/Mandur/iotedge-lorawan-starterkit"

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=true \
    POWERSHELL_TELEMETRY_OPTOUT=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false \
    PATH="/opt/factory-python/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/factory-python

COPY Tools/SoftwareFactory/Runtime/requirements.lock /tmp/factory-requirements.lock
RUN pip install --no-cache-dir --index-url=https://packagefeedproxy.microsoft.io/pypi/simple/ \
        --require-hashes -r /tmp/factory-requirements.lock \
    && rm /tmp/factory-requirements.lock

RUN test "$(dotnet --version)" = "10.0.100" \
    && command -v git \
    && command -v pwsh \
    && chmod 755 /usr/share/powershell/.store/powershell.linux.x64/*/powershell.linux.x64/*/tools/*/any/pwsh \
    && install -d -o app -g app -m 700 /workspaces/iotedge-lorawan-starterkit \
    && install -d -o root -g root -m 755 /home/session \
    && install -d -o app -g app -m 700 /home/session/factory-workspace /home/session/.agentserver

COPY Tools/SoftwareFactory/ /opt/lorawan-factory/

USER app
WORKDIR /workspaces/iotedge-lorawan-starterkit
EXPOSE 8088
CMD ["python", "-I", "/opt/lorawan-factory/Runtime/server.py"]
