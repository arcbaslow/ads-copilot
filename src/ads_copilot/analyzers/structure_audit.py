"""Campaign-structure quality checks.

Reads a CampaignTree and flags structural problems: too few ads per adgroup,
single-keyword adgroups (when the SKAG pattern isn't wanted), oversized
adgroups, low Quality Score keywords. These are the kinds of issues that
silently bleed budget — weak ad rotation, untargeted keyword sprawl, poor
QS driving up CPC.
"""

from __future__ import annotations

from ads_copilot.analyzers.alerts import Alert, Severity
from ads_copilot.config import StructureRules
from ads_copilot.models import CampaignStatus, CampaignTree, Platform


def audit_structure(tree: CampaignTree, rules: StructureRules) -> list[Alert]:
    """Scan a campaign tree for structural problems."""
    alerts: list[Alert] = []
    platform = tree.platform

    for campaign in tree.campaigns:
        if campaign.status != CampaignStatus.ENABLED:
            continue

        for ag in campaign.adgroups:
            if ag.status != CampaignStatus.ENABLED:
                continue

            kw_count = len(ag.keywords)

            # Ads-per-adgroup — too few ads means no rotation for testing
            if 0 < ag.ads_count < rules.min_ads_per_adgroup:
                alerts.append(
                    Alert(
                        severity=Severity.WARNING,
                        category="structure",
                        platform=platform,
                        title=(
                            f'"{campaign.name} / {ag.name}" has only '
                            f"{ag.ads_count} ad(s)"
                        ),
                        detail=(
                            f"Adgroup has {ag.ads_count} active ad(s); "
                            f"min is {rules.min_ads_per_adgroup}. "
                            "Weak ad rotation limits creative testing."
                        ),
                        campaign_id=campaign.id,
                        campaign_name=campaign.name,
                        metric_values={"ads_count": ag.ads_count, "adgroup_id": ag.id},
                    )
                )

            # Single-keyword adgroup check (SKAG pattern intentional or not)
            if rules.single_keyword_adgroups == "warn" and kw_count == 1:
                alerts.append(
                    Alert(
                        severity=Severity.INFO,
                        category="structure",
                        platform=platform,
                        title=(
                            f'"{campaign.name} / {ag.name}" is single-keyword'
                        ),
                        detail=(
                            "One keyword per adgroup (SKAG pattern). "
                            "Set single_keyword_adgroups: ok to silence."
                        ),
                        campaign_id=campaign.id,
                        campaign_name=campaign.name,
                        metric_values={"adgroup_id": ag.id},
                    )
                )

            # Oversized adgroup — too many keywords dilutes relevance
            if kw_count > rules.max_keywords_per_adgroup:
                alerts.append(
                    Alert(
                        severity=Severity.WARNING,
                        category="structure",
                        platform=platform,
                        title=(
                            f'"{campaign.name} / {ag.name}" has {kw_count} keywords'
                        ),
                        detail=(
                            f"Max recommended is {rules.max_keywords_per_adgroup}. "
                            "Large adgroups weaken ad-to-keyword relevance and hurt QS."
                        ),
                        campaign_id=campaign.id,
                        campaign_name=campaign.name,
                        metric_values={
                            "keywords_count": kw_count,
                            "adgroup_id": ag.id,
                        },
                    )
                )

    # Low Quality Score keywords — Google-only (Yandex doesn't expose QS the same way)
    if platform == Platform.GOOGLE:
        alerts.extend(_low_qs_alerts(tree, qs_min=5))

    return alerts


def _low_qs_alerts(tree: CampaignTree, qs_min: int) -> list[Alert]:
    """Emit one grouped alert per adgroup with low-QS keywords.

    Per-keyword alerts would drown the digest. We summarize: '<adgroup> has
    N keywords below QS <threshold>'.
    """
    alerts: list[Alert] = []
    for campaign in tree.campaigns:
        if campaign.status != CampaignStatus.ENABLED:
            continue
        for ag in campaign.adgroups:
            if ag.status != CampaignStatus.ENABLED:
                continue
            low_qs = [
                kw for kw in ag.keywords
                if kw.quality_score is not None and kw.quality_score < qs_min
            ]
            if not low_qs:
                continue
            worst = min(kw.quality_score for kw in low_qs if kw.quality_score is not None)
            severity = Severity.CRITICAL if worst <= 3 else Severity.WARNING
            alerts.append(
                Alert(
                    severity=severity,
                    category="structure",
                    platform=tree.platform,
                    title=(
                        f'"{campaign.name} / {ag.name}" has '
                        f"{len(low_qs)} keyword(s) below QS {qs_min}"
                    ),
                    detail=(
                        f"Worst keyword QS: {worst}. Low QS inflates CPC and "
                        "hurts ad rank. Review ad copy, landing page, and keyword "
                        "match tightness."
                    ),
                    campaign_id=campaign.id,
                    campaign_name=campaign.name,
                    metric_values={
                        "low_qs_count": len(low_qs),
                        "worst_qs": worst,
                        "adgroup_id": ag.id,
                    },
                )
            )
    return alerts
