from pathlib import Path
from types import SimpleNamespace

import autotrader_manual_close_v1 as manual_close
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE


ROOT = Path(__file__).resolve().parents[1]


def test_manual_close_creates_flat_execution_request_without_broker_post(monkeypatch) -> None:
    enrollment = SimpleNamespace(
        pilot_key="pilot",
        strategy_key="macd-norm-manager-v1",
        execution_mode=EXECUTION_MODE_LIVE,
        enabled=True,
    )
    observation = SimpleNamespace(direction="Buy")
    captured = {}

    monkeypatch.setattr(manual_close, "_pg_execution_inflight_v2", lambda _e: False)
    monkeypatch.setattr(manual_close, "is_position_managed_v1", lambda _o: True)
    monkeypatch.setattr(manual_close, "_quiesce_source_authority_v2", lambda _e: None)
    monkeypatch.setattr(
        manual_close,
        "load_pilot_equity_v2",
        lambda **_kwargs: SimpleNamespace(entry_budget=1000.0, currency="NOK"),
    )

    def _persist(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(manual_close, "_persist_intent_and_request_v2", _persist)

    result = manual_close.request_manual_close_v1(enrollment, observation=observation)

    assert result.request_created is True
    assert result.already_flat is False
    assert captured["state"].desired_direction == "FLAT"
    assert captured["state"].pending_target_direction == "FLAT"
    assert captured["state"].intent_signal == "USER_CLOSE_POSITION"
    assert captured["supersede_prior"] is True

    source = (ROOT / "autotrader_manual_close_v1.py").read_text(encoding="utf-8").lower()
    for forbidden in ("trade/v2/orders", "client.post(", "requests.post(", "place_order("):
        assert forbidden not in source


def test_close_position_control_pauses_autotrade_after_request() -> None:
    source = (ROOT / "tradingdesk_automanager_close_control_v1.py").read_text(encoding="utf-8")
    facade = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert '"Close position"' in source
    assert "request_manual_close_v1" in source
    assert "set_auto_manage_enabled_v1(enrollment, False)" in source
    assert "render_close_position_control_v1(context, observations=observations)" in facade


def test_reconciled_close_is_projected_as_flat_square_marker() -> None:
    projection = (ROOT / "autotrader_trade_markers_v2.py").read_text(encoding="utf-8")
    overlay = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "trade_marker_overlay_v2.py"
    ).read_text(encoding="utf-8")
    adapter = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "adapters.py"
    ).read_text(encoding="utf-8")

    assert "req.action = 'CLOSE'" in projection
    assert "close_attempt.status = 'RECONCILED'" in projection
    assert 'direction="FLAT"' in projection
    assert "shape: isFlat ? 'square'" in overlay
    assert "load_autotrader_trade_markers_v2" in adapter


def test_live_chart_keeps_periodic_forming_candle_refresh() -> None:
    page = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    runtime = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "direct_runtime.py"
    ).read_text(encoding="utf-8")

    assert "LIVE_CANDLE_OVERLAY_REFRESH_SECONDS = 1" in page
    assert "LIVE_CHART_BASE_REFRESH_SECONDS = 5" in page
    assert "forming = _forming_chart_candle(context)" in page
    assert "forming_candle=forming" in page
    assert 'st.fragment(run_every=f"{TRADINGDESK_CHART_REFRESH_SECONDS}s" if auto_refresh else None)(' in page
    assert "render_lightweight_live_update_v1(" not in page
    assert "render_lightweight_base_update_v1(" not in page
    assert "payload.forming_candle" in runtime
    assert "setTriggerValue('live_tick', Date.now())" not in runtime
