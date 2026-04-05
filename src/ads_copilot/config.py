"""Config loader. Reads YAML, resolves env var references, validates with pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class GoogleAdsAccount(BaseModel):
    name: str
    customer_id: str
    credentials_file: str | None = None
    login_customer_id: str | None = None
    currency: str = "USD"


class YandexDirectAccount(BaseModel):
    name: str
    login: str
    token_env: str = "YANDEX_DIRECT_TOKEN"
    client_login: str | None = None
    sandbox: bool = False
    currency: str = "RUB"

    def resolve_token(self) -> str:
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError(
                f"env var {self.token_env} is not set for Yandex account {self.name}"
            )
        return token


class AccountsConfig(BaseModel):
    google_ads: list[GoogleAdsAccount] = Field(default_factory=list)
    yandex_direct: list[YandexDirectAccount] = Field(default_factory=list)


class BusinessConfig(BaseModel):
    type: Literal["fintech", "ecommerce", "lead_gen", "saas", "other"] = "other"
    product_description: str = ""
    target_audience: str = ""
    currency: str = "USD"
    conversion_name: str = ""


class ScheduleConfig(BaseModel):
    enabled: bool = False
    cron: str = "0 8 * * *"
    timezone: str = "UTC"


class TelegramDelivery(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id: str = ""


class SlackDelivery(BaseModel):
    enabled: bool = False
    webhook_url_env: str = "SLACK_WEBHOOK_URL"


class MarkdownDelivery(BaseModel):
    enabled: bool = True
    output_dir: str = "./reports"


class EmailDelivery(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user_env: str = "SMTP_USER"
    smtp_password_env: str = "SMTP_PASSWORD"
    from_addr: str = ""
    to: list[str] = Field(default_factory=list)


class DeliveryConfig(BaseModel):
    telegram: TelegramDelivery = Field(default_factory=TelegramDelivery)
    slack: SlackDelivery = Field(default_factory=SlackDelivery)
    markdown: MarkdownDelivery = Field(default_factory=MarkdownDelivery)
    email: EmailDelivery = Field(default_factory=EmailDelivery)


class AIConfig(BaseModel):
    enabled: bool = False
    model: str = "claude-haiku-4-5-20251001"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_queries_per_batch: int = 100
    classify_threshold_impressions: int = 5


class SpendRules(BaseModel):
    daily_budget_pacing_threshold: float = 0.2
    zero_spend_campaigns_alert: bool = True


class PerformanceRules(BaseModel):
    ctr_drop_threshold: float = 0.3
    cpc_spike_threshold: float = 0.5
    cpa_spike_threshold: float = 0.4
    quality_score_min: int = 5


class ConversionsRules(BaseModel):
    zero_conversion_days: int = 3
    conversion_lag_hours: int = 48


class StructureRules(BaseModel):
    max_keywords_per_adgroup: int = 20
    min_ads_per_adgroup: int = 2
    single_keyword_adgroups: Literal["warn", "ok"] = "warn"


class QueryRules(BaseModel):
    min_impressions_for_review: int = 5
    high_spend_no_conversion_threshold: int = 50


class Rules(BaseModel):
    spend: SpendRules = Field(default_factory=SpendRules)
    performance: PerformanceRules = Field(default_factory=PerformanceRules)
    conversions: ConversionsRules = Field(default_factory=ConversionsRules)
    structure: StructureRules = Field(default_factory=StructureRules)
    search_queries: QueryRules = Field(default_factory=QueryRules)


class NegativeKeywordsConfig(BaseModel):
    existing_shared_lists: dict[str, list[str]] = Field(default_factory=dict)
    custom_patterns: list[str] = Field(default_factory=list)


class Config(BaseModel):
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
    business: BusinessConfig = Field(default_factory=BusinessConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    rules: Rules = Field(default_factory=Rules)
    negative_keywords: NegativeKeywordsConfig = Field(
        default_factory=NegativeKeywordsConfig
    )

    @model_validator(mode="after")
    def at_least_one_account(self) -> "Config":
        if not self.accounts.google_ads and not self.accounts.yandex_direct:
            raise ValueError("config must declare at least one account")
        return self


def load_config(path: str | Path) -> Config:
    """Load and validate a config.yaml file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config.model_validate(raw)
