from ads_copilot.models import (
    AdGroupNode,
    CampaignNode,
    CampaignStatus,
    CampaignTree,
    KeywordNode,
    MatchType,
    Platform,
)
from ads_copilot.reporters.structure_md import render_structure


def test_render_structure_basic() -> None:
    tree = CampaignTree(
        platform=Platform.GOOGLE,
        account_id="1234567890",
        currency="USD",
        campaigns=[
            CampaignNode(
                id="1",
                name="Loans_Search",
                status=CampaignStatus.ENABLED,
                daily_budget_minor=500_000_000,
                bidding_strategy="Target CPA",
                adgroups=[
                    AdGroupNode(
                        id="10",
                        name="Personal Loans",
                        status=CampaignStatus.ENABLED,
                        keywords=[
                            KeywordNode(
                                text="personal loan almaty",
                                match_type=MatchType.EXACT,
                                quality_score=8,
                            )
                        ],
                        ads_count=3,
                    ),
                    AdGroupNode(
                        id="11",
                        name="Car Loans",
                        status=CampaignStatus.ENABLED,
                        ads_count=1,
                    ),
                ],
            )
        ],
    )
    out = render_structure(tree)
    assert "Loans_Search" in out
    assert "Personal Loans" in out
    assert "500 USD/day" in out
    assert "only 1 ad" in out
    assert "personal loan almaty" in out
    assert "QS:8" in out
