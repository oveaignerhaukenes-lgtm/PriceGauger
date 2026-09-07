from __future__ import annotations

import autotrader_saxo_net_position_direction_v2 as net_direction


class _Log:
    def __init__(self):
        self.calls = []

    def warning(self, message, *args):
        self.calls.append((message, args))


def test_identical_warning_state_is_rate_limited_but_repeated_later() -> None:
    log = _Log()
    key = ("mixed", "4912__CfdOnIndex", "4912", 0.04, 0.17, 0.13, "Buy", 0.04)
    net_direction._warning_last_seen.clear()

    assert net_direction._warn_once_per_state_v2(
        log, key=key, message="state %s", args=("same",), now=100.0
    ) is True
    assert net_direction._warn_once_per_state_v2(
        log, key=key, message="state %s", args=("same",), now=101.0
    ) is False
    assert net_direction._warn_once_per_state_v2(
        log,
        key=key,
        message="state %s",
        args=("same",),
        now=100.0 + net_direction._WARNING_DEDUPE_SECONDS,
    ) is True
    assert len(log.calls) == 2


def test_changed_warning_fingerprint_logs_immediately() -> None:
    log = _Log()
    net_direction._warning_last_seen.clear()
    first = ("mixed", "4912", 0.17, 0.13)
    changed = ("mixed", "4912", 0.18, 0.13)

    assert net_direction._warn_once_per_state_v2(
        log, key=first, message="mixed", args=(), now=100.0
    ) is True
    assert net_direction._warn_once_per_state_v2(
        log, key=changed, message="mixed", args=(), now=101.0
    ) is True
    assert len(log.calls) == 2


def test_warning_dedupe_does_not_change_exposure_resolution() -> None:
    log = _Log()
    net_direction._warning_last_seen.clear()
    payload = {
        "Uic": 4912,
        "Amount": 0.04,
        "AmountLong": 0.17,
        "AmountShort": 0.13,
        "OpeningDirection": "Sell",
    }

    first = net_direction.resolve_net_position_exposure_v2(
        payload, net_position_id="4912__CfdOnIndex", logger=log
    )
    second = net_direction.resolve_net_position_exposure_v2(
        payload, net_position_id="4912__CfdOnIndex", logger=log
    )

    assert first == second
    assert first is not None
    assert first.direction == "Buy"
    assert first.amount == 0.04
    # Two warning categories (mixed basis + stale OpeningDirection), each emitted once.
    assert len(log.calls) == 2
