from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_reconciled_open_marker_is_a_durable_runtime_projection() -> None:
    source = _source("autotrader_trade_markers_v1.py")
    assert "CREATE TABLE IF NOT EXISTS pg_v2_autotrader_trade_markers" in source
    assert "request_id UUID PRIMARY KEY REFERENCES pg_v2_autotrader_execution_requests" in source
    assert "NEW.status = 'RECONCILED'" in source
    assert "OLD.status IS DISTINCT FROM 'RECONCILED'" in source
    assert "managed.average_open_price" in source
    assert "req.desired_direction" in source
    assert "ON CONFLICT (request_id) DO NOTHING" in source


def test_trade_marker_schema_is_installed_by_live_open_runtime_not_streamlit_ui() -> None:
    facade = _source("autotrader_live_open_v2.py")
    overlay = _source("trading_desk_live_overlay_v2.py")
    assert "ensure_autotrader_trade_marker_schema_v1()" in facade
    assert "_legacy.run_live_open_forever_v2" in facade
    assert "ensure_autotrader_trade_marker_schema_v1" not in overlay


def test_live_chart_overlay_draws_directional_and_active_markers() -> None:
    source = _source("trading_desk_live_overlay_v2.py")
    assert 'direction === \'LONG\' ? \'#16a34a\' : \'#dc2626\'' in source
    assert "const upward = direction === 'LONG'" in source
    assert "entry.tradeMarkers" in source
    assert "drawTradeMarker(context, xaxis, yaxis, size, marker)" in source
    assert "AKTIV ${direction}" in source
    assert '"trade_markers": trade_markers' in source


def test_marker_loader_separates_historical_autotrader_open_from_active_fallback() -> None:
    source = _source("autotrader_trade_markers_v1.py")
    assert 'source="AUTOTRADER_OPEN"' in source
    assert 'source="ACTIVE_MANAGED_POSITION"' in source
    assert "historical triangles come only from reconciled AutoTrader OPEN requests" in source.lower()
    assert "managed.managed = TRUE" in source
