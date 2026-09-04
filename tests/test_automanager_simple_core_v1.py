from __future__ import annotations

from pathlib import Path


def test_simple_core_primary_ui_has_only_position_manage_strategy_and_optional_settings() -> None:
    source = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
    assert '"BUY"' in source or 'f"BUY @' in source
    assert '"SELL"' in source or 'f"SELL @' in source
    assert 'st.toggle("Manage position"' in source
    assert '"Strategi"' in source
    assert 'with st.popover("⚙"' in source
    assert '"All-in ved ny strategi-entry"' in source
    assert "Aktiver AutoManager" not in source
    assert "Jeg vil at PriceGauger" not in source
    assert "SHADOW-strategi" not in source


def test_simple_core_manual_targets_precede_optional_strategy_dispatch() -> None:
    source = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    manual = source.index("if manual_target_pending_v2")
    manage_gate = source.index("if not auto_manage_enabled_v1")
    strategy = source.index("if enrollment.strategy_key == AI_BASELINE_STRATEGY_V2")
    assert manual < manage_gate < strategy
    assert "adopt_user_confirmed_position_v2" in source
    assert "is_position_managed_v1" in source


def test_simple_core_keeps_transaction_safety_but_decouples_accounting_from_reentry() -> None:
    facade = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")
    legacy = Path("autotrader_live_open_legacy_v2.py").read_text(encoding="utf-8")
    assert "status IN ('ORDER_ACCEPTED', 'RECONCILED')" in facade
    assert "status IN ('SUBMITTING', 'UNCERTAIN')" in facade
    assert "equity_reconciliations" not in facade
    assert 'block_reason="PRODUCT_NOT_CONFIRMED_FLAT"' in legacy
    assert "_open_orders_exist" in legacy
    assert "precheck_entry_amount_v2" in legacy
    assert "_record_attempt_before_submit" in legacy
    assert "STATUS_UNCERTAIN" in legacy


def test_activity_status_no_longer_claims_30m_or_manual_basis_confirmation() -> None:
    source = Path("autotrader_activity_log_v2.py").read_text(encoding="utf-8")
    assert 'ENGINE_AUTOMANAGER = "AutoManager"' in source
    assert "registrerer AutoManager-basis" in source
    assert "ingen brukerbekreftelse kreves" in source
    assert "AutoManager · MACD 30m" not in source
