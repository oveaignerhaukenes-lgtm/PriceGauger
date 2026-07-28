from telegram_flow_engine import AssetPostScore, ScoredTelegramPost, aggregate_scored_posts


def _post(message_id: str, event_key: str, direction: float, *, relation: str = "new", novelty: float = 1.0):
    return ScoredTelegramPost(
        message_id=message_id,
        channel="test-channel",
        published_at="2026-07-29T12:00:00+00:00",
        text=message_id,
        event_key=event_key,
        relation=relation,
        novelty=novelty,
        source_quality=1.0,
        scores=(
            AssetPostScore(
                asset="Brent",
                direction=direction,
                impact=1.0,
                confidence=1.0,
                horizon_hours=4.0,
                rationale=message_id,
            ),
        ),
    )


def test_duplicate_event_cluster_is_not_double_counted():
    result = aggregate_scored_posts(
        [_post("a", "same-event", 0.8), _post("b", "same-event", 0.6)],
        as_of="2026-07-29T12:00:00+00:00",
    )

    brent = next(item for item in result.assets if item.asset == "Brent")
    assert brent.selected_event_count == 1
    assert brent.flow_score == 0.8
    assert brent.direction == "LONG_BIAS"
    assert sum(item.selected for item in result.contributions if item.asset == "Brent") == 1


def test_denial_can_reverse_prior_event_when_stronger():
    result = aggregate_scored_posts(
        [
            _post("initial", "event-1", 0.4),
            _post("denial", "event-1", -0.9, relation="denial"),
        ],
        as_of="2026-07-29T12:00:00+00:00",
    )

    brent = next(item for item in result.assets if item.asset == "Brent")
    assert brent.flow_score == -0.9
    assert brent.direction == "SHORT_BIAS"


def test_channel_weight_and_time_decay_affect_score():
    result = aggregate_scored_posts(
        [_post("a", "event-a", 1.0)],
        channel_weights={"test-channel": 2.0},
        as_of="2026-07-29T16:00:00+00:00",
        half_life_hours=4.0,
    )

    brent = next(item for item in result.assets if item.asset == "Brent")
    assert brent.flow_score == 1.0
