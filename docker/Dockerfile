FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/arcbaslow/ads-copilot"
LABEL org.opencontainers.image.description="Google Ads + Yandex Direct auditor"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime deps first for layer caching
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir ".[ai,telegram]"

# Data + reports live in mounted volume
RUN mkdir -p /data/reports && chmod 755 /data

ENV ADS_COPILOT_CONFIG=/config/config.yaml \
    ADS_COPILOT_DB=/data/ads_copilot.sqlite \
    ADS_COPILOT_LOG_LEVEL=INFO

VOLUME ["/config", "/data"]

# Default to running the scheduler. Override with `docker run ... ads-copilot <cmd>`
ENTRYPOINT ["ads-copilot"]
CMD ["schedule", "--config", "/config/config.yaml", "--db", "/data/ads_copilot.sqlite"]
