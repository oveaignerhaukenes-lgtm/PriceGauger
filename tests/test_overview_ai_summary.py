import json

from overview_ai_summary import build_overview_summary
from overview_service import OverviewData, OverviewMarket


def _data() -> OverviewData:
    return OverviewData(
        flow=None,
        markets=(
            OverviewMarket(
                market="Brent",
                direction="LONG_BIAS",
                score=0.42,
                confidence=0.36,
                event_count=3,
                top_driver="Supply-risk escalation",
                change_from_previous=0.08,
                status_reason="Price and technical confirmation pending.",
            ),
        ),
        latest_posts=(),
        information_state={
            "as_of": "2026-07-31T00:00:00+00:00",
            "conflict_regime": "CEASEFIRE",
            "ceasefire_active": True,
            "narrative_saturation": 0.15,
            "confirmation_quality": 0.45,
            "supply_risk": 0.62,
            "active_event_count": 3,
        },
        latest_alert=None,
    )


def test_summary_falls_back_without_api_key():
    result = build_overview_summary(_data(), api_key="")

    assert result.model == "deterministic-fallback"
    assert result.regime == "CEASEFIRE"
    assert result.sensitivity == "HEADLINE_SENSITIVE"
    assert "Brent" in result.headline


def test_summary_uses_structured_ai_response():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output_text": json.dumps(
                    {
                        "regime": "Skjør våpenhvile",
                        "sensitivity": "HEADLINE_SENSITIVE",
                        "headline": "Markedet er svært følsomt for brudd på våpenhvilen",
                        "summary": "Ny eskalering kan raskt endre Brent-bildet, men prisbekreftelse mangler.",
                        "key_driver": "Forsyningsrisiko under et roligere utgangspunkt.",
                        "caveat": "Ingen kalender- eller teknisk bekreftelse i datagrunnlaget.",
                    }
                )
            }

    class Session:
        def __init__(self):
            self.request = None

        def post(self, url, **kwargs):
            self.request = {"url": url, **kwargs}
            return Response()

    session = Session()
    result = build_overview_summary(_data(), api_key="test-key", model="test-model", session=session)

    assert result.model == "test-model"
    assert result.regime == "Skjør våpenhvile"
    assert result.sensitivity == "HEADLINE_SENSITIVE"
    assert "trade recommendation" in session.request["json"]["input"][0]["content"]
    assert "No economic calendar" in session.request["json"]["input"][1]["content"]
