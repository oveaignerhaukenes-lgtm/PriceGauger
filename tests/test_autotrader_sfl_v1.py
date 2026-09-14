from pathlib import Path

from autotrader_sfl_v1 import (
    SFL_STRATEGY_KEYS_V1,
    SFL_TIMEFRAMES_V1,
    sfl_decision_v1,
)


def test_sfl_has_requested_four_horizons() -> None:
    assert SFL_TIMEFRAMES_V1 == (1, 2, 5, 10)
    assert SFL_STRATEGY_KEYS_V1 == {
        1: "sfl-1m-v1",
        2: "sfl-2m-v1",
        5: "sfl-5m-v1",
        10: "sfl-10m-v1",
    }


def test_sfl_short_derisks_to_flat_before_bullish_reentry() -> None:
    recovering = sfl_decision_v1(
        current="SHORT",
        spreads=(-10.0, -8.0, -5.0, -1.0),
        impulse=1.0,
        noise=0.10,
        structure=1.0,
    )
    assert recovering.target == "FLAT"
    assert recovering.reason == "DEFENSIVE_EXIT_SHORT"

    confirmed = sfl_decision_v1(
        current="FLAT",
        spreads=(-10.0, -8.0, -5.0, -1.0),
        impulse=1.0,
        noise=0.10,
        structure=1.0,
    )
    assert confirmed.target == "LONG"
    assert confirmed.reason == "CONFIRM_LONG"


def test_sfl_noise_keeps_uncertain_market_flat() -> None:
    decision = sfl_decision_v1(
        current="FLAT",
        spreads=(-0.4, 0.2, -0.3, 0.1),
        impulse=0.05,
        noise=0.90,
        structure=0.0,
    )
    assert decision.target == "FLAT"
    assert decision.reason == "NOISE_FLAT"


def test_sfl_never_directly_reverses_a_held_position() -> None:
    long_hit = sfl_decision_v1(
        current="LONG",
        spreads=(10.0, 5.0, 1.0, -5.0),
        impulse=-1.0,
        noise=0.10,
        structure=-1.0,
    )
    short_hit = sfl_decision_v1(
        current="SHORT",
        spreads=(-10.0, -5.0, -1.0, 5.0),
        impulse=1.0,
        noise=0.10,
        structure=1.0,
    )
    assert long_hit.target == "FLAT"
    assert short_hit.target == "FLAT"


def test_sfl_is_live_selectable_and_materialized_for_sim() -> None:
    catalog = Path("autotrader_strategy_catalog_v2.py").read_text(encoding="utf-8")
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    materializer = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    for minutes in SFL_TIMEFRAMES_V1:
        assert f'"sfl-{minutes}m-v1"' in catalog
    assert "run_sfl_live_once_v1" in dispatch
    assert "SFL_LIVE_STRATEGIES" in dispatch
    assert "load_sfl_series_v1" in materializer


def test_macd_a_is_materialized_into_strategy_lab() -> None:
    materializer = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    helper = Path("autotrader_macd_a_series_v1.py").read_text(encoding="utf-8")
    assert "load_macd_a_series_v1" in materializer
    assert 'MACD_A_STRATEGY_KEY_V1 = "macd-a-v1"' in helper
    assert '"TARGET_MACD-A"' in helper


def test_sfl_has_no_direct_broker_post_path() -> None:
    source = Path("autotrader_sfl_v1.py").read_text(encoding="utf-8")
    assert "place_order(" not in source
    assert "trade/v2/orders" not in source
    assert "_persist_intent_and_request_v2" in source
