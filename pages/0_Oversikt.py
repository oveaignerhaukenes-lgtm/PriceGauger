from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from build_info import render_build_badge
from overview_ai_summary import build_overview_summary
from overview_service import load_overview


st.set_page_config(page_title="Oversikt · PriceGauger", page_icon="📡", layout="wide")
render_build_badge()
st.title("PriceGauger")
st.caption("Kontinuerlig markedstilstand · nye hendelser vises som endringer i totalbildet")

st.markdown(
    """
    <style>
    .pg-summary-card,.pg-state-card,.pg-alert-card,.pg-news-card {
        border:1px solid rgba(128,128,128,.24); border-radius:.8rem;
        padding:.85rem 1rem; margin-bottom:.7rem; background:rgba(128,128,128,.035);
    }
    .pg-summary-card {padding:1rem 1.1rem; margin:.35rem 0 1.15rem;}
    .pg-summary-top {display:flex; justify-content:space-between; gap:1rem; align-items:flex-start;}
    .pg-summary-kicker {font-size:.74rem; font-weight:750; letter-spacing:.08em; opacity:.72;}
    .pg-summary-title {font-size:1.05rem; font-weight:750; margin:.28rem 0 .45rem; line-height:1.3;}
    .pg-summary-text {font-size:.9rem; line-height:1.48; max-width:75rem;}
    .pg-summary-tag {white-space:nowrap; border:1px solid rgba(128,128,128,.28); border-radius:999px; padding:.3rem .6rem; font-size:.72rem; font-weight:700;}
    .pg-summary-driver {font-size:.8rem; margin-top:.65rem; line-height:1.4;}
    .pg-state-top {display:flex; justify-content:space-between; gap:.8rem; align-items:flex-start;}
    .pg-market {font-size:1.02rem; font-weight:700;}
    .pg-direction {font-weight:700; letter-spacing:.02em;}
    .pg-meta {font-size:.78rem; opacity:.76; margin-top:.35rem; line-height:1.35;}
    .pg-driver {font-size:.86rem; margin-top:.55rem; line-height:1.35; overflow-wrap:anywhere;}
    .pg-delta {font-size:.78rem; margin-top:.4rem; font-weight:650;}
    .pg-bar {height:.4rem; border-radius:999px; background:rgba(128,128,128,.20); overflow:hidden; margin-top:.55rem;}
    .pg-bar span {display:block; height:100%; border-radius:999px; background:currentColor;}
    .pg-alert-card {padding:1rem;}
    .pg-alert-severity {font-size:.75rem; font-weight:700; letter-spacing:.08em; opacity:.82;}
    .pg-alert-title {font-size:1rem; font-weight:750; margin:.35rem 0 .5rem; line-height:1.3;}
    .pg-alert-summary {font-size:.86rem; line-height:1.4;}
    .pg-alert-grid {display:grid; grid-template-columns:1fr 1fr; gap:.55rem; margin-top:.8rem;}
    .pg-alert-stat {border-top:1px solid rgba(128,128,128,.20); padding-top:.45rem; font-size:.78rem;}
    .pg-news-card {padding:.75rem .9rem;}
    .pg-news-head {display:flex; justify-content:space-between; gap:.75rem; font-size:.76rem; opacity:.76;}
    .pg-news-text {font-size:.88rem; line-height:1.4; margin-top:.35rem; overflow-wrap:anywhere;}
    .pg-news-impact {font-size:.78rem; margin-top:.45rem; font-weight:650;}
    @media(max-width:700px){
      .pg-summary-top {display:block;}
      .pg-summary-tag {display:inline-block; margin-top:.55rem; white-space:normal;}
      .pg-alert-card {margin-top:.35rem;}
      .pg-alert-grid {grid-template-columns:1fr;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _fmt_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%y · %H:%M")
    except Exception:
        return value


def _direction_label(value: str) -> str:
    return {
        "LONG_BIAS": "LONG-BIAS",
        "SHORT_BIAS": "SHORT-BIAS",
        "NEUTRAL": "NØYTRAL",
        "CONFLICTED": "MOTSTRIDENDE",
        "INSUFFICIENT_DATA": "FOR LITE DATA",
        "STALE": "UTDATERT",
    }.get(value, value)


def _direction_color(value: str) -> str:
    if value == "LONG_BIAS":
        return "#2e8b57"
    if value == "SHORT_BIAS":
        return "#b24a4a"
    if value == "CONFLICTED":
        return "#b27a28"
    return "#7a7a7a"


def _sensitivity_label(value: str) -> str:
    return {
        "HEADLINE_SENSITIVE": "OVERSKRIFTSFØLSOMT",
        "COMMODITY_SENSITIVE": "VAREFØLSOMT",
        "MACRO_POLICY_SENSITIVE": "MAKRO-/POLITIKKFØLSOMT",
        "MIXED": "BLANDET REGIME",
        "UNCLEAR": "UKLAR FØLSOMHET",
    }.get(value, value)


try:
    data = load_overview()
except Exception as exc:
    st.error(f"Oversikten kunne ikke lese produksjonsdata: {exc}")
    st.stop()

summary_key = ":".join(
    [
        str(getattr(data.flow, "as_of", "no-flow")),
        str((data.information_state or {}).get("as_of", "no-info")),
        str(len(data.latest_posts)),
    ]
)
try:
    if st.session_state.get("overview_summary_key") != summary_key:
        with st.spinner("Oppsummerer markedsbildet …"):
            st.session_state["overview_summary"] = build_overview_summary(data)
            st.session_state["overview_summary_key"] = summary_key
    summary = st.session_state.get("overview_summary")
except Exception as exc:
    summary = None
    st.caption(f"AI-oppsummeringen kunne ikke oppdateres: {exc}")

if summary is not None:
    st.markdown(
        f"""
        <article class="pg-summary-card">
          <div class="pg-summary-top">
            <div>
              <div class="pg-summary-kicker">AI-OPPSUMMERING · {html.escape(summary.regime)}</div>
              <div class="pg-summary-title">{html.escape(summary.headline)}</div>
            </div>
            <div class="pg-summary-tag">{html.escape(_sensitivity_label(summary.sensitivity))}</div>
          </div>
          <div class="pg-summary-text">{html.escape(summary.summary)}</div>
          <div class="pg-summary-driver"><strong>Viktigste driver:</strong> {html.escape(summary.key_driver)}</div>
          <div class="pg-meta">{html.escape(summary.caveat)} · {html.escape(summary.model)}</div>
        </article>
        """,
        unsafe_allow_html=True,
    )

main_col, mover_col = st.columns([2, 1], gap="large")

with main_col:
    st.subheader("Nåværende markedstilstand")
    if data.flow is None or not data.markets:
        st.info("Venter på første autoritative Decision State-snapshot fra workeren.")
    else:
        for item in data.markets:
            color = _direction_color(item.direction)
            width = max(2.0, min(100.0, abs(item.score) * 100.0))
            delta_label = f"Endring siden forrige snapshot: {item.change_from_previous:+.2f}"
            st.markdown(
                f"""
                <article class="pg-state-card" style="color:{color}">
                  <div class="pg-state-top">
                    <div class="pg-market" style="color:inherit">{html.escape(item.market)}</div>
                    <div class="pg-direction" style="color:inherit">{html.escape(_direction_label(item.direction))}</div>
                  </div>
                  <div class="pg-bar"><span style="width:{width:.1f}%"></span></div>
                  <div class="pg-meta" style="color:var(--text-color)">
                    Decision State {item.score:+.2f} · konfidens {item.confidence:.0%} · {item.event_count} aktive hendelser
                  </div>
                  <div class="pg-delta" style="color:var(--text-color)">{html.escape(delta_label)}</div>
                  <div class="pg-driver" style="color:var(--text-color)">{html.escape(item.top_driver)}</div>
                  <div class="pg-meta" style="color:var(--text-color)">{html.escape(item.status_reason)}</div>
                </article>
                """,
                unsafe_allow_html=True,
            )
        st.caption(
            f"Oppdatert {_fmt_time(data.flow.as_of)} · {data.flow.post_count} poster · "
            f"{data.flow.event_cluster_count} hendelsesklynger · {data.flow.model or 'modell ukjent'}"
        )

with mover_col:
    st.subheader("Siste markedsflytter")
    alert = data.latest_alert
    if alert is None:
        st.info("Ingen hendelse har passert markedsflytter-terskelen ennå.")
    else:
        move_low = float(getattr(alert, "expected_move_low_pct", 0.0))
        move_high = float(getattr(alert, "expected_move_high_pct", 0.0))
        st.markdown(
            f"""
            <article class="pg-alert-card">
              <div class="pg-alert-severity">{html.escape(str(alert.severity))} · {html.escape(str(alert.status))}</div>
              <div class="pg-alert-title">{html.escape(str(alert.headline))}</div>
              <div class="pg-alert-summary">{html.escape(str(alert.summary))}</div>
              <div class="pg-alert-grid">
                <div class="pg-alert-stat"><strong>{html.escape(str(alert.market))}</strong><br>{html.escape(str(alert.expected_direction))}</div>
                <div class="pg-alert-stat"><strong>{move_low:+.2f}% til {move_high:+.2f}%</strong><br>estimert bevegelse</div>
                <div class="pg-alert-stat"><strong>{float(alert.horizon_hours):g} t</strong><br>hovedhorisont</div>
                <div class="pg-alert-stat"><strong>{float(alert.source_quality):.0%}</strong><br>kildekvalitet</div>
              </div>
              <div class="pg-meta">Oppdatert {_fmt_time(str(alert.updated_at))} · kontekstfaktor {float(alert.context_multiplier):.2f}</div>
            </article>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("Se full vurdering"):
            st.write(alert.rationale)
            st.write(f"Nyhetsverdi: {float(alert.novelty):.0%}")
            st.write(f"Tilstandsnudge: {float(alert.state_delta):+.2f}")
            st.write(f"Prisbekreftelse: {float(alert.price_confirmation):+.2f}")

st.divider()
st.subheader("Siste hendelser")
if not data.latest_posts:
    st.info("Ingen scorede Telegram-poster er lagret ennå.")
else:
    for post in data.latest_posts:
        ranked = sorted(
            post.scores,
            key=lambda score: abs(score.direction * score.impact * score.confidence),
            reverse=True,
        )
        lead = ranked[0] if ranked else None
        impact = (
            f"{lead.asset}: {lead.direction * lead.impact * lead.confidence:+.2f} · {lead.rationale}"
            if lead is not None
            else "Ingen beregnet markedseffekt."
        )
        st.markdown(
            f"""
            <article class="pg-news-card">
              <div class="pg-news-head"><span>{html.escape(post.channel)}</span><span>{html.escape(_fmt_time(post.published_at))}</span></div>
              <div class="pg-news-text">{html.escape(post.text)}</div>
              <div class="pg-news-impact">{html.escape(impact)}</div>
              <div class="pg-meta">{html.escape(post.relation)} · nyhetsverdi {post.novelty:.0%} · kildekvalitet {post.source_quality:.0%}</div>
            </article>
            """,
            unsafe_allow_html=True,
        )

with st.expander("Informasjonstilstand og datakvalitet"):
    if data.information_state is None:
        st.write("Ingen Information State er lagret ennå.")
    else:
        info = data.information_state
        st.write(
            {
                "as_of": info.get("as_of"),
                "conflict_regime": info.get("conflict_regime"),
                "ceasefire_active": info.get("ceasefire_active"),
                "narrative_saturation": info.get("narrative_saturation"),
                "confirmation_quality": info.get("confirmation_quality"),
                "supply_risk": info.get("supply_risk"),
            }
        )
