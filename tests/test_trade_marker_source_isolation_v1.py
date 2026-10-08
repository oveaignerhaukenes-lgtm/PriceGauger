from datetime import datetime, timezone

import autotrader_trade_markers_v2 as markers_v2
from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1


def _marker(source: str, key: str):
    return AutoTraderTradeMarkerV1(
        executed_at=datetime(2026,10,9,tzinfo=timezone.utc),
        execution_price=100.0,
        direction="LONG",
        amount=0.01,
        strategy_key=key,
        net_position_id=key,
        active=False,
        source=source,
    )


def test_marker_aggregator_keeps_v3_when_legacy_source_fails(monkeypatch):
    expected=_marker("AUTOTRADER_V3","v3")
    monkeypatch.setattr(markers_v2,"load_v3_trade_markers_v1",lambda market:(expected,))
    monkeypatch.setattr(markers_v2,"load_autotrader_trade_markers_v1",lambda market:(_ for _ in ()).throw(RuntimeError("legacy")))
    monkeypatch.setattr(markers_v2,"_flat_markers_v2",lambda market:())
    monkeypatch.setattr(markers_v2,"load_manual_saxo_trade_markers_v1",lambda market:())
    assert markers_v2.load_autotrader_trade_markers_v2("US Tech 100 NAS") == (expected,)


def test_marker_aggregator_keeps_other_sources_when_v3_projection_fails(monkeypatch):
    expected=_marker("SAXO_MANUAL_FILL","manual")
    monkeypatch.setattr(markers_v2,"load_v3_trade_markers_v1",lambda market:(_ for _ in ()).throw(RuntimeError("v3")))
    monkeypatch.setattr(markers_v2,"load_autotrader_trade_markers_v1",lambda market:())
    monkeypatch.setattr(markers_v2,"_flat_markers_v2",lambda market:())
    monkeypatch.setattr(markers_v2,"load_manual_saxo_trade_markers_v1",lambda market:(expected,))
    assert markers_v2.load_autotrader_trade_markers_v2("US Tech 100 NAS") == (expected,)
