from dataclasses import replace

from notification_service import (
    DeliveryResult,
    NotificationConfig,
    NotificationStore,
    alert_fingerprint,
    dispatch_market_mover,
    format_alert_text,
    should_notify,
)
from state_contracts import MarketMoverAlert


NOW = "2026-07-30T20:00:00+00:00"


def _alert(*, severity: str = "ALERT", status: str = "ACTIVE") -> MarketMoverAlert:
    return MarketMoverAlert(
        alert_id="market-mover:test",
        event_cluster_id="iran-bombing",
        created_at=NOW,
        updated_at=NOW,
        status=status,
        severity=severity,
        headline="Massive bombing reported in Iran",
        summary="Unconfirmed report during an active ceasefire.",
        confirmation_status="UNCONFIRMED",
        source_quality=0.75,
        novelty=0.9,
        market="Brent",
        expected_direction="UP",
        expected_move_low_pct=2.5,
        expected_move_high_pct=5.0,
        horizon_hours=4.0,
        state_delta=0.9,
        price_confirmation=0.0,
        context_multiplier=1.8,
        rationale="Large context-adjusted move.",
    )


class FakeNotifier:
    channel = "telegram"

    def __init__(self):
        self.recipients = ("123",)
        self.calls = 0

    def send(self, alert, *, dashboard_url=""):
        self.calls += 1
        return [DeliveryResult(self.channel, "123", True)]


def test_notification_threshold_rejects_watch_by_default():
    assert should_notify(_alert(severity="WATCH")) is False
    assert should_notify(_alert(severity="WATCH"), minimum_severity="WATCH") is True
    assert should_notify(_alert(status="REJECTED"), minimum_severity="WATCH") is False


def test_alert_text_contains_actionable_market_context():
    text = format_alert_text(_alert(), dashboard_url="https://example.test")
    assert "Brent MARKEDSFLYTTER" in text
    assert "Estimert bevegelse: +2.50% til +5.00%" in text
    assert "Unconfirmed" in text
    assert "https://example.test" in text


def test_dispatch_is_idempotent_for_same_alert_version(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    notifier = FakeNotifier()
    config = NotificationConfig(minimum_severity="ALERT", dashboard_url="https://example.test")

    first = dispatch_market_mover(_alert(), config=config, store=store, notifiers=(notifier,))
    second = dispatch_market_mover(_alert(), config=config, store=store, notifiers=(notifier,))

    assert first[0].delivered is True
    assert second[0].detail == "duplicate skipped"
    assert notifier.calls == 1


def test_changed_alert_version_can_be_sent_again(tmp_path):
    store = NotificationStore(tmp_path / "notifications.sqlite3")
    notifier = FakeNotifier()
    config = NotificationConfig(minimum_severity="ALERT")
    initial = _alert()
    updated = replace(
        initial,
        updated_at="2026-07-30T20:05:00+00:00",
        status="CONFIRMED",
        price_confirmation=0.6,
    )

    dispatch_market_mover(initial, config=config, store=store, notifiers=(notifier,))
    dispatch_market_mover(updated, config=config, store=store, notifiers=(notifier,))

    assert alert_fingerprint(initial) != alert_fingerprint(updated)
    assert notifier.calls == 2
