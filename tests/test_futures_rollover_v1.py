from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import futures_rollover_v1 as module
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument
from trading_desk import ChartBar
from tradingdesk_ui.charts.lightweight.direct_contract import build_lightweight_direct_live_payload_v1


def _source(*, asset_type: str = "ContractFutures") -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=7,
        market_name="Brent",
        instrument_id=41,
        instrument_type="future",
        display_name="Brent Sep 2026",
        provider="saxo",
        provider_instrument_id="43660942",
        asset_type=asset_type,
        symbol="COU6",
        price_multiplier=1.0,
        metadata={"expiry": "2026-08-28T18:30:00Z", "description": "Brent Sep 2026"},
    )


class _Client:
    def instrument_details(self, instrument: SaxoInstrument):
        if int(instrument.uic) == 43660942:
            return {
                "Uic": 43660942,
                "PrimaryListing": 49990001,
                "ExpiryDateTime": "2026-08-28T18:30:00Z",
                "IsTradable": False,
                "Symbol": "COU6",
                "Description": "Brent Sep 2026",
            }
        return {
            "Uic": 49990001,
            "PrimaryListing": 49990001,
            "ExpiryDateTime": "2026-10-30T18:30:00Z",
            "IsTradable": True,
            "Symbol": "COV6",
            "Description": "Brent Nov 2026",
        }


def test_expired_subscribed_future_rolls_to_saxo_primary_listing(monkeypatch) -> None:
    monkeypatch.setattr(module, "list_subscribed_sources_v2", lambda provider=None: (_source(),))
    applied = []
    monkeypatch.setattr(
        module,
        "_apply_rollover",
        lambda **kwargs: applied.append(kwargs) or 52,
    )

    summary = module.resolve_saxo_futures_rollovers_once_v1(
        client=_Client(),
        now=datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc),
    )

    assert summary.checked == 1
    assert summary.eligible == 1
    assert summary.rolled == 1
    assert summary.failed == 0
    assert applied[0]["candidate"].uic == 49990001
    assert applied[0]["reason"] in {"CURRENT_NOT_TRADABLE", "CURRENT_EXPIRED"}


def test_non_future_subscription_is_never_rollover_mutated(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "list_subscribed_sources_v2",
        lambda provider=None: (_source(asset_type="CfdOnIndex"),),
    )
    summary = module.resolve_saxo_futures_rollovers_once_v1(client=_Client())
    assert summary.checked == 0
    assert summary.rolled == 0


def test_rollover_chart_marker_is_red_and_snaps_to_first_new_bar() -> None:
    bars = (
        ChartBar(
            market="Brent",
            bar_time="2026-09-07T06:00:00+00:00",
            open=90.0,
            high=91.0,
            low=89.5,
            close=90.5,
            volume=10.0,
        ),
        ChartBar(
            market="Brent",
            bar_time="2026-09-07T06:01:00+00:00",
            open=90.5,
            high=91.2,
            low=90.2,
            close=91.0,
            volume=12.0,
        ),
    )
    payload = build_lightweight_direct_live_payload_v1(
        market="Brent",
        timeframe="1m",
        primary=bars,
        overlays={},
        overlay_mode="actual",
        indicators=None,
        indicator_names=(),
        indicator_timeframes={},
        chart_height=600,
        price_panel_share=.7,
        rollover_events=(
            {
                "occurred_at": datetime(2026, 9, 6, 20, 30, tzinfo=timezone.utc),
                "old_symbol": "COU6",
                "new_symbol": "COV6",
            },
        ),
    )
    rollover = next(item for item in payload["markers"] if str(item.get("text", "")).startswith("ROLLOVER"))
    assert rollover["time"] == int(datetime.fromisoformat(bars[0].bar_time).timestamp())
    assert rollover["color"] == "#dc2626"
    assert "COU6 → COV6" in rollover["text"]


def test_rollover_schema_and_runtime_keep_execution_authority_separate() -> None:
    schema = Path("db_v2_schema.sql").read_text(encoding="utf-8")
    runtime = Path("runtime_subscription_bridge_v2.py").read_text(encoding="utf-8")
    rollover = Path("futures_rollover_v1.py").read_text(encoding="utf-8")
    assert "pg_v2_instrument_rollovers" in schema
    assert "_resolve_futures_rollovers_best_effort()" in runtime
    assert "PrimaryListing" in rollover
    assert "set_collection_subscription_v2" in rollover
    for forbidden in ("place_order", "submit_order", "autotrader_live_open", "autotrader_live_close"):
        assert forbidden not in rollover
