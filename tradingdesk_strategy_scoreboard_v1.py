from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from autotrader_hybrid_replay_v1 import replay_hybrid_models_v1
from autotrader_strategy_scoreboard_v1 import REGIMES_V1, build_strategy_scoreboard_v1
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from trading_desk_v2_context import TradingDeskV2Context
from tradingdesk_hybrid_lab_v1 import load_hybrid_lab_config_v1


_REGIME_HELP_V1 = {
    "CHOPPY": "lav netto fremdrift + mange retningsskift",
    "EVEN": "balansert/ordnet prisflyt uten tydelig ekstrem",
    "TREND": "høy retningsmessig effektivitet",
    "IMPULSE": "stor del av bevegelsen konsentrert i få bars",
}


@st.cache_data(ttl=60, show_spinner=False)
def _load_scoreboard_v1(
    instrument_id: int,
    weights_items: tuple[tuple[str, float], ...],
    threshold: float,
    cost_bps_per_leg: float,
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7, hours=12)
    bars = CanonicalMarketBarStoreV2().load_instrument_range(
        instrument_id=int(instrument_id),
        start=start,
        end=end,
        limit=12_000,
    )
    replay, _ = replay_hybrid_models_v1(
        bars,
        weights=dict(weights_items),
        hybrid_threshold=float(threshold),
        cost_bps_per_leg=float(cost_bps_per_leg),
    )
    return build_strategy_scoreboard_v1(replay, now=end)


def _window_table_v1(scoreboard) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, by_window in scoreboard.metrics.items():
        row: dict[str, object] = {"Strategi": name}
        for window in ("6h", "24h", "7d"):
            metric = by_window[window]
            row[f"{window} P/L %"] = round(metric.return_pct, 3)
            row[f"{window} DD %"] = round(metric.max_drawdown_pct, 3)
        row["24h skift"] = int(by_window["24h"].switches)
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values("24h P/L %", ascending=False).reset_index(drop=True)
    frame.insert(0, "#", range(1, len(frame) + 1))
    return frame


def _regime_table_v1(scoreboard) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, values in scoreboard.regime_returns_7d.items():
        row: dict[str, object] = {"Strategi": name}
        for regime in REGIMES_V1:
            row[regime] = round(float(values.get(regime, 0.0)), 3)
        rows.append(row)
    return pd.DataFrame(rows)


def render_tradingdesk_strategy_scoreboard_v1(context: TradingDeskV2Context) -> None:
    instrument_id = context.instrument_id
    if instrument_id is None:
        return

    try:
        config = load_hybrid_lab_config_v1(int(instrument_id))
        scoreboard = _load_scoreboard_v1(
            int(instrument_id),
            tuple(sorted((name, float(weight)) for name, weight in config.weights.items())),
            float(config.threshold),
            float(config.cost_bps_per_leg),
        )
    except Exception as exc:
        st.caption(f"Strategy Scoreboard venter: {exc}")
        return

    with st.expander("Strategy Scoreboard · regime", expanded=True):
        st.caption(
            "Samme canonical 1m-data og samme kostnadsantakelse for alle modeller. "
            "P/L er normalisert signalreplay før gearing."
        )

        regime_columns = st.columns(3)
        for column, window in zip(regime_columns, ("6h", "24h", "7d")):
            regime = scoreboard.windows[window]
            with column:
                st.metric(f"Regime · {window}", regime.label, f"pris {regime.net_move_pct:+.2f}%")
                st.caption(
                    f"eff {regime.efficiency:.2f} · reversals {regime.reversal_rate:.2f} · "
                    f"impulse {regime.impulse_share:.2f}"
                )

        table = _window_table_v1(scoreboard)
        if not table.empty:
            st.dataframe(table, hide_index=True, width="stretch")

        with st.expander("Resultat fordelt på regime · siste 7d", expanded=False):
            st.caption(
                "Hver time klassifiseres enkelt som CHOPPY, EVEN, TREND eller IMPULSE. "
                "Tabellen viser hvilken type marked hver modell faktisk har tjent/tapt i."
            )
            regime_table = _regime_table_v1(scoreboard)
            if not regime_table.empty:
                st.dataframe(regime_table, hide_index=True, width="stretch")
            st.caption(" · ".join(f"{key}: {_REGIME_HELP_V1[key]}" for key in REGIMES_V1))


__all__ = ["render_tradingdesk_strategy_scoreboard_v1"]
