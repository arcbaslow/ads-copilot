from pathlib import Path

import pytest

from ads_copilot.config import load_config


MINIMAL = """
accounts:
  yandex_direct:
    - name: Main
      login: test-login
      token_env: FAKE_TOKEN
business:
  type: fintech
  currency: KZT
"""


def test_load_minimal_config(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.accounts.yandex_direct[0].login == "test-login"
    assert cfg.business.currency == "KZT"
    assert cfg.rules.performance.ctr_drop_threshold == 0.3


def test_config_requires_at_least_one_account(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("business:\n  currency: USD\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_config(p)


def test_yandex_token_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL, encoding="utf-8")
    monkeypatch.delenv("FAKE_TOKEN", raising=False)
    cfg = load_config(p)
    with pytest.raises(RuntimeError, match="FAKE_TOKEN"):
        cfg.accounts.yandex_direct[0].resolve_token()


def test_yandex_token_env_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL, encoding="utf-8")
    monkeypatch.setenv("FAKE_TOKEN", "y0_secret")
    cfg = load_config(p)
    assert cfg.accounts.yandex_direct[0].resolve_token() == "y0_secret"
