# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-04-05

### Added
- **Slack delivery** via incoming webhook with Block Kit formatting
- **Email delivery** via SMTP with HTML + plain-text multipart, markdown-to-HTML shim (no markdown dep)
- **Agency / multi-account mode** — the scheduler runs one audit per configured account and delivers a separate report for each. Account label is rendered in report titles, Telegram/Slack headers, and markdown filenames.
- GitHub Actions CI running tests + ruff on Python 3.11/3.12/3.13

### Changed
- `JobResult` now aggregates per-account results (`result.accounts[i]`) instead of flat counters
- `AuditReport` carries an optional `account_label` used in report headers

## [0.5.0] - 2026-04-05

### Added
- **APScheduler daemon** (`ads-copilot schedule`) with 5-field cron parsing and timezone support
- **Airflow DAG template** at `dags/ads_copilot_dag.py`
- **Docker deployment** — Dockerfile (python:3.12-slim, ai+telegram extras) + docker-compose with named volume for SQLite and reports
- `scheduler/job.py`: shared audit runner for cron and Airflow

## [0.4.0] - 2026-04-05

### Added
- **MCP server** (FastMCP, `ads-copilot-mcp` console script) with 8 tools:
  `get_performance_summary`, `get_search_queries`, `get_negative_suggestions`,
  `apply_negatives` (dry-run by default), `get_campaign_structure`,
  `get_alerts`, `get_spend_pacing`, `compare_platforms`
- Currency-mismatch detection on `compare_platforms`
- `ConnectorRegistry` for on-demand connector construction

## [0.3.0] - 2026-04-05

### Added
- **AI search-query classifier** (Claude Haiku) with bilingual CIS prompt
- Rule-based filter runs first; AI only classifies unflagged queries with spend + zero conversions, capped at 200/account and ranked by wasted spend to control token costs
- Graceful degradation: code-fence stripping, loose JSON extraction, unknown-category dropping
- Token usage tracking (input/output/batches/failures)
- `--classify` flag on `audit` CLI

## [0.2.0] - 2026-04-05

### Added
- **Alert model** (`Severity`: INFO/WARNING/CRITICAL) shared by analyzers
- **Rule-based negative keyword finder** — bilingual RU/EN regex patterns (informational, jobs, reviews, free/download, DIY, images), custom patterns from config, skips converted queries, ranks by wasted spend
- **Spend pacing checker** — scales with period length, escalates to CRITICAL past 2× threshold, separate zero-spend check
- **Performance anomaly detector** — period-over-period CTR/CPC/CPA deltas with volume floors to filter noise
- **SQLite snapshot store** for period-over-period comparison
- **Telegram Bot API reporter** with 4000-char message chunking
- Markdown + Telegram HTML formatters
- `audit` orchestrator wiring connectors → snapshots → analyzers → report

## [0.1.0] - 2026-04-05

### Added
- Initial release
- Cross-platform data models (`Metrics`, `CampaignData`, `SearchQueryData`, `CampaignTree`, `NegativeKeyword`) with monetary values in minor units
- `AdPlatformConnector` protocol — uniform async interface
- **Yandex Direct API v5 connector** — JSON API over httpx, report polling loop (201/202 → retryIn header), agency accounts via `Client-Login`, negative keyword mutations
- **Google Ads v18 connector** — official `google-ads` client wrapped as async, GAQL queries, structure mapping with keyword/QS/ad counts
- Click CLI: `spend`, `structure`, `queries`, `audit`
- Pydantic config loader with env-var token resolution
