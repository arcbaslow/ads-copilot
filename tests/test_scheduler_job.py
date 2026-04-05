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
    """Swap the real Yandex connector enumeration for fakes with empty data."""
    import ads_copilot.scheduler.job as job_module
    from ads_copilot.models import Platform
    from tests.fakes import FakeConnector

    def _patched(cfg):  # type: ignore[no-untyped-def]
        out = []
        for y in cfg.accounts.yandex_direct:
            out.append(
                (
                    f"{y.name} (Yandex)",
                    FakeConnector(
                        platform=Platform.YANDEX,
                        account_id=y.login,
                        currency=y.currency,
                    ),
                )
            )
        return out

    monkeypatch.setattr(job_module, "_enumerate_accounts", _patched)
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
    assert len(result.accounts) == 1
    account = result.accounts[0]
    assert account.alerts == 0  # no data -> no alerts
    assert account.queries_reviewed == 0
    assert "markdown" in account.delivered
    assert "main" in account.account.lower()
    md_files = list(out_dir.glob("audit-*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "Ads Report" in content
    assert "main" in content.lower()  # account label in title


async def test_run_scheduled_audit_no_connectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ads_copilot.scheduler.job as job_module

    monkeypatch.setattr(job_module, "_enumerate_accounts", lambda cfg: [])
    monkeypatch.setenv("FAKE_TOKEN", "x")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        CONFIG_YAML.format(output_dir=str(tmp_path).replace("\\", "/")),
        encoding="utf-8",
    )

    result = await run_scheduled_audit(
        JobOptions(config_path=str(config_path), db_path=str(tmp_path / "db.sqlite"))
    )
    assert result.accounts == []
    assert result.total_alerts == 0
