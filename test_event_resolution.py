from event_models import MarketEvent
from event_resolution import UpdateType, canonical_event_from_plan, rank_gdelt_analogues, resolve_observation
from telegram_query_builder import build_search_plan


def _plan(message_id: str, text: str):
    return build_search_plan(
        message_id=message_id,
        message_url=f"https://t.me/Middle_East_Spectator/{message_id}",
        text=text,
        published_at="2026-07-21T10:00:00+00:00",
    )


def _gdelt(event_id: str, title: str, country: str = "") -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source="gdelt_cloud_v2",
        event_date="2026-07-10",
        title=title,
        summary=title,
        category="attack" if "attack" in title.lower() or "bomb" in title.lower() else "statement",
        subcategory="",
        domain="POLITICAL",
        country=country,
        location="",
        actors=[],
        confidence=0.9,
        market_sensitivity=0.7,
        significance=0.7,
        url="",
        raw={},
        published_at="2026-07-10T10:00:00Z",
        timestamp_source="test",
        timestamp_confidence=1.0,
    )


def test_bahrain_embassy_post_is_canonical_and_not_shipping() -> None:
    plan = _plan("100", "BREAKING: The Israeli Embassy in Bahrain was bombed")
    event = canonical_event_from_plan(plan)

    assert event.title == "BREAKING: The Israeli Embassy in Bahrain was bombed"
    assert event.event_type == "attack"
    assert event.target == "diplomatic facility"
    assert event.country == "Bahrain"
    assert event.regime_id == "GEOPOLITICAL_CONFLICT"
    assert event.to_market_event().source == "telegram"


def test_irrelevant_un_statement_cannot_replace_primary_event() -> None:
    canonical = canonical_event_from_plan(_plan("100", "BREAKING: The Israeli Embassy in Bahrain was bombed"))
    candidates = [
        _gdelt("statement", "Israeli ambassador speaks at United Nations event", "Israel"),
        _gdelt("attack", "Bomb attack targets embassy compound in Bahrain", "Bahrain"),
    ]

    matches = rank_gdelt_analogues(canonical, candidates, minimum_score=0.0)

    assert matches[0].event_id == "attack"
    assert canonical.title != matches[0].event.title
    assert canonical.to_market_event().event_id.startswith("telegram:")


def test_exact_repeat_is_duplicate() -> None:
    previous = canonical_event_from_plan(_plan("100", "Drone attack reported at Erbil base"))
    current = canonical_event_from_plan(_plan("101", "Drone attack reported at Erbil base"))

    result = resolve_observation(current, previous)

    assert result.update_type is UpdateType.DUPLICATE
    assert result.cluster_id == previous.cluster_id
    assert result.novelty_score == 0.0


def test_higher_death_toll_is_escalation_in_same_cluster() -> None:
    previous = canonical_event_from_plan(_plan("100", "One soldier was killed in the drone attack at Erbil base"))
    current = canonical_event_from_plan(_plan("101", "Four soldiers were killed in the drone attack at Erbil base"))

    result = resolve_observation(current, previous)

    assert result.update_type is UpdateType.ESCALATION
    assert result.cluster_id == previous.cluster_id
    assert result.fact_changes["fatalities"] == {"old": 1, "new": 4}
    assert result.severity_delta > 0


def test_official_confirmation_changes_confidence_not_event_identity() -> None:
    previous = canonical_event_from_plan(_plan("100", "Drone attack reported at Erbil base"))
    current = canonical_event_from_plan(_plan("101", "Pentagon officially confirms the drone attack at Erbil base"))

    result = resolve_observation(current, previous)

    assert result.update_type is UpdateType.CONFIRMATION
    assert result.cluster_id == previous.cluster_id
    assert result.confidence_delta > 0
    assert result.severity_delta == 0.0
