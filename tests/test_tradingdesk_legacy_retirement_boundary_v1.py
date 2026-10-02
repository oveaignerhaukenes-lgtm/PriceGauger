from pathlib import Path


def test_canonical_facade_has_no_runtime_import_from_legacy_panel():
    facade = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "tradingdesk_automanage_panel_legacy_v2" not in facade
    assert "tradingdesk_automanage_read_model_v2" in facade
    assert "tradingdesk_automanage_activity_ui_v2" in facade


def test_extracted_read_model_is_execution_read_only():
    source = Path("tradingdesk_automanage_read_model_v2.py").read_text(encoding="utf-8")
    assert "pnl_enrollments_for_context_v2" in source
    assert "ORDER BY updated_at DESC, enrolled_at DESC" in source
    assert "set_live" not in source
    assert "place_order" not in source
    assert "request_manual_target" not in source
