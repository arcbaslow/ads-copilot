"""Prompt templates for Claude-based query classification.

We keep prompts version-controlled and bilingual-aware. CIS markets commonly
mix Russian and English in a single query (e.g. "кредит online almaty"), and
the model handles this natively — we just need to tell it so.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a senior PPC analyst reviewing search-query reports from Google Ads \
and Yandex Direct. You work for CIS-market advertisers (Kazakhstan, Russia, \
Uzbekistan, Belarus) where queries mix Russian, Kazakh, and English.

Your job: for each query, decide whether it should stay as a targeted term or \
be added as a negative keyword. Be strict about intent mismatch and wasted \
spend — high-cost queries with zero conversions are strong negative candidates.

You output ONLY valid JSON. No preamble, no commentary, no code fences."""


USER_PROMPT_TEMPLATE = """\
Business context:
- Type: {business_type}
- What they sell: {product_description}
- Target audience: {target_audience}
- Currency: {currency}
- Active campaigns (name and intent):
{campaign_list}

Classify each search query below. For each one, respond with:
- category: one of RELEVANT | NEGATIVE_EXACT | NEGATIVE_PHRASE | REVIEW | BRAND
- reason: short explanation (max 12 words, in English)
- confidence: one of HIGH | MEDIUM | LOW

Category definitions:
- RELEVANT: intent matches the product/service; keep targeting it
- NEGATIVE_EXACT: add as exact-match negative (specific wasted term)
- NEGATIVE_PHRASE: add as phrase-match negative (whole pattern is off)
- REVIEW: ambiguous, needs a human to decide
- BRAND: brand query (own brand or a competitor's)

Rules:
- A query with clicks > 0 and zero conversions AND irrelevant intent → NEGATIVE
- A query with conversions > 0 → RELEVANT (do not negate what converts)
- Informational queries (what/how/why/что/как) without buying intent → usually NEGATIVE_PHRASE
- Job-seeker, review-hunter, or free/download queries → NEGATIVE_PHRASE
- Competitor brand names (without own brand) → BRAND with reason="competitor"

Output strict JSON array in the same order as the input:
[{{"query": "<text>", "category": "...", "reason": "...", "confidence": "..."}}, ...]

Queries:
{queries_block}"""


def render_user_prompt(
    business_type: str,
    product_description: str,
    target_audience: str,
    currency: str,
    campaigns: list[tuple[str, str]],
    queries: list[tuple[str, int, int, int, float]],
) -> str:
    """Build the user prompt.

    campaigns: list of (name, intent_hint)
    queries:   list of (query, impressions, clicks, cost_minor, conversions)
    """
    if campaigns:
        campaign_lines = "\n".join(
            f"  - {name}: {intent}" for name, intent in campaigns
        )
    else:
        campaign_lines = "  (none provided)"

    query_lines = []
    for i, (q, imp, clk, cost, conv) in enumerate(queries, 1):
        query_lines.append(
            f'{i}. "{q}" — {imp} impr, {clk} clicks, '
            f"{cost / 1_000_000:.2f} spend, {conv:.1f} conv"
        )
    queries_block = "\n".join(query_lines)

    return USER_PROMPT_TEMPLATE.format(
        business_type=business_type or "not specified",
        product_description=product_description or "not specified",
        target_audience=target_audience or "not specified",
        currency=currency or "USD",
        campaign_list=campaign_lines,
        queries_block=queries_block,
    )
