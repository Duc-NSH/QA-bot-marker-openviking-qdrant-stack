# openviking/Dockerfile
FROM ghcr.io/volcengine/openviking:latest

# Install qdrant-client into the OV venv (OV uses httpx-based REST internally;
# our custom adapter uses the official qdrant-client SDK for cleaner API access).
RUN /app/.venv/bin/python -m ensurepip && \
    /app/.venv/bin/python -m pip install --no-cache-dir "qdrant-client>=1.12"

# Copy our custom adapter so it is importable as app.adapters.qdrant
COPY adapter/app /opt/openviking-custom/app
ENV PYTHONPATH="/opt/openviking-custom:${PYTHONPATH:-}"
