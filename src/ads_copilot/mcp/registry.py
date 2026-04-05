"""Connector registry: builds platform connectors from config on demand.

Connectors are reused within a single tool call, then closed together via
`close_all`. The server (or a test harness) owns a single registry instance
and hands it to each tool.
"""

from __future__ import annotations

from ads_copilot.config import Config
from ads_copilot.connectors.base import AdPlatformConnector
from ads_copilot.models import Platform


class ConnectorRegistry:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: dict[Platform, AdPlatformConnector] = {}

    def get(self, platform: Platform) -> AdPlatformConnector:
        if platform in self._cache:
            return self._cache[platform]
        self._cache[platform] = self._build(platform)
        return self._cache[platform]

    def available(self) -> list[Platform]:
        out: list[Platform] = []
        if self.cfg.accounts.google_ads:
            out.append(Platform.GOOGLE)
        if self.cfg.accounts.yandex_direct:
            out.append(Platform.YANDEX)
        return out

    def _build(self, platform: Platform) -> AdPlatformConnector:
        if platform == Platform.GOOGLE:
            from ads_copilot.connectors.google_ads import (
                GoogleAdsConfig,
                GoogleAdsConnector,
            )

            acct = self.cfg.accounts.google_ads[0]
            return GoogleAdsConnector(
                GoogleAdsConfig(
                    customer_id=acct.customer_id.replace("-", ""),
                    credentials_file=acct.credentials_file,
                    login_customer_id=acct.login_customer_id,
                    currency=acct.currency,
                )
            )
        from ads_copilot.connectors.yandex_direct import (
            YandexConfig,
            YandexDirectConnector,
        )

        acct = self.cfg.accounts.yandex_direct[0]
        return YandexDirectConnector(
            YandexConfig(
                token=acct.resolve_token(),
                login=acct.login,
                client_login=acct.client_login,
                sandbox=acct.sandbox,
                currency=acct.currency,
            )
        )

    async def close_all(self) -> None:
        for conn in self._cache.values():
            try:
                await conn.close()
            except Exception:
                pass
        self._cache.clear()


class StaticRegistry(ConnectorRegistry):
    """Test-only: skip config, use pre-built connectors."""

    def __init__(self, connectors: dict[Platform, AdPlatformConnector]):
        self._cache = connectors
        self.cfg = None  # type: ignore[assignment]

    def available(self) -> list[Platform]:
        return list(self._cache.keys())

    def _build(self, platform: Platform) -> AdPlatformConnector:
        raise KeyError(f"no connector for {platform}")
