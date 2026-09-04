from __future__ import annotations

from pathlib import Path


def test_manage_control_is_product_level_and_pauses_only_unstarted_strategy_requests() -> None:
    source = Path("autotrader_manage_control_v1.py").read_text(encoding="utf-8")
    assert "PRIMARY KEY(account_id, uic, asset_type)" in source
    assert "return True" in source  # migration default: existing active controller remains ON
    assert "status IN ('PENDING','APPROVED')" in source
    assert "AUTOMANAGER_OFF" in source
    assert "SUBMITTING" not in source.split("AUTOMANAGER_OFF", 1)[0].split("UPDATE pg_v2_autotrader_execution_requests", 1)[-1]
    assert "pg_v2_autotrader_fast_live_state" in source


def test_manual_buy_sell_uses_normal_execution_requests_not_direct_saxo_post() -> None:
    source = Path("autotrader_manual_target_v2.py").read_text(encoding="utf-8")
    assert "_persist_intent_and_request_v2" in source
    assert "grant_user_confirmed_flat_authority_v2" in source
    assert "adopt_user_confirmed_position_v2" in source
    assert "trade/v2/orders" not in source
    assert "_post_once" not in source
