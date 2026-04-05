# Docker deployment

Self-contained deployment for the scheduled audit daemon.

## Quick start

```bash
# 1. Copy your config into ./docker/config/
mkdir -p docker/config
cp config.example.yaml docker/config/config.yaml
# edit docker/config/config.yaml — enable schedule, telegram, etc.
# If you use Google Ads, put google-ads.yaml next to config.yaml and
# set credentials_file: /config/google-ads.yaml in config.yaml

# 2. Create .env with your tokens
cat > docker/.env <<EOF
YANDEX_DIRECT_TOKEN=y0_xxx
ANTHROPIC_API_KEY=sk-ant-xxx
TELEGRAM_BOT_TOKEN=xxx
EOF

# 3. Build and run
cd docker
docker compose up -d --build

# 4. Check logs
docker compose logs -f ads-copilot
```

## One-off commands

```bash
# Run an audit right now (without waiting for cron)
docker compose run --rm ads-copilot audit --config /config/config.yaml

# Pull campaign structure
docker compose run --rm ads-copilot structure --config /config/config.yaml

# Dump search queries to CSV
docker compose run --rm ads-copilot queries --config /config/config.yaml -o /data/queries.csv
```

## Persistent state

- `/config` — mount with your `config.yaml` and Google Ads credentials (read-only)
- `/data` — SQLite snapshot DB and markdown reports (named volume by default)
