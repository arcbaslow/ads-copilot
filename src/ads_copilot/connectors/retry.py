"""Shared retry helper for transient API errors.

Retries on:
- 429 Too Many Requests (respects Retry-After header if present)
- 5xx server errors
- Network-level failures (httpx.TransportError subclasses)

Does NOT retry on:
- 4xx client errors other than 429 (request is wrong, retrying won't help)
- Payload parsing errors (already succeeded at the transport level)
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.25  # 25% random jitter on each backoff


def _backoff_delay(attempt: int, policy: RetryPolicy, retry_after: float | None) -> float:
    """Return seconds to wait before the next attempt. Zero-indexed attempt."""
    if retry_after is not None:
        return min(max(retry_after, 0.0), policy.max_delay)
    exp = policy.base_delay * (2 ** attempt)
    capped = min(exp, policy.max_delay)
    if policy.jitter > 0:
        jitter = capped * policy.jitter * random.random()
        return capped + jitter
    return capped


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After header (seconds only — we ignore HTTP-date form)."""
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


async def retry_http(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy | None = None,
    description: str = "HTTP call",
) -> httpx.Response:
    """Call `send` with retries on transient failures. Returns the final response
    (successful or last attempt). Raises on non-retryable errors or after exhausting
    max_attempts."""
    policy = policy or RetryPolicy()
    last_exc: Exception | None = None

    for attempt in range(policy.max_attempts):
        try:
            response = await send()
        except httpx.TransportError as e:
            last_exc = e
            if attempt + 1 >= policy.max_attempts:
                raise
            delay = _backoff_delay(attempt, policy, None)
            log.warning(
                "%s: transport error (%s), retrying in %.1fs (%d/%d)",
                description, e, delay, attempt + 2, policy.max_attempts,
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code not in RETRYABLE_STATUS:
            return response

        if attempt + 1 >= policy.max_attempts:
            return response  # let caller handle terminal failure

        delay = _backoff_delay(attempt, policy, _retry_after_seconds(response))
        log.warning(
            "%s: HTTP %d, retrying in %.1fs (%d/%d)",
            description, response.status_code, delay,
            attempt + 2, policy.max_attempts,
        )
        await asyncio.sleep(delay)

    # unreachable in normal flow; included for type checker
    if last_exc:
        raise last_exc
    raise RuntimeError("retry loop exited without response")
