"""FastMCP server: thin wrapper that registers core tools with the MCP runtime.

Run via the `ads-copilot-mcp` console script. Requires `ads-copilot[mcp]`
(i.e. the `mcp` extra). Tool implementations live in `core.py` so tests can
exercise them without the mcp SDK.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ads_copilot.config import load_config
from ads_copilot.mcp import core
from ads_copilot.mcp.registry import ConnectorRegistry

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"


def build_server() -> Any:
    """Build a FastMCP instance with all 8 tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise RuntimeError(
            "mcp SDK not installed. `pip install 'ads-copilot[mcp]'`."
        ) from e

    config_path = os.environ.get("ADS_COPILOT_CONFIG", DEFAULT_CONFIG_PATH)
    cfg = load_config(config_path)
    registry = ConnectorRegistry(cfg)

    mcp = FastMCP("ads-copilot")

    @mcp.tool()
    async def get_performance_summary(
        platforms: list[str] | None = None,
        period: str = "yesterday",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Combined performance summary across Google Ads and Yandex Direct."""
        return await core.get_performance_summary(
            registry, platforms=platforms, period=period,
            date_from=date_from, date_to=date_to,
        )

    @mcp.tool()
    async def get_search_queries(
        platform: str,
        period: str = "last_7_days",
        min_impressions: int = 5,
        classify: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Search queries for a platform, optionally classified by rule-based filter."""
        return await core.get_search_queries(
            registry, cfg, platform=platform, period=period,
            min_impressions=min_impressions, classify=classify, limit=limit,
        )

    @mcp.tool()
    async def get_negative_suggestions(
        platform: str,
        period: str = "last_30_days",
        min_spend: float = 10.0,
    ) -> dict[str, Any]:
        """Ranked negative keyword suggestions with reasons."""
        return await core.get_negative_suggestions(
            registry, cfg, platform=platform, period=period, min_spend=min_spend,
        )

    @mcp.tool()
    async def apply_negatives(
        platform: str,
        negatives: list[dict[str, Any]],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Apply negative keywords. Dry-run by default — set dry_run=false to push."""
        return await core.apply_negatives(
            registry, platform=platform, negatives=negatives, dry_run=dry_run,
        )

    @mcp.tool()
    async def get_campaign_structure(platform: str) -> dict[str, Any]:
        """Full campaign/adgroup hierarchy for a platform."""
        return await core.get_campaign_structure(registry, platform=platform)

    @mcp.tool()
    async def get_alerts(
        platforms: list[str] | None = None,
        period: str = "last_7_days",
    ) -> dict[str, Any]:
        """Run spend + performance checks and return alerts sorted by severity."""
        db = os.environ.get("ADS_COPILOT_DB", "./ads_copilot.sqlite")
        return await core.get_alerts(
            registry, cfg, platforms=platforms, period=period, snapshot_db=db,
        )

    @mcp.tool()
    async def get_spend_pacing(
        platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        """Today's spend vs daily budget for active campaigns."""
        return await core.get_spend_pacing(registry, platforms=platforms)

    @mcp.tool()
    async def compare_platforms(
        metric: str = "cpc",
        period: str = "last_30_days",
    ) -> dict[str, Any]:
        """Compare Google vs Yandex on a metric (cpc|cpa|ctr|roas|conversions|cost)."""
        return await core.compare_platforms(registry, metric=metric, period=period)

    return mcp


def main() -> None:
    """Entry point for the `ads-copilot-mcp` console script."""
    logging.basicConfig(
        level=os.environ.get("ADS_COPILOT_LOG_LEVEL", "WARNING"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
