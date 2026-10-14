"""Walk-forward selection must not see its chronological holdout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sin
from types import SimpleNamespace
from pathlib import Path

import pytest

import aen_walk_forward_v1 as walk
from aen_replay_v1 import AEnPaperConfig

START=datetime(2026,10,14,tzinfo=timezone.utc)
SPLIT=START+timedelta(minutes=400)
END=START+timedelta(minutes=700)


def bar(i,close=100):
    return SimpleNamespace(
        bar_time=(START+timedelta(minutes=i)).isoformat(),
        open=close,high=close+.2,low=close-.2,close=close,volume=10.0)


def test_all_candidates_have_identical_one_unit_risk_and_costs():
    configs=walk.candidate_configs()
    assert len(configs)==13
    assert len({c.identity for c in configs})==13
    assert all(c.max_units==1 and c.costs_enabled for c in configs)
    assert all(c.structure_minutes==5 for c in configs)
    assert sum(c.adaptive for c in configs)==1
    assert set(c.minutes for c in configs)=={2,5,10}


def test_explicit_insufficient_bars_without_scoring(monkeypatch):
    def fail(*a,**k):
        raise AssertionError("must not run expensive tests with insufficient data")
    monkeypatch.setattr(walk,"replay",fail)
    r=walk.evaluate_walk_forward([bar(i) for i in range(30)],
        started_at=START,split_at=SPLIT,ended_at=END)
    assert r.status=="INSUFFICIENT_BARS"
    assert r.selected_name is None and r.candidates==()


def test_selection_frozen_before_holdout_evaluation(monkeypatch):
    rows=[bar(i) for i in range(700)]
    chronology=[]
    def fake_prepare(data,config):
        return len(data)
    def fake_replay(cfg,data,*,started_at,prepared):
        is_train=(walk.utc(started_at)==START)
        chronology.append((is_train, len(data), cfg.identity))
        # Training prefers 10m; held-out deliberately prefers 2m.
        score=(cfg.minutes if is_train else -cfg.minutes)
        return SimpleNamespace(return_pct=float(score),
            max_drawdown_pct=2.0,executions=6,turnover_units=6,
            total_cost_pct=.5)
    monkeypatch.setattr(walk,"replay",fake_replay)
    monkeypatch.setattr(walk,"prepare_replay_inputs",fake_prepare)
    configs=(AEnPaperConfig(minutes=2),AEnPaperConfig(minutes=10))
    r=walk.evaluate_walk_forward(rows,started_at=START,split_at=SPLIT,
                                ended_at=END,configs=configs)
    assert r.status=="SCORED"
    assert r.selected_name==configs[1].label
    assert r.candidates[1].selected_on_training
    assert r.candidates[1].holdout_net_pct==-10
    assert [training for training,*_ in chronology]==[True,True,False,False]
    assert all(length==400 for training,length,_ in chronology if training)
    assert all(length==700 for training,length,_ in chronology if not training)


def test_holdout_future_prices_do_not_change_choice(monkeypatch):
    logs=[]
    def fake_prepare(data,config):
        return len(data)
    def fake_replay(cfg,data,*,started_at,prepared):
        is_train=walk.utc(started_at)==START
        # Train score depends only on the bars actually supplied to TRAIN.
        net=(sum(x.close for x in data)/len(data)-100 if is_train
             else data[-1].close-100)
        return SimpleNamespace(return_pct=net+cfg.minutes*.01,
            max_drawdown_pct=0.,executions=3,turnover_units=3,
            total_cost_pct=.05)
    monkeypatch.setattr(walk,"replay",fake_replay)
    monkeypatch.setattr(walk,"prepare_replay_inputs",fake_prepare)
    left=[bar(i) for i in range(700)]
    altered=[bar(i,close=500 if i>=400 else 100) for i in range(700)]
    configs=(AEnPaperConfig(minutes=2),AEnPaperConfig(minutes=10))
    a=walk.evaluate_walk_forward(left,started_at=START,split_at=SPLIT,
                                 ended_at=END,configs=configs)
    b=walk.evaluate_walk_forward(altered,started_at=START,split_at=SPLIT,
                                 ended_at=END,configs=configs)
    assert a.selected_name==b.selected_name
    assert [x.training_net_pct for x in a.candidates]==[
           x.training_net_pct for x in b.candidates]
    assert [x.holdout_net_pct for x in a.candidates]!=[
           x.holdout_net_pct for x in b.candidates]


def test_no_lookahead_with_real_engine(monkeypatch):
    rows=[bar(i,close=100+.002*i+sin(i/12)*.75)
          for i in range(740)]
    result=walk.evaluate_walk_forward(rows,started_at=START+timedelta(minutes=120),
        split_at=START+timedelta(minutes=500),
        ended_at=START+timedelta(minutes=740))
    assert result.train_bars==380 and result.test_bars==240
    assert result.status in {"SCORED","INSUFFICIENT_TRADES"}
    assert len(result.candidates)==13
    assert sum(x.selected_on_training for x in result.candidates)<=1
    assert all(x.training_executions>=0 and x.holdout_executions>=0
               for x in result.candidates)


def test_mismatched_risk_or_structure_cannot_be_compared():
    rows=[bar(i) for i in range(720)]
    base=AEnPaperConfig(minutes=2)
    with pytest.raises(ValueError,match="matched"):
        walk.evaluate_walk_forward(rows,started_at=START,
            split_at=SPLIT,ended_at=END,
            configs=(base,AEnPaperConfig(minutes=5,max_units=3)))
    with pytest.raises(ValueError,match="structure"):
        walk.evaluate_walk_forward(rows,started_at=START,
            split_at=SPLIT,ended_at=END,
            configs=(base,AEnPaperConfig(minutes=5,structure_minutes=10)))


def test_split_validation_and_presentation_isolation():
    with pytest.raises(ValueError,match="start"):
        walk.evaluate_walk_forward([],started_at=START,
            split_at=END,ended_at=SPLIT)
    ui=Path("aen_lab_ui_v1.py").read_text()
    assert "Kjør walk-forward på valgt tidsvindu" in ui
    assert "selected_on_training" in ui
    assert "Holdout netto" in ui
    source=Path("aen_walk_forward_v1.py").read_text()
    for banned in ("place_order(", "configured_client", "from database import",
                   "set_live_enabled"):
        assert banned not in source
