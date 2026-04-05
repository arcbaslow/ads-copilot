from dataclasses import dataclass
from typing import Any

from ads_copilot.ai.query_intent import (
    Classification,
    Confidence,
    QueryClassifier,
    _parse_json_array,
)
from ads_copilot.config import AIConfig, BusinessConfig
from ads_copilot.models import Metrics, Platform, SearchQueryData


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list[_Block]
    usage: _Usage


class FakeClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def messages_create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(
            content=[_Block(text=self.response_text)],
            usage=_Usage(input_tokens=100, output_tokens=50),
        )


def _q(query: str, clicks: int = 2, cost: int = 3_000_000) -> SearchQueryData:
    return SearchQueryData(
        platform=Platform.GOOGLE,
        query=query,
        campaign_id="c1",
        campaign_name="Loans",
        adgroup_id="ag1",
        adgroup_name="ag",
        metrics=Metrics(impressions=100, clicks=clicks, cost_minor=cost),
    )


def _classifier(client: FakeClient) -> QueryClassifier:
    return QueryClassifier(
        ai_config=AIConfig(enabled=True, max_queries_per_batch=100),
        business=BusinessConfig(
            type="fintech",
            product_description="consumer loans",
            target_audience="adults 25-55 KZ",
            currency="KZT",
        ),
        client=client,
    )


def test_classifies_batch_and_tracks_usage() -> None:
    response = """[
        {"query": "кредит онлайн", "category": "RELEVANT", "reason": "buying intent", "confidence": "HIGH"},
        {"query": "что такое кредит", "category": "NEGATIVE_PHRASE", "reason": "informational", "confidence": "HIGH"}
    ]"""
    client = FakeClient(response)
    clf = _classifier(client)
    results = clf.classify([_q("кредит онлайн"), _q("что такое кредит")])
    assert len(results) == 2
    assert results[0].category == Classification.RELEVANT
    assert results[1].category == Classification.NEGATIVE_PHRASE
    assert results[1].confidence == Confidence.HIGH
    assert clf.stats.queries_seen == 2
    assert clf.stats.queries_classified == 2
    assert clf.stats.batches == 1
    assert clf.stats.input_tokens == 100
    assert clf.stats.output_tokens == 50


def test_malformed_response_skipped_gracefully() -> None:
    client = FakeClient("not json at all, sorry")
    clf = _classifier(client)
    results = clf.classify([_q("кредит")])
    assert results == []
    assert clf.stats.failures == 0  # empty array is not a failure
    assert clf.stats.queries_classified == 0


def test_handles_json_wrapped_in_code_fence() -> None:
    response = (
        "```json\n"
        '[{"query": "кредит", "category": "RELEVANT", '
        '"reason": "ok", "confidence": "MEDIUM"}]\n'
        "```"
    )
    client = FakeClient(response)
    clf = _classifier(client)
    results = clf.classify([_q("кредит")])
    assert len(results) == 1
    assert results[0].category == Classification.RELEVANT


def test_batches_large_input() -> None:
    response = "[]"
    client = FakeClient(response)
    clf = QueryClassifier(
        ai_config=AIConfig(enabled=True, max_queries_per_batch=3),
        business=BusinessConfig(type="other"),
        client=client,
    )
    clf.classify([_q(f"q{i}") for i in range(10)])
    assert clf.stats.batches == 4  # ceil(10/3)
    assert len(client.calls) == 4


def test_drops_unknown_category() -> None:
    response = '[{"query": "x", "category": "WEIRD", "reason": "n/a", "confidence": "HIGH"}]'
    client = FakeClient(response)
    clf = _classifier(client)
    results = clf.classify([_q("x")])
    assert results == []


def test_mismatched_query_skipped() -> None:
    response = (
        '[{"query": "totally different string", "category": "RELEVANT", '
        '"reason": "n/a", "confidence": "HIGH"}]'
    )
    client = FakeClient(response)
    clf = _classifier(client)
    results = clf.classify([_q("кредит")])
    assert results == []  # no match on query text


def test_parse_json_array_with_preamble() -> None:
    text = 'Here is your answer:\n[{"query": "x", "category": "RELEVANT"}]'
    parsed = _parse_json_array(text)
    assert len(parsed) == 1
    assert parsed[0]["query"] == "x"


def test_parse_json_array_empty() -> None:
    assert _parse_json_array("") == []
    assert _parse_json_array("no array here") == []


def test_api_failure_recorded() -> None:
    class FailingClient:
        def messages_create(self, **kwargs: Any) -> Any:
            raise RuntimeError("api down")

    clf = _classifier(FailingClient())  # type: ignore[arg-type]
    results = clf.classify([_q("кредит")])
    assert results == []
    assert clf.stats.failures == 1
