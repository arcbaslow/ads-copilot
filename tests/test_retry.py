from typing import Any

import httpx
import pytest

from ads_copilot.connectors.retry import (
    RetryPolicy,
    _backoff_delay,
    _retry_after_seconds,
    retry_http,
)


def _policy(**kwargs: Any) -> RetryPolicy:
    base = {"max_attempts": 4, "base_delay": 0.01, "max_delay": 0.1, "jitter": 0}
    base.update(kwargs)
    return RetryPolicy(**base)


def _response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(status_code=status, headers=headers)


def test_backoff_delay_exponential() -> None:
    p = _policy(base_delay=1.0, max_delay=100.0, jitter=0)
    assert _backoff_delay(0, p, None) == 1.0
    assert _backoff_delay(1, p, None) == 2.0
    assert _backoff_delay(2, p, None) == 4.0
    assert _backoff_delay(3, p, None) == 8.0


def test_backoff_delay_capped() -> None:
    p = _policy(base_delay=1.0, max_delay=5.0, jitter=0)
    assert _backoff_delay(10, p, None) == 5.0  # 2**10 clamped


def test_retry_after_header_honored() -> None:
    p = _policy(base_delay=1.0, max_delay=100.0, jitter=0)
    assert _backoff_delay(0, p, retry_after=15.0) == 15.0
    # respects the cap
    assert _backoff_delay(0, p, retry_after=500.0) == 100.0


def test_retry_after_parses_seconds() -> None:
    assert _retry_after_seconds(_response(429, "30")) == 30.0
    assert _retry_after_seconds(_response(429, "not a number")) is None
    assert _retry_after_seconds(_response(429, None)) is None


async def test_retries_on_429_until_success() -> None:
    attempts = {"n": 0}

    async def send() -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _response(429, "0")
        return _response(200)

    result = await retry_http(send, policy=_policy(), description="test")
    assert result.status_code == 200
    assert attempts["n"] == 3


async def test_retries_on_5xx() -> None:
    attempts = {"n": 0}

    async def send() -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return _response(503)
        return _response(200)

    result = await retry_http(send, policy=_policy(), description="test")
    assert result.status_code == 200


async def test_does_not_retry_on_4xx() -> None:
    attempts = {"n": 0}

    async def send() -> httpx.Response:
        attempts["n"] += 1
        return _response(400)

    result = await retry_http(send, policy=_policy(), description="test")
    assert result.status_code == 400
    assert attempts["n"] == 1


async def test_exhausts_attempts_and_returns_final() -> None:
    attempts = {"n": 0}

    async def send() -> httpx.Response:
        attempts["n"] += 1
        return _response(503)

    result = await retry_http(
        send, policy=_policy(max_attempts=3), description="test",
    )
    assert result.status_code == 503
    assert attempts["n"] == 3


async def test_retries_on_transport_error() -> None:
    attempts = {"n": 0}

    async def send() -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectError("network hiccup")
        return _response(200)

    result = await retry_http(send, policy=_policy(), description="test")
    assert result.status_code == 200
    assert attempts["n"] == 2


async def test_transport_error_exhausts_and_raises() -> None:
    async def send() -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        await retry_http(
            send, policy=_policy(max_attempts=2), description="test",
        )
