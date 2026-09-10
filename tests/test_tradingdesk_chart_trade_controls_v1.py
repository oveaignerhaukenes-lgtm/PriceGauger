from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chart_trade_controls_use_canonical_manual_target_path() -> None:
    source = (ROOT / "tradingdesk_chart_trade_controls_v1.py").read_text(encoding="utf-8")

    assert "request_manual_target_v2" in source
    assert "load_manual_target_quote_v2" in source
    assert "_ensure_execution_ready_v1" in source
    assert "_active_live_for_context_v1" in source
    assert "_position_observations_v2" in source
    assert "setTriggerValue('trade_action'" in source
    assert "target_direction=str(action)" in source
    assert "st.rerun(scope=\"fragment\")" in source
    assert "client.post(" not in source
    assert "client.request(" not in source


def test_chart_trade_controls_claim_in_chart_touch_gestures() -> None:
    source = (ROOT / "tradingdesk_chart_trade_controls_v1.py").read_text(encoding="utf-8")

    assert "root.style.touchAction = 'none'" in source
    assert "root.style.overscrollBehavior = 'contain'" in source
    assert "vertTouchDrag: true" in source
    assert "horzTouchDrag: true" in source
    assert "pressedMouseMove: true" in source
