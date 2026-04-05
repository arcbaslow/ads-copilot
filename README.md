# ads-copilot

Scheduled campaign auditor + MCP server for **Google Ads** and **Yandex Direct**.

Pulls performance data, runs rule-based checks, classifies search queries with AI, and delivers actionable digests to Telegram/Slack. Built for CIS-market digital marketers managing both platforms at once.

> **Status:** v0.1 (alpha). Core connectors and CLI. Not production-ready yet.

## Why

Existing MCP servers and PPC tools are either Google-only, interactive-only, or $200+/month SaaS. `ads-copilot` fills the gap:

- **Dual-platform** — one tool for Google Ads *and* Yandex Direct
- **Autonomous** — runs on cron, posts to Telegram. No human needed for daily checks.
- **AI search-query intelligence** — Claude Haiku classifies search terms (bilingual RU/EN) into relevant / negative / review buckets
- **Open source** — MIT, self-hosted, Docker-native

## Three modes

| Mode | Use | Command |
|---|---|---|
| Scheduled | Daily digest to Telegram/Slack | cron / Airflow DAG |
| MCP server | Ask Claude about your campaigns | Claude Desktop config |
| CLI | Ad-hoc audit | `ads-copilot audit --google --yandex` |

## Quick start

```bash
# Install
pip install ads-copilot

# Configure
cp config.example.yaml config.yaml
# edit config.yaml — add account IDs and set env vars for tokens

# Environment
export GOOGLE_ADS_CREDENTIALS=./google-ads.yaml
export YANDEX_DIRECT_TOKEN=y0_xxx
export ANTHROPIC_API_KEY=sk-ant-xxx   # optional, for AI classification

# Run
ads-copilot spend --google --yandex --today
ads-copilot structure --google
ads-copilot audit --period 7d
```

## CLI

```bash
ads-copilot spend        # current spend vs budget
ads-copilot audit        # run all checks, return alerts
ads-copilot queries      # pull search terms, optionally classify with AI
ads-copilot structure    # dump campaign/adgroup hierarchy
```

## MCP server

Add to Claude Desktop config:

```json
{
  "mcpServers": {
    "ads-copilot": {
      "command": "ads-copilot-mcp",
      "env": {
        "GOOGLE_ADS_CREDENTIALS": "/path/to/google-ads.yaml",
        "YANDEX_DIRECT_TOKEN": "y0_xxx"
      }
    }
  }
}
```

Then ask: *"How did my Google Ads and Yandex campaigns perform yesterday? Any search queries I should negate?"*

## Configuration

See [`config.example.yaml`](config.example.yaml) for the full reference. Minimal:

```yaml
accounts:
  google_ads:
    - name: "Main"
      customer_id: "123-456-7890"
      credentials_file: "./google-ads.yaml"
  yandex_direct:
    - name: "Main"
      login: "my-yandex-login"
      token_env: "YANDEX_DIRECT_TOKEN"

business:
  type: fintech
  currency: KZT
  conversion_name: "loan_submitted"

delivery:
  telegram:
    enabled: true
    bot_token_env: "TELEGRAM_BOT_TOKEN"
    chat_id: "-1001234567890"
```

## Roadmap

- [x] v0.1 — Core connectors (Google Ads + Yandex Direct), CLI skeleton, data models
- [x] v0.2 — Analyzers (spend pacing, anomaly detection, rule-based query filter), SQLite snapshots, Telegram delivery
- [ ] v0.3 — AI search-query classification (Claude Haiku)
- [ ] v0.4 — MCP server (FastMCP, 8 tools)
- [ ] v0.5 — APScheduler + Airflow DAG + Docker compose
- [ ] v1.0 — Slack/email delivery, multi-account agency mode, PyPI publish

## License

MIT
