from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spring_trade_engine.observer import observe_bars_v1


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _Bar:
    instrument_id: int
    market_id: int
    market_name: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float


def _bars() -> tuple[_Bar, ...]:
    start = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    closes = (100.0, 100.2, 100.5, 100.9, 101.2, 101.0, 100.6, 100.1, 99.8, 99.7, 100.0, 100.4)
    return tuple(
        _Bar(
            instrument_id=7,
            market_id=3,
            market_name="Test Market",
            bar_time=start + timedelta(minutes=index),
            open=close - 0.05,
            high=close + 0.1,
            low=close - 0.1,
            close=close,
        )
        for index, close in enumerate(closes)
    )


def test_blind_observer_emits_model_light_spring_primitives() -> None:
    observation = observe_bars_v1(_bars(), equilibrium_span=6, minimum_bars=12)

    assert observation.instrument_id == 7
    assert observation.market_id == 3
    assert observation.market_name == "Test Market"
    assert observation.bar_count == 12
    assert observation.equilibrium_price > 0
    assert observation.realized_volatility_pct >= 0
    assert observation.range_volatility_pct > 0
    assert observation.shock_score >= 0
    assert observation.energy_proxy >= 0
    assert observation.turning_state in {"UP", "DOWN", "TURN_UP", "TURN_DOWN", "FLAT"}
    assert observation.estimated_period_minutes is None
    assert observation.damping_ratio is None
    assert observation.oscillation_confidence is None
    assert observation.context_equilibrium_price is None


def test_spring_runtime_has_no_execution_authority_imports() -> None:
    package = ROOT / "spring_trade_engine"
    python_sources = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))

    assert "autotrader_live_open" not in python_sources
    assert "autotrader_live_close" not in python_sources
    assert "autotrader_manual_execution" not in python_sources
    assert "saxo_provider" not in python_sources
    assert "SaxoClient" not in python_sources


def test_spring_has_dedicated_railway_service_configuration() -> None:
    source = (ROOT / "railway.spring.toml").read_text(encoding="utf-8")

    assert "spring_trade_engine/runtime.py" in source
    assert "realtime_worker.py" not in source
    assert "telegram_multi_worker.py" not in source
