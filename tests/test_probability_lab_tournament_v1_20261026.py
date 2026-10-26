"""No-future, fixed-roster model tournament and conservative recommendation tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from math import sin

import pytest

from probability_lab_tournament_v1 import (
    MODELS, explain_tournament, run_model_tournament,
)


START = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def bars(n=550, *, break_at=None, change_after=None, flat=False):
    result = []
    price = 20000.
    for k in range(n):
        # Reversal/persistent regimes; not live Saxo data.
        if not flat:
            direction = 4 if (k // 14) % 2 == 0 else -3
            price += direction + .1 * sin(k)
            if change_after is not None and k >= change_after:
                price += (k % 3) * 4
        at = START + timedelta(minutes=k + (40 if break_at is not None and k >= break_at else 0))
        result.append(SimpleNamespace(
            bar_time=at.isoformat(),
            close=price, open=price, high=price, low=price
        ))
    return result


@pytest.mark.parametrize("h", (1, 2, 5, 10))
def test_all_models_normalized_forward_and_holdout_nonoverlap(h):
    t = run_model_tournament(bars(600), horizon=h, window=120)
    assert len(MODELS) >= 8
    assert t.candidates == tuple(MODELS)
    assert t.rows
    assert t.validation and t.holdout
    assert t.selected in MODELS
    for r in t.rows:
        assert r.actual in ("up", "down", "flat")
        assert r.probabilities.keys() == MODELS.keys()
        for probs in r.probabilities.values():
            assert sum(probs) == pytest.approx(1., abs=1e-9)
            assert all(0 <= p <= 1 for p in probs)
    for a, b in zip(t.rows, t.rows[1:]):
        assert (datetime.fromisoformat(b.asof) - datetime.fromisoformat(a.asof)) >= timedelta(minutes=h)


def test_forecast_at_fixed_asof_invariant_to_future_appending():
    a = run_model_tournament(bars(260), horizon=2, window=120)
    b = run_model_tournament(bars(340), horizon=2, window=120)
    later = {r.asof: r for r in b.rows}
    for point in a.rows:
        assert point.asof in later
        assert point.probabilities.keys() == later[point.asof].probabilities.keys()
        for model in MODELS:
            assert point.probabilities[model] == pytest.approx(
                later[point.asof].probabilities[model], abs=1e-12
            )
        assert point.actual == later[point.asof].actual


def test_model_selection_has_holdout_and_abstains_for_insufficient_data():
    tiny = run_model_tournament(bars(75), horizon=10, window=60)
    assert tiny.selected is None
    assert not tiny.evidence
    story = explain_tournament(tiny, market="Tech100", roundtrip_bps=8)
    assert "For lite" in story["summary"]
    assert "Ikke" in story["recommendation"]
    medium = run_model_tournament(bars(250), horizon=5, window=120)
    assert medium.selected in MODELS
    assert not medium.evidence  # <100 independent late-period comparisons


def test_constant_price_never_promotes_trading_or_reports_real_fills():
    t = run_model_tournament(bars(600, flat=True), horizon=1, window=120)
    assert t.selected in MODELS
    assert not t.evidence or t.selected != "baseline"
    report = explain_tournament(t, market="Tech100", roundtrip_bps=8)
    assert "Saxo-fill" not in report["summary"]
    assert "LIVE" in report["recommendation"] or "handelsbruk" in report["recommendation"]


def test_gaps_do_not_create_cross_gap_target():
    t = run_model_tournament(bars(540, break_at=300), horizon=5)
    assert t.gap_count == 1
    for f in t.rows:
        at = datetime.fromisoformat(f.asof)
        assert not (START + timedelta(minutes=295) <= at < START + timedelta(minutes=340))


def test_score_is_only_on_future_heldout_observations():
    t = run_model_tournament(bars(550), horizon=1)
    last_val = max(datetime.fromisoformat(r.asof) for r in t.validation)
    first_test = min(datetime.fromisoformat(r.asof) for r in t.holdout)
    assert last_val < first_test
    assert len(t.validation) + len(t.holdout) <= len(t.rows)
    if t.gain_ci95 is not None:
        assert t.gain_ci95[0] <= t.gain_ci95[1]
        base = t.holdout_scores["baseline"]["brier"]
        chosen = t.holdout_scores[t.selected]["brier"]
        assert t.gain_brier == pytest.approx(base - chosen)


def test_research_only_cost_cannot_improve_mean_signal_return():
    low = run_model_tournament(bars(330), horizon=1, threshold=.35, roundtrip_bps=0)
    high = run_model_tournament(bars(330), horizon=1, threshold=.35, roundtrip_bps=30)
    for model in MODELS:
        x = low.holdout_scores[model]
        y = high.holdout_scores[model]
        assert x["signals"] == y["signals"]
        if x["signals"]:
            assert y["mean_net_signal_pct"] == pytest.approx(
                x["mean_net_signal_pct"] - .3
            )


def test_reject_bad_cost_and_propagate_invalid_canonical_data():
    with pytest.raises(ValueError):
        run_model_tournament(bars(300), roundtrip_bps=-1)
    with pytest.raises(ValueError, match="sorted and unique"):
        run_model_tournament(bars(200) + [bars(200)[-1]])
