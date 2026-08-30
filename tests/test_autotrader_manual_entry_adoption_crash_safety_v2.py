from __future__ import annotations

from pathlib import Path


def test_manual_resize_retires_every_old_managed_basis_before_reenrollment():
    source = Path("autotrader_manual_entry_adoption_v2.py").read_text(encoding="utf-8")
    retire = source.index("UPDATE pg_v2_autotrader_managed_positions")
    enroll = source.index("enroll_position_v1(observation)")
    assert retire < enroll
    retired_sql = source[retire:enroll]
    assert "account_id = ? AND uic = ? AND asset_type = ?" in retired_sql
    assert "NOT (net_position_id" not in retired_sql
