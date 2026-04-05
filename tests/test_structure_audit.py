from ads_copilot.analyzers.alerts import Severity
from ads_copilot.analyzers.structure_audit import audit_structure
from ads_copilot.config import StructureRules
from ads_copilot.models import (
    AdGroupNode,
    CampaignNode,
    CampaignStatus,
    CampaignTree,
    KeywordNode,
    MatchType,
    Platform,
)


def _tree(*campaigns: CampaignNode, platform: Platform = Platform.GOOGLE) -> CampaignTree:
    return CampaignTree(
        platform=platform, account_id="acct", currency="USD", campaigns=list(campaigns)
    )


def _ag(
    name: str, keywords: int = 5, ads: int = 3,
    status: CampaignStatus = CampaignStatus.ENABLED,
    qs: int | None = None,
) -> AdGroupNode:
    kws = [
        KeywordNode(
            text=f"kw-{i}", match_type=MatchType.EXACT,
            quality_score=qs, status=CampaignStatus.ENABLED,
        )
        for i in range(keywords)
    ]
    return AdGroupNode(
        id=name, name=name, status=status, keywords=kws, ads_count=ads,
    )


def _c(name: str, adgroups: list[AdGroupNode], status: CampaignStatus = CampaignStatus.ENABLED) -> CampaignNode:
    return CampaignNode(
        id=name, name=name, status=status,
        daily_budget_minor=None, bidding_strategy=None, adgroups=adgroups,
    )


def test_flags_too_few_ads() -> None:
    rules = StructureRules(min_ads_per_adgroup=2, single_keyword_adgroups="ok")
    tree = _tree(_c("C1", [_ag("AG1", keywords=5, ads=1)]))
    alerts = audit_structure(tree, rules)
    ads_alerts = [a for a in alerts if "ad(s)" in a.title]
    assert len(ads_alerts) == 1
    assert ads_alerts[0].severity == Severity.WARNING


def test_zero_ads_not_flagged_as_too_few() -> None:
    # Zero ads is a different problem (no delivery at all) — covered elsewhere
    rules = StructureRules(min_ads_per_adgroup=2)
    tree = _tree(_c("C1", [_ag("AG1", ads=0)]))
    alerts = audit_structure(tree, rules)
    assert not any("ad(s)" in a.title for a in alerts)


def test_single_keyword_warn() -> None:
    rules = StructureRules(single_keyword_adgroups="warn")
    tree = _tree(_c("C1", [_ag("AG1", keywords=1)]))
    alerts = audit_structure(tree, rules)
    assert any("single-keyword" in a.title for a in alerts)


def test_single_keyword_ok_silenced() -> None:
    rules = StructureRules(single_keyword_adgroups="ok")
    tree = _tree(_c("C1", [_ag("AG1", keywords=1)]))
    alerts = audit_structure(tree, rules)
    assert not any("single-keyword" in a.title for a in alerts)


def test_oversized_adgroup_flagged() -> None:
    rules = StructureRules(max_keywords_per_adgroup=10, single_keyword_adgroups="ok")
    tree = _tree(_c("C1", [_ag("AG1", keywords=25)]))
    alerts = audit_structure(tree, rules)
    assert any("25 keywords" in a.title for a in alerts)


def test_paused_campaigns_ignored() -> None:
    rules = StructureRules(min_ads_per_adgroup=2)
    tree = _tree(
        _c("C1", [_ag("AG1", ads=1)], status=CampaignStatus.PAUSED),
    )
    assert audit_structure(tree, rules) == []


def test_paused_adgroups_ignored() -> None:
    rules = StructureRules(min_ads_per_adgroup=2, single_keyword_adgroups="ok")
    tree = _tree(
        _c("C1", [_ag("AG1", ads=1, status=CampaignStatus.PAUSED)])
    )
    assert audit_structure(tree, rules) == []


def test_low_qs_alert_google_only() -> None:
    rules = StructureRules(single_keyword_adgroups="ok")
    tree = _tree(
        _c("C1", [_ag("AG1", keywords=3, qs=3)]),
        platform=Platform.GOOGLE,
    )
    alerts = audit_structure(tree, rules)
    qs_alerts = [a for a in alerts if "QS" in a.title]
    assert len(qs_alerts) == 1
    assert qs_alerts[0].severity == Severity.CRITICAL  # worst QS of 3


def test_low_qs_moderate_is_warning() -> None:
    rules = StructureRules(single_keyword_adgroups="ok")
    tree = _tree(
        _c("C1", [_ag("AG1", keywords=3, qs=4)]),
    )
    qs_alerts = [a for a in audit_structure(tree, rules) if "QS" in a.title]
    assert qs_alerts[0].severity == Severity.WARNING


def test_low_qs_skipped_on_yandex() -> None:
    rules = StructureRules(single_keyword_adgroups="ok")
    tree = _tree(
        _c("C1", [_ag("AG1", keywords=3, qs=2)]),
        platform=Platform.YANDEX,
    )
    alerts = audit_structure(tree, rules)
    assert not any("QS" in a.title for a in alerts)


def test_keywords_without_qs_not_counted() -> None:
    rules = StructureRules(single_keyword_adgroups="ok")
    tree = _tree(_c("C1", [_ag("AG1", keywords=3, qs=None)]))
    alerts = audit_structure(tree, rules)
    assert not any("QS" in a.title for a in alerts)
