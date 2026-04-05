"""Render CampaignTree as a human-readable markdown hierarchy."""

from __future__ import annotations

from ads_copilot.models import CampaignStatus, CampaignTree, MatchType


def _status_tag(status: CampaignStatus) -> str:
    return {
        CampaignStatus.ENABLED: "ENABLED",
        CampaignStatus.PAUSED: "PAUSED",
        CampaignStatus.REMOVED: "REMOVED",
        CampaignStatus.UNKNOWN: "?",
    }[status]


def _money(minor: int | None, currency: str) -> str:
    if minor is None:
        return "-"
    return f"{minor / 1_000_000:,.0f} {currency}/day"


def _match(mt: MatchType) -> str:
    return {MatchType.EXACT: "Exact", MatchType.PHRASE: "Phrase", MatchType.BROAD: "Broad"}[mt]


def render_structure(tree: CampaignTree) -> str:
    lines: list[str] = []
    lines.append(f"## {tree.platform.value.title()} Account: {tree.account_id}")
    lines.append("")
    for c in tree.campaigns:
        budget = _money(c.daily_budget_minor, tree.currency)
        strat = c.bidding_strategy or "-"
        lines.append(
            f"### Campaign: {c.name} [{_status_tag(c.status)}] [{budget}]"
        )
        lines.append(f"  Strategy: {strat}")
        n = len(c.adgroups)
        for i, ag in enumerate(c.adgroups):
            branch = "└──" if i == n - 1 else "├──"
            warn = ""
            if ag.ads_count and ag.ads_count < 2:
                warn = " ⚠️ only 1 ad"
            lines.append(
                f"  {branch} AdGroup: {ag.name} "
                f"[{len(ag.keywords)} keywords, {ag.ads_count} ads]{warn}"
            )
            for kw in ag.keywords[:8]:
                qs = f"QS:{kw.quality_score}" if kw.quality_score else ""
                cpc = f"CPC:{kw.cpc_minor / 1_000_000:.2f}" if kw.cpc_minor else ""
                extras = " ".join(x for x in (qs, cpc) if x)
                lines.append(
                    f"      KW: {kw.text} [{_match(kw.match_type)}] {extras}".rstrip()
                )
            if len(ag.keywords) > 8:
                lines.append(f"      … and {len(ag.keywords) - 8} more")
        lines.append("")
    return "\n".join(lines)
