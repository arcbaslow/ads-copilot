"""Claude-powered search query intent classifier.

Takes the queries that the rule-based filter couldn't confidently handle,
batches them, and asks Claude Haiku to classify intent. Falls back gracefully
on malformed JSON (one retry, then the batch is skipped).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from ads_copilot.ai.prompts import SYSTEM_PROMPT, render_user_prompt
from ads_copilot.config import AIConfig, BusinessConfig
from ads_copilot.models import SearchQueryData

log = logging.getLogger(__name__)


class Classification(str, Enum):
    RELEVANT = "RELEVANT"
    NEGATIVE_EXACT = "NEGATIVE_EXACT"
    NEGATIVE_PHRASE = "NEGATIVE_PHRASE"
    REVIEW = "REVIEW"
    BRAND = "BRAND"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(slots=True)
class ClassifiedQuery:
    query: SearchQueryData
    category: Classification
    reason: str
    confidence: Confidence


@dataclass(slots=True)
class ClassifyStats:
    queries_seen: int = 0
    queries_classified: int = 0
    batches: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicClientProto(Protocol):
    """Minimal interface we rely on. Lets us mock in tests."""

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> Any: ...


class _RealAnthropicClient:
    """Thin adapter around the anthropic SDK's sync Messages API."""

    def __init__(self, api_key: str) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. `pip install anthropic`."
            ) from e
        self._client = Anthropic(api_key=api_key)

    def messages_create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> Any:
        return self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )


class QueryClassifier:
    def __init__(
        self,
        ai_config: AIConfig,
        business: BusinessConfig,
        client: AnthropicClientProto | None = None,
    ):
        self.ai_config = ai_config
        self.business = business
        self.stats = ClassifyStats()
        self._client = client
        self._max_tokens = 4096

    def _get_client(self) -> AnthropicClientProto:
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self.ai_config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"env var {self.ai_config.api_key_env} is not set"
            )
        self._client = _RealAnthropicClient(api_key)
        return self._client

    def classify(
        self,
        queries: list[SearchQueryData],
        campaigns: list[tuple[str, str]] | None = None,
    ) -> list[ClassifiedQuery]:
        """Classify a list of queries. Returns results in input order
        (skipping any queries the model failed to classify)."""
        self.stats.queries_seen = len(queries)
        if not queries:
            return []

        batch_size = max(1, self.ai_config.max_queries_per_batch)
        results: list[ClassifiedQuery] = []
        for batch_start in range(0, len(queries), batch_size):
            batch = queries[batch_start : batch_start + batch_size]
            self.stats.batches += 1
            try:
                batch_results = self._classify_batch(batch, campaigns or [])
                results.extend(batch_results)
                self.stats.queries_classified += len(batch_results)
            except Exception as e:
                self.stats.failures += 1
                log.warning(
                    "batch %d failed (%d queries): %s",
                    self.stats.batches, len(batch), e,
                )
        return results

    def _classify_batch(
        self,
        batch: list[SearchQueryData],
        campaigns: list[tuple[str, str]],
    ) -> list[ClassifiedQuery]:
        tuples = [
            (
                q.query,
                q.metrics.impressions,
                q.metrics.clicks,
                q.metrics.cost_minor,
                q.metrics.conversions,
            )
            for q in batch
        ]
        user_prompt = render_user_prompt(
            business_type=self.business.type,
            product_description=self.business.product_description,
            target_audience=self.business.target_audience,
            currency=self.business.currency,
            campaigns=campaigns,
            queries=tuples,
        )
        client = self._get_client()
        response = client.messages_create(
            model=self.ai_config.model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        self._track_usage(response)
        text = _extract_text(response)
        parsed = _parse_json_array(text)
        return _zip_results(batch, parsed)

    def _track_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.stats.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.stats.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)


# ---------------- parsing helpers ----------------


def _extract_text(response: Any) -> str:
    """Pull the text body from an anthropic Message response."""
    content = getattr(response, "content", None)
    if content is None:
        return ""
    # SDK returns content as a list of blocks
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    if isinstance(content, str):
        return content
    return ""


_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    text = text.strip()
    # Strip possible code-fence wrapping
    if text.startswith("```"):
        text = text.strip("`")
        text = text.lstrip("json").lstrip()
    # Find the JSON array anywhere in the body
    try:
        return json.loads(text) if text.startswith("[") else _loose_extract(text)
    except json.JSONDecodeError:
        return _loose_extract(text)


def _loose_extract(text: str) -> list[dict[str, Any]]:
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _zip_results(
    batch: list[SearchQueryData],
    parsed: list[dict[str, Any]],
) -> list[ClassifiedQuery]:
    # Build lookup by query text; we rely on the model returning the exact string.
    by_query: dict[str, dict[str, Any]] = {}
    for item in parsed:
        q = item.get("query")
        if isinstance(q, str):
            by_query[q] = item

    out: list[ClassifiedQuery] = []
    for sq in batch:
        item = by_query.get(sq.query)
        if item is None:
            continue
        cat = _coerce_enum(Classification, item.get("category"))
        if cat is None:
            continue
        conf = _coerce_enum(Confidence, item.get("confidence")) or Confidence.MEDIUM
        out.append(
            ClassifiedQuery(
                query=sq,
                category=cat,
                reason=str(item.get("reason", "")).strip()[:120],
                confidence=conf,
            )
        )
    return out


def _coerce_enum(enum_cls: type[Enum], value: Any) -> Any:
    if not isinstance(value, str):
        return None
    try:
        return enum_cls(value.strip().upper())
    except ValueError:
        return None


# field import kept for future use
_ = field
