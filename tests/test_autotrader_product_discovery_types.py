from __future__ import annotations

from trading_desk_products import LEVERAGED_ASSET_TYPE_NAMES


def test_supported_leveraged_types_are_knockout_focused() -> None:
    assert LEVERAGED_ASSET_TYPE_NAMES == (
        "MiniFuture",
        "WarrantKnockOut",
        "WarrantOpenEndKnockOut",
        "WarrantOtherLeverageWithKnockOut",
        "WarrantDoubleKnockOut",
    )
