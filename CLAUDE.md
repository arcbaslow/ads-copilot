# CLAUDE.md

## Project: `ads-copilot`

**One-line:** Scheduled campaign auditor + MCP server for Google Ads and Yandex Direct that pulls data, runs rule-based checks, processes search queries with AI, and delivers actionable Telegram/Slack summaries - designed for CIS-market digital marketers managing both platforms simultaneously.

---

## Why this exists

### The daily grind nobody has automated

A typical digital marketer at a CIS bank or e-commerce company starts their morning by:

1. Opening Google Ads dashboard, scanning campaigns, checking spend vs budget
2. Opening Yandex Direct, doing the same thing in a completely different UI
3. Exporting search query reports from both platforms
4. Manually reviewing 200-500 search queries for irrelevant terms
5. Adding negative keywords one by one
6. Checking conversion data against CRM (did the leads actually convert?)
7. Writing a summary for their manager or the client

This takes 1-3 hours every day. Most of it is mechanical pattern recognition.

### What exists and what's missing

| Tool | What it does | What's missing |
|------|-------------|----------------|
| Google Ads MCP (official) | GAQL queries via Claude | Read-only. No scheduling. No summaries. No Yandex. |
| Community Google Ads MCPs (5+) | Read/write Google Ads | Still interactive-only. No autonomous runs. No search query intelligence. |
| Yandex Direct MCP | **Does not exist** | Complete gap. |
| Yandex APIs MCP (stufently) | Search, Wordstat, Webmaster, Metrika | No Yandex Direct (ads). |
| tapi-yandex-direct (Python) | Python wrapper for Yandex Direct API v5 | Raw library, no intelligence layer. |
| Optmyzr / Adalysis / Opteo | Full PPC management platforms | $200-500+/mo SaaS. No CIS market focus. No Yandex. |

**The gap:** No open-source tool that (a) covers both Google Ads and Yandex Direct, (b) runs on a schedule without human interaction, (c) uses AI for search query classification, and (d) delivers digests to Telegram - the primary communication tool in CIS markets.

---

## What it does

### Three modes of operation

#### 1. Scheduled audit (cron / Airflow)

Runs daily (or on any cron schedule). No human input required.

```
cron: 0 8 * * * (every day at 08:00)
    |
    v
[Pull] Google Ads + Yandex Direct data (last 24h, last 7d, last 30d)
    |
    v
[Check] Run rule-based audit (50+ checks)
    |
    v
[Classify] AI-process search queries (batch, Claude Haiku)
    |
    v
[Generate] Summary with action items
    |
    v
[Deliver] Telegram bot / Slack webhook / email / markdown file
```

#### 2. MCP server (interactive)

Claude Desktop / claude.ai / Claude Code integration. Ask questions about your campaigns in natural language.

```
User: "How did my Google Ads and Yandex campaigns perform yesterday?
       Any search queries I should negate?"

Claude -> [MCP tools] -> structured response with data + recommendations
```

#### 3. CLI (ad-hoc)

```bash
# Run full audit
ads-copilot audit --google --yandex --period 7d

# Search query analysis only
ads-copilot queries --google --period 30d --classify --output negatives.csv

# Campaign structure map
ads-copilot structure --google --output structure.md

# Quick spend check
ads-copilot spend --google --yandex --today
```

---

## Architecture

```
ads-copilot/
├── CLAUDE.md
├── README.md
├── LICENSE                         # MIT
├── pyproject.toml
├── config.yaml                     # Account configs, rules, thresholds
│
├── src/
│   └── ads_copilot/
│       ├── __init__.py
│       ├── cli.py                  # Click CLI
│       │
│       ├── connectors/
│       │   ├── __init__.py
│       │   ├── google_ads.py       # Google Ads API v18 via google-ads-python
│       │   ├── yandex_direct.py    # Yandex Direct API v5 via httpx (JSON)
│       │   └── base.py             # Common interface (AdPlatformConnector)
│       │
│       ├── collectors/
│       │   ├── __init__.py
│       │   ├── campaign_data.py    # Pull campaign/adgroup/ad performance
│       │   ├── search_queries.py   # Pull search term reports
│       │   ├── conversions.py      # Pull conversion data
│       │   └── structure.py        # Map campaign hierarchy
│       │
│       ├── analyzers/
│       │   ├── __init__.py
│       │   ├── spend_checker.py    # Budget pacing, overspend alerts
│       │   ├── performance.py      # CTR/CPC/CPA anomaly detection
│       │   ├── query_classifier.py # AI-powered search query classification
│       │   ├── negative_finder.py  # Rule-based + AI negative keyword discovery
│       │   ├── structure_audit.py  # Campaign structure quality checks
│       │   └── conversion_audit.py # Conversion tracking health checks
│       │
│       ├── reporters/
│       │   ├── __init__.py
│       │   ├── telegram.py         # Telegram Bot API delivery
│       │   ├── slack.py            # Slack webhook delivery
│       │   ├── markdown.py         # Local markdown report
│       │   ├── email.py            # SMTP delivery
│       │   └── formatters.py       # Cross-platform message formatting
│       │
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── query_intent.py     # Claude-powered query intent classification
│       │   ├── summarizer.py       # Report summarization
│       │   └── prompts.py          # Prompt templates
│       │
│       ├── scheduler/
│       │   ├── __init__.py
│       │   ├── cron.py             # Standalone cron scheduler (APScheduler)
│       │   └── airflow_dag.py      # Airflow DAG template
│       │
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── server.py           # MCP server (FastMCP)
│       │   └── tools.py            # MCP tool definitions
│       │
│       └── config.py               # Config loader + validation
│
├── tests/
│   ├── fixtures/                   # Sample API responses
│   ├── test_query_classifier.py
│   ├── test_spend_checker.py
│   └── test_negative_finder.py
│
├── examples/
│   ├── fintech-bank/               # Config for a typical bank account
│   ├── ecommerce/                  # Config for e-commerce
│   └── lead-gen/                   # Config for lead generation
│
├── dags/
│   └── ads_copilot_dag.py          # Ready-to-use Airflow DAG
│
└── docker/
    ├── Dockerfile
    └── docker-compose.yml          # Self-contained deployment
```

---

## Core features

### 1. Dual-platform data collection

Both connectors implement the same `AdPlatformConnector` interface:

```python
class AdPlatformConnector(Protocol):
    async def get_campaigns(self, date_from, date_to) -> list[CampaignData]: ...
    async def get_adgroups(self, campaign_ids, date_from, date_to) -> list[AdGroupData]: ...
    async def get_search_queries(self, date_from, date_to) -> list[SearchQueryData]: ...
    async def get_conversions(self, date_from, date_to) -> list[ConversionData]: ...
    async def get_campaign_structure(self) -> CampaignTree: ...
    async def add_negative_keywords(self, items: list[NegativeKeyword]) -> list[Result]: ...
```

**Google Ads connector:**
- Uses `google-ads` Python client library (v18+)
- Auth: OAuth2 refresh token or service account
- Queries via GAQL
- Reports: SEARCH_TERM_PERFORMANCE_REPORT, CAMPAIGN_PERFORMANCE_REPORT, etc.

**Yandex Direct connector:**
- Uses `httpx` with JSON API v5 (no SOAP, it's 2026)
- Auth: OAuth token
- Reports: SEARCH_QUERY_PERFORMANCE_REPORT, CAMPAIGN_PERFORMANCE_REPORT
- Handles Yandex-specific report polling (201/202 status codes, async report generation)
- Supports agency accounts (Client-Login header)

### 2. Search query intelligence (the killer feature)

This is where the tool differentiates from everything else.

**Rule-based layer (fast, free, runs first):**

```python
NEGATIVE_PATTERNS = {
    # Universal patterns
    "informational": [
        r"\b(what|how|why|when|where|who|is|are|can|does)\b",  # EN
        r"\b(что|как|почему|когда|где|кто|можно|ли)\b",        # RU
    ],
    "competitor": [],     # loaded from config per account
    "brand_mismatch": [], # loaded from config per account
    "irrelevant": [
        r"\b(free|бесплатно|скачать|download|torrent)\b",
        r"\b(отзывы|review|reddit|youtube|video|видео)\b",
        r"\b(вакансии|job|career|salary|зарплата)\b",
    ],
    "geographic_mismatch": [],  # loaded from config per account
}
```

**AI layer (runs on queries that pass rule-based filter):**

Batches remaining queries (up to 100 per API call) and sends to Claude Haiku:

```
You are a search query analyst for a {business_type} company.
The company sells: {product_description}
Target audience: {target_audience}
Active campaigns: {campaign_list_with_intent}

Classify each search query into one of these categories:
- RELEVANT: User intent matches the product/service
- NEGATIVE_EXACT: Should be added as exact match negative
- NEGATIVE_PHRASE: Should be added as phrase match negative
- REVIEW: Ambiguous, needs human review
- BRAND: Brand query (own or competitor)

For NEGATIVE queries, also provide:
- reason: why this query is irrelevant
- suggested_level: campaign | adgroup | account
- match_type: exact | phrase

Queries:
{query_list_with_metrics}

Respond in JSON only.
```

**Output: a ready-to-apply negative keyword list with justifications.**

### 3. Performance anomaly detection

Rule-based checks with configurable thresholds:

```yaml
# config.yaml -> rules section
rules:
  spend:
    daily_budget_pacing_threshold: 0.2  # alert if >20% over/under daily pace
    zero_spend_campaigns_alert: true     # alert on active campaigns with $0 spend
    
  performance:
    ctr_drop_threshold: 0.3             # alert if CTR drops >30% vs prior period
    cpc_spike_threshold: 0.5            # alert if CPC increases >50%
    cpa_spike_threshold: 0.4            # alert if CPA increases >40%
    quality_score_min: 5                # flag keywords with QS < 5 (Google only)
    
  conversions:
    zero_conversion_days: 3             # alert if campaign has 0 conversions for N days
    conversion_lag_hours: 48            # expected conversion reporting lag
    
  structure:
    max_keywords_per_adgroup: 20        # flag adgroups with too many keywords
    min_ads_per_adgroup: 2              # flag adgroups with <2 ads
    single_keyword_adgroups: "warn"     # or "ok" for SKAG structure
    
  search_queries:
    min_impressions_for_review: 5       # only review queries with 5+ impressions
    high_spend_no_conversion_threshold: 50  # flag queries spending >$50 with 0 conversions (currency from config)
```

### 4. Telegram delivery (primary channel)

CIS market standard. The bot sends structured messages with inline buttons for actions:

```
📊 Daily Ads Report | Apr 02, 2026

💰 SPEND
Google Ads: $450 / $500 budget (90%)
Yandex Direct: 45,000 RUB / 50,000 budget (90%)

📈 PERFORMANCE (vs yesterday)
Google: CTR 3.2% (+0.3%), CPC $1.20 (-5%), Conv: 12
Yandex: CTR 2.8% (-0.1%), CPC 85 RUB (+3%), Conv: 8

⚠️ ALERTS (3)
1. Campaign "Loans_Search" CPA spiked 45% ($85 -> $123)
2. "Credit Card" adgroup has 0 conversions for 3 days
3. Yandex campaign "Вклады_Поиск" overspent by 22%

🔍 SEARCH QUERIES (reviewed 342 queries)
Negatives to add: 18 (high confidence)
Needs review: 7 (ambiguous)

[View Details] [Apply Negatives] [Open Full Report]
```

The `[Apply Negatives]` button triggers the MCP tool or CLI to push negatives back to the platform via API.

### 5. Campaign structure mapping

Generates a human-readable campaign hierarchy:

```markdown
## Google Ads Account: 123-456-7890

### Campaign: Loans_Search [ENABLED] [$500/day]
  Strategy: Target CPA ($50)
  ├── AdGroup: Personal Loans [12 keywords, 3 ads]
  │   ├── KW: personal loan almaty [Exact] QS:8 CPC:$1.50
  │   ├── KW: personal loan online [Broad] QS:6 CPC:$2.10
  │   └── ...
  ├── AdGroup: Car Loans [8 keywords, 2 ads] ⚠️ only 2 ads
  └── AdGroup: Mortgage [15 keywords, 3 ads]

### Campaign: Brand [ENABLED] [$100/day]
  Strategy: Maximize Clicks
  └── AdGroup: Brand Terms [5 keywords, 4 ads]

## Yandex Direct Account: login-name

### Campaign: Кредиты_Поиск [Active] [50000 RUB/day]
  Strategy: Оптимизация конверсий
  ├── AdGroup: Потребительские кредиты [10 phrases, 2 ads]
  └── AdGroup: Автокредиты [8 phrases, 2 ads]
```

---

## Tech stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | google-ads client is Python. Yandex Direct examples are Python. Target audience knows Python. |
| Package manager | uv | Fast. Falls back to pip. |
| CLI | click | Standard. |
| HTTP | httpx | Async, modern. Used for Yandex Direct API. |
| Google Ads | google-ads (official) | Only official client supports GAQL and all v18 features. |
| Yandex Direct | httpx + custom wrapper | tapi-yandex-direct is unmaintained since 2021. Custom wrapper is cleaner. |
| AI | anthropic SDK | Claude Haiku for query classification. Optional. |
| MCP | mcp SDK (FastMCP) | Standard. |
| Scheduler | APScheduler | Lightweight, no external deps. Docker-native. |
| Airflow | DAG template | For teams already on Airflow. |
| Telegram | python-telegram-bot | Async, well-maintained. |
| Slack | httpx (webhook) | No SDK needed for webhook-only. |
| Config | PyYAML | Human-editable. |
| Data | SQLite | Local storage for historical comparisons. No external DB required. |

---

## Yandex Direct API specifics

### Why a custom wrapper instead of tapi-yandex-direct

The existing library (pavelmaksimov/tapi-yandex-direct) was last updated in 2021 and uses sync requests. Our wrapper:
- Async (httpx)
- Handles report polling natively (201/202 -> wait -> retry loop)
- Supports agency accounts (Client-Login header injection)
- Type-safe dataclasses for all responses
- Handles Yandex-specific encoding quirks (UTF-8 with BOM in TSV reports)

### Auth

```python
# Yandex Direct uses a simple OAuth token
# Get one at https://oauth.yandex.ru/authorize?response_type=token&client_id={APP_ID}
headers = {
    "Authorization": f"Bearer {token}",
    "Client-Login": client_login,  # for agency accounts
    "Accept-Language": "ru",
}
```

### Report types we use

| Report | Fields | Purpose |
|--------|--------|---------|
| SEARCH_QUERY_PERFORMANCE_REPORT | Query, CampaignId, AdGroupId, Impressions, Clicks, Cost, Conversions | Search query mining |
| CAMPAIGN_PERFORMANCE_REPORT | CampaignName, Impressions, Clicks, Cost, Conversions, AvgCpc | Daily performance |
| AD_PERFORMANCE_REPORT | AdId, AdGroupName, Impressions, Clicks, Ctr | Ad-level metrics |
| CUSTOM_REPORT | Flexible | Structure mapping |

### Report polling pattern

```python
async def fetch_report(self, body: dict) -> str:
    """Yandex reports are async. Poll until ready."""
    while True:
        resp = await self.client.post(REPORTS_URL, json=body, headers=self.headers)
        if resp.status_code == 200:
            return resp.text  # TSV content
        elif resp.status_code == 201:
            # Report created, being prepared
            retry_in = int(resp.headers.get("retryIn", 5))
            await asyncio.sleep(retry_in)
        elif resp.status_code == 202:
            # Report still preparing
            retry_in = int(resp.headers.get("retryIn", 10))
            await asyncio.sleep(retry_in)
        else:
            raise YandexDirectError(resp.status_code, resp.text)
```

---

## Google Ads API specifics

### Auth options

1. **OAuth2 refresh token** (standard for individual accounts)
2. **Service account** (for MCC/manager accounts at scale)

Both stored in `google-ads.yaml` or env vars.

### GAQL queries we run

```sql
-- Campaign performance (last 7 days)
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.bidding_strategy_type,
  campaign_budget.amount_micros,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.cost_per_conversion
FROM campaign
WHERE segments.date DURING LAST_7_DAYS
  AND campaign.status != 'REMOVED'
ORDER BY metrics.cost_micros DESC

-- Search terms with spend but no conversions
SELECT
  search_term_view.search_term,
  campaign.name,
  ad_group.name,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM search_term_view
WHERE segments.date DURING LAST_30_DAYS
  AND metrics.cost_micros > 0
  AND metrics.conversions = 0
ORDER BY metrics.cost_micros DESC
LIMIT 500
```

---

## MCP tools

```python
@mcp.tool()
async def get_performance_summary(
    platforms: list[str] = ["google", "yandex"],
    period: str = "yesterday",  # yesterday | last_7_days | last_30_days | custom
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Get combined performance summary across platforms."""

@mcp.tool()
async def get_search_queries(
    platform: str,  # google | yandex
    period: str = "last_7_days",
    min_impressions: int = 5,
    classify: bool = True,  # run AI classification
) -> dict:
    """Get search queries with optional AI classification."""

@mcp.tool()
async def get_negative_suggestions(
    platform: str,
    period: str = "last_30_days",
    min_spend: float = 10.0,
) -> dict:
    """Get AI-suggested negative keywords with justifications."""

@mcp.tool()
async def apply_negatives(
    platform: str,
    negatives: list[dict],  # [{keyword, match_type, level, campaign_id?}]
    dry_run: bool = True,
) -> dict:
    """Apply negative keywords. Dry run by default for safety."""

@mcp.tool()
async def get_campaign_structure(
    platform: str,
) -> dict:
    """Get full campaign/adgroup/keyword hierarchy."""

@mcp.tool()
async def get_alerts(
    platforms: list[str] = ["google", "yandex"],
) -> dict:
    """Run all audit checks and return alerts sorted by severity."""

@mcp.tool()
async def get_spend_pacing(
    platforms: list[str] = ["google", "yandex"],
) -> dict:
    """Current spend vs daily budget for all active campaigns."""

@mcp.tool()
async def compare_platforms(
    metric: str,  # cpc | cpa | ctr | roas | conversions
    period: str = "last_30_days",
) -> dict:
    """Compare Google vs Yandex performance on a specific metric."""
```

---

## Configuration

```yaml
# config.yaml

accounts:
  google_ads:
    - name: "Main Account"
      customer_id: "123-456-7890"
      credentials_file: "./google-ads.yaml"  # or env: GOOGLE_ADS_CREDENTIALS
      
  yandex_direct:
    - name: "Main Account"
      login: "my-yandex-login"
      token_env: "YANDEX_DIRECT_TOKEN"       # env var name
      # For agency:
      # agency_token_env: "YANDEX_AGENCY_TOKEN"
      # client_login: "client-login"

business:
  type: fintech                               # fintech | ecommerce | lead_gen | saas
  product_description: "Consumer loans and credit cards for individuals"
  target_audience: "Adults 25-55 in Kazakhstan looking for personal financing"
  currency: KZT                               # for threshold calculations
  conversion_name: "loan_application_submitted"

schedule:
  enabled: true
  cron: "0 8 * * *"                           # daily at 08:00
  timezone: "Asia/Almaty"

delivery:
  telegram:
    enabled: true
    bot_token_env: "TELEGRAM_BOT_TOKEN"
    chat_id: "-1001234567890"                  # group chat ID
  slack:
    enabled: false
    webhook_url_env: "SLACK_WEBHOOK_URL"
  markdown:
    enabled: true
    output_dir: "./reports"

ai:
  enabled: true
  model: "claude-haiku-4-5-20251001"
  api_key_env: "ANTHROPIC_API_KEY"
  max_queries_per_batch: 100
  classify_threshold_impressions: 5            # only classify queries with 5+ impressions

rules:
  # ... (see rule definitions above)

negative_keywords:
  # Account-level negatives (already applied, skip in analysis)
  existing_shared_lists:
    google: ["Main Negatives", "Brand Competitors"]
    yandex: ["Минус-слова общие"]
  # Custom irrelevant patterns for this account
  custom_patterns:
    - r"\b(хоум|каспий|халык)\b"               # competitor brands
    - r"\b(работа|вакансия)\b"                  # job seekers
```

---

## Milestones

### v0.1 - Core connectors + CLI (week 1-2)
- [ ] Google Ads connector (campaigns, adgroups, search terms)
- [ ] Yandex Direct connector (campaigns, adgroups, search terms, report polling)
- [ ] Common `AdPlatformConnector` interface
- [ ] CLI: `ads-copilot spend`, `ads-copilot structure`
- [ ] SQLite for data persistence
- [ ] Tests with fixture data

### v0.2 - Analyzers + reports (week 3-4)
- [ ] Spend pacing checker
- [ ] Performance anomaly detector
- [ ] Rule-based search query filter
- [ ] Markdown report generator
- [ ] Telegram bot delivery
- [ ] CLI: `ads-copilot audit`, `ads-copilot queries`

### v0.3 - AI search query intelligence (week 5)
- [ ] Claude Haiku integration for query classification
- [ ] Batch processing with cost control
- [ ] Negative keyword suggestion engine (rule + AI hybrid)
- [ ] Interactive review mode (CLI + Telegram inline buttons)

### v0.4 - MCP server (week 6)
- [ ] FastMCP server with 8 tools
- [ ] Claude Desktop config example
- [ ] Write operations (apply negatives) with dry_run safety

### v0.5 - Scheduling + deployment (week 7)
- [ ] APScheduler standalone mode
- [ ] Airflow DAG template
- [ ] Docker compose deployment
- [ ] Historical comparison (today vs yesterday, this week vs last)

### v1.0 - Polish (week 8)
- [ ] Slack delivery
- [ ] Email delivery (SMTP)
- [ ] Multi-account support (agency mode)
- [ ] README with full docs
- [ ] PyPI publish

---

## Competitive advantage

1. **Yandex Direct support** - no other MCP or audit tool has this. Instant differentiation for CIS market.
2. **Dual-platform comparison** - "your Google CPC is $1.20, your Yandex CPC is $0.85 on same keywords" - this insight requires both platforms in one tool.
3. **Scheduled autonomous operation** - all existing MCP servers are interactive. This runs on cron and delivers results to Telegram. No human needed for routine checks.
4. **AI search query classification in Russian** - Claude handles bilingual queries (RU/EN mixed) natively, which is the norm for CIS markets.
5. **Fintech-specific rules** - built-in understanding of loan/banking/insurance campaign structures.
6. **Open source with production-quality defaults** - ready to deploy in Docker, not just a demo.

---

## Non-goals (for now)

- Not a bid management tool (Google/Yandex smart bidding handles this)
- Not a creative generation tool (different problem space)
- Not a full ads management UI (the CLI and Telegram bot are the UI)
- Not real-time monitoring (daily/hourly cron is sufficient for most teams)
- Does not auto-apply changes without explicit confirmation (safety first)

---

## Code conventions

- Python 3.11+, type hints everywhere, strict mypy
- Async by default (all API calls are async)
- Connectors are protocol-based (duck typing via Protocol)
- All currency values stored as integers (micros for Google, kopecks for Yandex)
- Dates always in account timezone, never UTC (marketers think in local time)
- Russian and English supported in all user-facing strings
- All write operations require explicit `dry_run=False` flag
- Secrets via env vars only, never in config files
- Tests use fixtures, never live API calls
