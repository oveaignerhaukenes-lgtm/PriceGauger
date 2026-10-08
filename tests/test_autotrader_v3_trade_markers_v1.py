from pathlib import Path

from autotrader_v3_trade_markers_v1 import marker_direction_v3, position_direction_v3


def test_v3_marker_projection_reads_only_execution_events():
    source=Path("autotrader_v3_trade_markers_v1.py").read_text(encoding="utf-8")
    assert "FROM autotrader_v3_execution_events e" in source
    assert "FROM autotrader_v3_order_guard" not in source
    assert "nearest_bar" not in source
    assert "ensure_v3_order_schema" not in source
    assert "LEFT JOIN LATERAL" in source
    assert 'source="AUTOTRADER_V3"' in source
    assert "inventory_before" in source and "inventory_after" in source
    assert "position_units" in source


def test_v3_ledger_derives_flat_from_reconciled_inventory():
    source=Path("autotrader_v3_execution_events_v1.py").read_text(encoding="utf-8")
    assert "THEN 'FLAT'" in source
    assert "inventory_before" in source and "inventory_after" in source


def test_canonical_chart_marker_loader_includes_v3_projection():
    source=Path("autotrader_trade_markers_v2.py").read_text(encoding="utf-8")
    assert "load_v3_trade_markers_v1" in source
    assert "markers.extend(load_v3_trade_markers_v1(market_name))" in source


def test_execution_side_direction_is_kept_separate_from_position_direction():
    assert marker_direction_v3(
        action="REDUCE", side="Buy", resulting_direction="SHORT"
    ) == "LONG"
    assert marker_direction_v3(
        action="REDUCE", side="Sell", resulting_direction="LONG"
    ) == "SHORT"


def test_position_vector_direction_follows_inventory_after():
    assert position_direction_v3(
        inventory_after=-0.05, resulting_direction="SHORT"
    ) == "SHORT"
    assert position_direction_v3(
        inventory_after=0.03, resulting_direction="LONG"
    ) == "LONG"
    assert position_direction_v3(
        inventory_after=0.0, resulting_direction="SHORT"
    ) == "FLAT"


def test_full_close_execution_marker_can_remain_neutral():
    assert marker_direction_v3(
        action="CLOSE", side="Buy", resulting_direction="FLAT"
    ) == "FLAT"


def test_chart_uses_one_compact_execution_triangle_per_v3_event():
    overlay=Path("tradingdesk_ui/charts/lightweight/trade_marker_overlay_v2.py").read_text(encoding="utf-8")
    contract=Path("tradingdesk_ui/charts/lightweight/contract.py").read_text(encoding="utf-8")
    live=Path("tradingdesk_ui/charts/lightweight/live_update.py").read_text(encoding="utf-8")

    assert "vectorSize" not in overlay
    assert ":position" not in overlay
    assert ":execution" in overlay
    assert '"marker_role": "EXECUTION_EVENT"' in contract
    assert "_v3_execution_marker_size" in contract
    assert "account_light" in live and "account_dark" in live


def test_execution_marker_size_distinguishes_build_from_reduce():
    from tradingdesk_ui.charts.lightweight.contract import _v3_execution_marker_size

    assert _v3_execution_marker_size("ADD") > _v3_execution_marker_size("REDUCE")
    assert _v3_execution_marker_size("OPEN") > _v3_execution_marker_size("CLOSE")
    assert _v3_execution_marker_size("REVERSE") > _v3_execution_marker_size("ADD")


def test_three_v3_accounts_receive_distinct_palette_pairs():
    from datetime import datetime, timezone
    from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1
    from tradingdesk_ui.charts.lightweight.contract import _v3_account_palette_map

    markers=tuple(
        AutoTraderTradeMarkerV1(
            executed_at=datetime(2026,10,9,tzinfo=timezone.utc),
            execution_price=1.0,direction="LONG",amount=.01,
            strategy_key=f"s{index}",net_position_id=f"n{index}",active=False,
            source="AUTOTRADER_V3",side="Buy",account_id=account,
        )
        for index,account in enumerate(("ACC-C","ACC-A","ACC-B"))
    )
    palette=_v3_account_palette_map(markers)
    assert set(palette)=={"ACC-A","ACC-B","ACC-C"}
    assert len(set(palette.values()))==3


def test_compact_v3_markers_encode_action_by_size_without_text_noise():
    from tradingdesk_ui.charts.lightweight.contract import _v3_execution_marker_size
    assert _v3_execution_marker_size("REDUCE") < _v3_execution_marker_size("ADD")
    assert _v3_execution_marker_size("ADD") < _v3_execution_marker_size("REVERSE")
    contract=Path("tradingdesk_ui/charts/lightweight/contract.py").read_text(encoding="utf-8")
    live=Path("tradingdesk_ui/charts/lightweight/live_update.py").read_text(encoding="utf-8")
    overlay=Path("tradingdesk_ui/charts/lightweight/trade_marker_overlay_v2.py").read_text(encoding="utf-8")
    assert '"text": ""' in contract
    assert "text: ''" in live
    assert "text: ''" in overlay
