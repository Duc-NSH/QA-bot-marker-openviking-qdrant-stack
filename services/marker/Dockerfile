FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system -e "."

EXPOSE 8001
CMD ["uvicorn", "marker_svc.main:app", "--host", "0.0.0.0", "--port", "8001"]
