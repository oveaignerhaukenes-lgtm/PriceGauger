"""Markedsrytme production-safe projections and navigation contracts."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_rhythm_dashboard_v1 import (
    amplitude_duration_counts_v1,
    build_rhythm_view_v1,
    cross_scale_alignment_v1,
    duration_bucket_v1,
    last_confirmed_legs_v1,
    turn_table_v1,
)


def wave(values):
    return pd.Series(
        values, index=pd.date_range("2026-10-16T10:00:00Z",
        periods=len(values),freq="1min"), dtype=float
    )


def test_confirmed_turns_and_leg_timing_are_separately_recorded():
    v=build_rhythm_view_v1(wave([100,101,100,99,100,101,100,99,100]),thresholds_pct=(0.5,))
    assert v.as_of == pd.Timestamp("2026-10-16T10:08:00Z")
    events=v.turns[0.5]
    assert len(events)>=4
    first_peak=next(t for t in events if t.kind=="PEAK")
    assert first_peak.pivot_at < first_peak.confirmed_at
    table=turn_table_v1(v,threshold_pct=0.5)
    assert table[0]["Bekreftet"] >= table[0]["Topp-/bunntid"]
    assert any(row["Deteksjonsforsinkelse min"]>0 for row in table)
    assert any(leg.confirmed_at > leg.end_at for leg in v.legs)


def test_half_cycles_four_minute_full_cycles_and_velocity():
    v=build_rhythm_view_v1(wave([100,101,100,99]*15),thresholds_pct=(0.5,))
    p=v.profiles[0]
    assert p.median_leg_minutes == pytest.approx(2)
    assert p.median_cycle_minutes == pytest.approx(4)
    assert v.legs
    for leg in v.legs:
        assert leg.speed_pct_per_min == pytest.approx(leg.amplitude_pct/leg.duration_minutes)
    table=last_confirmed_legs_v1(v,threshold_pct=0.5)
    assert table and table[0]["Minutter"]>0


def test_heatmap_counts_each_smallest_threshold_swing_once():
    v=build_rhythm_view_v1(wave([100,101,100,99]*25),thresholds_pct=(0.25,0.5,1.0))
    table=amplitude_duration_counts_v1(v)
    expected=sum(1 for l in v.legs if l.threshold_pct==0.25)
    assert int(table.to_numpy().sum())==expected


def test_gap_does_not_splice_two_sessions_into_fake_cycle():
    p=wave([100,101,100,99,100,101,100])
    p.index=pd.DatetimeIndex([
        p.index[0],p.index[1],p.index[2],p.index[3],
        p.index[4]+pd.Timedelta(minutes=15),
        p.index[5]+pd.Timedelta(minutes=15),
        p.index[6]+pd.Timedelta(minutes=15),
    ])
    v=build_rhythm_view_v1(p,thresholds_pct=(0.5,))
    assert all(leg.duration_minutes < 15 for leg in v.legs)


def test_missing_cadence_returns_unknown_not_a_fabricated_phase():
    v=build_rhythm_view_v1(wave([100+0.01*x for x in range(60)]),thresholds_pct=(1.0,))
    assert v.profiles[0].completed_cycles==0
    assert v.profiles[0].median_cycle_minutes is None
    assert v.turns[1.0]==()
    assert cross_scale_alignment_v1(v)==[]


def test_cross_scale_match_is_backwards_only_from_confirmation():
    v=build_rhythm_view_v1(wave([100,103,100,97]*20),thresholds_pct=(0.5,1.0,3.0))
    comparison=cross_scale_alignment_v1(v)
    assert len(comparison)==2
    assert all(x["Historisk match"]<=x["Bekreftede makrovendinger"] for x in comparison)
    assert all(x["Median bekreftelseslag min"] is None or x["Median bekreftelseslag min"]>=0 for x in comparison)


def test_amplitude_duration_buckets_are_disjoint():
    assert [duration_bucket_v1(x) for x in (1,2,3,5,15,22)] == [
        "1m","2m","3–4m","5–8m","9–20m",">20m"
    ]


def test_new_market_rhythm_page_is_only_reading_canonical_data():
    ui=Path("pages/0_Markedsrytme.py").read_text(encoding="utf-8")
    model=Path("market_rhythm_dashboard_v1.py").read_text(encoding="utf-8")
    navigation=Path("navigation_config.py").read_text(encoding="utf-8")
    assert '"title": "Markedsrytme"' in navigation
    assert '"url_path": "Markedsrytme"' in navigation
    assert "CanonicalMarketBarStoreV2().load_instrument_range" in ui
    assert "list_subscribed_sources_v2" in ui
    assert '@st.fragment(run_every="30s")' in ui
    for prohibited in (
        "place_order(", "set_live_enabled", "save_autotrader_config_v3",
        "switch_live_strategy", "request_manual_target", "saxo_provider",
        "insert into", "update autotrader_",
    ):
        assert prohibited not in (ui+"\n"+model).lower()
