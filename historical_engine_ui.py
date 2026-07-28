from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import streamlit as st


def _pct(value: float | None, *, signed: bool = False, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    prefix = "+" if signed else ""
    return f"{float(value):{prefix}.{digits}f} %"


def _interval(low: float | None, high: float | None) -> str:
    if low is None or high is None or pd.isna(low) or pd.isna(high):
        return "—"
    return f"{float(low):+.2f} til {float(high):+.2f} %"


def render_semantic_ranking_table(rows: Iterable[dict[str, Any]]) -> None:
    records = []
    for index, item in enumerate(rows, start=1):
        records.append(
            {
                "rank": index,
                "title": str(item.get("title") or ""),
                "published_at": str(item.get("published_at") or ""),
                "combined_similarity": float(item.get("combined_similarity") or 0.0),
                "event_similarity": float(item.get("event_similarity") or 0.0),
                "market_similarity": float(item.get("market_similarity") or 0.0),
                "explanation": str(item.get("explanation") or ""),
            }
        )
    if not records:
        st.info("Ingen semantiske vurderinger er tilgjengelige.")
        return

    frame = pd.DataFrame(records)
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        row_height=76,
        column_order=(
            "rank",
            "title",
            "combined_similarity",
            "event_similarity",
            "market_similarity",
            "published_at",
            "explanation",
        ),
        column_config={
            "rank": st.column_config.NumberColumn("#", width="small", format="%d"),
            "title": st.column_config.TextColumn("Historisk kandidat", width="large"),
            "combined_similarity": st.column_config.ProgressColumn(
                "Samlet likhet",
                width="medium",
                min_value=0.0,
                max_value=1.0,
                format="%.0f%%",
            ),
            "event_similarity": st.column_config.NumberColumn(
                "Hendelse",
                width="small",
                format="percent",
            ),
            "market_similarity": st.column_config.NumberColumn(
                "Marked",
                width="small",
                format="percent",
            ),
            "published_at": st.column_config.TextColumn("Tidspunkt", width="medium"),
            "explanation": st.column_config.TextColumn("Begrunnelse", width="large"),
        },
    )


def _render_summary_card(label: str, value: str, detail: str = "") -> None:
    with st.container(border=True):
        st.caption(label)
        st.markdown(f"### {value}")
        if detail:
            st.caption(detail)


def render_historical_assessment(assessment: Any) -> None:
    probability_up = assessment.probability_up
    probability_down = assessment.probability_down

    left, right = st.columns(2)
    with left:
        _render_summary_card(
            "Hovedsignal · 4 timer",
            assessment.forecast_direction,
            f"{_pct(None if probability_up is None else probability_up * 100, digits=0)} opp · "
            f"{_pct(None if probability_down is None else probability_down * 100, digits=0)} ned",
        )
        _render_summary_card(
            "Forventet bevegelse · median",
            _pct(assessment.expected_return_pct, signed=True),
            f"Sannsynlig intervall: {_interval(assessment.likely_interval_low_pct, assessment.likely_interval_high_pct)}",
        )
    with right:
        _render_summary_card(
            "Modellsikkerhet",
            _pct(assessment.confidence * 100, digits=0),
            f"{assessment.independent_analogues} uavhengige analogtidspunkter",
        )
        _render_summary_card(
            "Bredt historisk intervall",
            _interval(assessment.broad_interval_low_pct, assessment.broad_interval_high_pct),
            f"Status: {assessment.status}",
        )

    st.markdown("#### Alle vurderte tidshorisonter")
    horizons = list(assessment.horizons)
    for start in range(0, len(horizons), 2):
        columns = st.columns(2)
        for column, horizon in zip(columns, horizons[start : start + 2]):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{horizon.horizon} · {horizon.direction}**")
                    up = _pct(None if horizon.probability_up is None else horizon.probability_up * 100, digits=0)
                    down = _pct(None if horizon.probability_down is None else horizon.probability_down * 100, digits=0)
                    st.write(f"Opp: **{up}** · ned: **{down}**")
                    st.write(f"Median: **{_pct(horizon.median_return_pct, signed=True)}**")
                    st.write(
                        "Sannsynlig intervall: "
                        f"**{_interval(horizon.likely_interval_low_pct, horizon.likely_interval_high_pct)}**"
                    )
                    st.write(
                        "Bredt intervall: "
                        f"**{_interval(horizon.broad_interval_low_pct, horizon.broad_interval_high_pct)}**"
                    )
                    st.caption(f"Datapunkter: {horizon.observations}")

    st.caption(
        f"Rå reaksjoner: {assessment.raw_reactions} · "
        f"duplikater fjernet: {assessment.duplicate_reactions_removed} · "
        f"kalibreringsmål: {assessment.calibration_target}"
    )
