"""Integration-style test for run_scheduled_audit using fake connectors and
a temp config file."""

from pathlib import Path

import pytest

from ads_copilot.scheduler.job import JobOptions, run_scheduled_audit


CONFIG_YAML = """
accounts:
  yandex_direct:
    - name: main
      login: test-login
      token_env: FAKE_TOKEN
      sandbox: true
      currency: USD
business:
  type: fintech
  currency: USD
delivery:
  telegram:
    enabled: false
  markdown:
    enabled: true
    output_dir: "{output_dir}"
"""


@pytest.fixture
def fake_yandex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the real Yandex connector for a fake that returns empty data."""
    from ads_copilot.models import Platform
    from tests.fakes import FakeConnector

    def _make_fake(config):  # type: ignore[no-untyped-def]
        return FakeConnector(
            platform=Platform.YANDEX,
            account_id=config.login,
            currency=config.currency,
        )

    import ads_copilot.scheduler.job as job_module
    original = job_module._build_connectors

    def _patched(cfg):  # type: ignore[no-untyped-def]
        if not cfg.accounts.yandex_direct:
            return []
        return [_make_fake(cfg.accounts.yandex_direct[0])]

    monkeypatch.setattr(job_module, "_build_connectors", _patched)
    monkeypatch.setenv("FAKE_TOKEN", "fake-token-value")
    return None


async def test_run_scheduled_audit_writes_markdown(
    tmp_path: Path, fake_yandex: None
) -> None:
    out_dir = tmp_path / "reports"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        CONFIG_YAML.format(output_dir=str(out_dir).replace("\\", "/")),
        encoding="utf-8",
    )

    result = await run_scheduled_audit(
        JobOptions(
            config_path=str(config_path),
            db_path=str(tmp_path / "db.sqlite"),
            period_days=1,
        )
    )
    assert result.alerts == 0  # no data -> no alerts
    assert result.queries_reviewed == 0
    assert "markdown" in result.delivered
    md_files = list(out_dir.glob("audit-*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "Ads Report" in content


async def test_run_scheduled_audit_no_connectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ads_copilot.scheduler.job as job_module

    monkeypatch.setattr(job_module, "_build_connectors", lambda cfg: [])
    monkeypatch.setenv("FAKE_TOKEN", "x")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        CONFIG_YAML.format(output_dir=str(tmp_path).replace("\\", "/")),
        encoding="utf-8",
    )

    result = await run_scheduled_audit(
        JobOptions(config_path=str(config_path), db_path=str(tmp_path / "db.sqlite"))
    )
    assert result.alerts == 0
    assert result.delivered == []
