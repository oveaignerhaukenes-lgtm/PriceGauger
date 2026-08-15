from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from analysis_status import AnalysisStatusStore
from analysis_status_ui import ANALYSIS_STATUS_CSS, render_analysis_status
from build_info import render_build_badge
from market_history_store import MarketHistoryStore
from market_mover_observation import format_elapsed, observe_market_mover
from market_navigation import market_detail_href
from overview_ai_summary import build_overview_summary
from overview_service import load_overview
from overview_v2_cards import render_v2_overview_market_cards
from overview_visuals import asset_color
from saxo_auth import configured_oauth_client


st.set_page_config(page_title="Oversikt · PriceGauger", page_icon="📡", layout="wide")

render_build_badge()
title_col, saxo_col = st.columns([4, 1])
with title_col:
    st.title("PriceGauger")
    st.caption("Kontinuerlig markedstilstand · nye hendelser vises som endringer i totalbildet")
with saxo_col:
    try:
        _saxo_client = configured_oauth_client()
        _saxo_status = _saxo_client.status() if _saxo_client is not None else {
            "connected": False,
            "environment": "ukjent",
            "status": "NOT_CONFIGURED",
        }
    except Exception:
        _saxo_status = {"connected": False, "environment": "ukjent", "status": "STATUS_ERROR"}
    _saxo_icon = "🟢" if _saxo_status.get("connected") else "🔴"
    st.markdown(
        f"**{_saxo_icon} Saxo · {str(_saxo_status.get('environment', 'ukjent')).upper()}**"
    )
    st.caption(str(_saxo_status.get("status", "UKJENT")).replace("_", " "))
    st.page_link("pages/1_Saxo_OpenAPI.py", label="Åpne Saxo-status", icon="🔌")

st.markdown(
    """
    <style>
    .pg-summary-card,.pg-market-card,.pg-alert-card,.pg-news-card {
        border:1px solid rgba(128,128,128,.24); border-radius:.8rem;
        padding:.85rem 1rem; margin-bottom:.7rem; background:rgba(128,128,128,.035);
    }
    .pg-summary-card {padding:1rem 1.1rem; margin:.35rem 0 .8rem;}
    .pg-summary-top {display:flex; justify-content:space-between; gap:1rem; align-items:flex-start;}
    .pg-summary-kicker {font-size:.74rem; font-weight:750; letter-spacing:.08em; opacity:.72;}
    .pg-summary-title {font-size:1.05rem; font-weight:750; margin:.28rem 0 .45rem; line-height:1.3;}
    .pg-summary-text {font-size:.9rem; line-height:1.48; max-width:75rem;}
    .pg-summary-tag {white-space:nowrap; border:1px solid rgba(128,128,128,.28); border-radius:999px; padding:.3rem .6rem; font-size:.72rem; font-weight:700;}
    .pg-summary-driver {font-size:.8rem; margin-top:.65rem; line-height:1.4;}

    .pg-alert-card {padding:.72rem 1rem; margin-bottom:1.05rem;}
    .pg-alert-row {display:grid; grid-template-columns:minmax(11rem,1.25fr) minmax(16rem,3fr) repeat(4,minmax(6.5rem,.75fr)); gap:.75rem; align-items:center;}
    .pg-alert-severity {font-size:.7rem; font-weight:750; letter-spacing:.08em; opacity:.75;}
    .pg-alert-title {font-size:.94rem; font-weight:750; line-height:1.25; margin-top:.16rem;}
    .pg-alert-summary {font-size:.8rem; line-height:1.35; opacity:.9;}
    .pg-alert-stat {border-left:1px solid rgba(128,128,128,.22); padding-left:.7rem; font-size:.74rem; line-height:1.25;}
    .pg-alert-stat strong {font-size:.82rem;}

    .pg-market-card {padding:0; overflow:hidden; border-left:4px solid var(--market-color); transition:box-shadow .12s ease,border-color .12s ease;}
    .pg-market-card:hover {box-shadow:0 .2rem .75rem rgba(15,23,42,.08); border-color:rgba(128,128,128,.38); border-left-color:var(--market-color);}
    .pg-market-layout {display:grid; grid-template-columns:minmax(0,5fr) minmax(12rem,2.2fr) minmax(16rem,3fr);}
    .pg-analysis {padding:.9rem 1rem 1rem;}
    .pg-recommendation {padding:.9rem 1rem 1rem; border-left:1px solid rgba(128,128,128,.22); background:rgba(128,128,128,.035);}
    .pg-forecast {padding:.75rem .55rem .7rem .8rem; border-left:1px solid rgba(128,128,128,.22); background:rgba(128,128,128,.018); min-width:0;}
    .pg-state-top {display:flex; justify-content:space-between; gap:.8rem; align-items:flex-start;}
    .pg-market {font-size:1.05rem; font-weight:780; color:var(--market-color);}
    .pg-market-title-link {color:var(--market-color)!important; text-decoration:none!important; border-radius:.2rem;}
    .pg-market-title-link:hover {text-decoration:underline!important; text-underline-offset:.16rem;}
    .pg-market-title-link:focus-visible {outline:2px solid var(--market-color); outline-offset:2px;}
    .pg-direction {font-weight:750; letter-spacing:.02em; color:var(--market-color);}
    .pg-meta {font-size:.78rem; opacity:.76; margin-top:.35rem; line-height:1.35;}
    .pg-data-health {font-size:.72rem; margin-top:.48rem; padding:.32rem .45rem; border-radius:.45rem; background:rgba(128,128,128,.08); line-height:1.3;}
    .pg-rec-kicker {font-size:.69rem; font-weight:780; letter-spacing:.09em; opacity:.7;}
    .pg-rec-action {font-size:1.25rem; font-weight:820; margin:.28rem 0 .12rem; color:var(--market-color);}
    .pg-rec-signal {font-size:.78rem; font-weight:700; margin-bottom:.65rem;}
    .pg-rec-grid {display:grid; grid-template-columns:1fr; gap:.42rem;}
    .pg-rec-row {border-top:1px solid rgba(128,128,128,.18); padding-top:.4rem; font-size:.76rem; line-height:1.3;}
    .pg-rec-row strong {display:block; font-size:.82rem; margin-bottom:.08rem;}
    .pg-rec-status {display:inline-block; margin-top:.62rem; border:1px solid rgba(128,128,128,.28); border-radius:999px; padding:.28rem .55rem; font-size:.69rem; font-weight:780; letter-spacing:.05em;}

    .pg-news-card {padding:.75rem .9rem;}
    .pg-news-head {display:flex; justify-content:space-between; gap:.75rem; font-size:.76rem; opacity:.76;}
    .pg-news-text {font-size:.88rem; line-height:1.4; margin-top:.35rem; overflow-wrap:anywhere;}
    .pg-news-impact {font-size:.78rem; margin-top:.45rem; font-weight:650;}

    @media(max-width:1100px){
      .pg-alert-row {grid-template-columns:1fr 2fr repeat(2,1fr);}
      .pg-alert-stat:nth-last-child(-n+2) {margin-top:.15rem;}
      .pg-market-layout {grid-template-columns:minmax(0,3fr) minmax(13rem,1.4fr);}
      .pg-forecast {grid-column:1 / -1; border-left:0; border-top:1px solid rgba(128,128,128,.22);}
    }
    @media(max-width:700px){
      .pg-summary-top {display:block;}
      .pg-summary-tag {display:inline-block; margin-top:.55rem; white-space:normal;}
      .pg-alert-row {grid-template-columns:1fr 1fr;}
      .pg-alert-main,.pg-alert-summary {grid-column:1 / -1;}
      .pg-alert-stat {border-left:0; border-top:1px solid rgba(128,128,128,.22); padding:.45rem 0 0;}
      .pg-market-layout {grid-template-columns:1fr;}
      .pg-recommendation,.pg-forecast {border-left:0; border-top:1px solid rgba(128,128,128,.22); grid-column:auto;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(f"<style>{ANALYSIS_STATUS_CSS}</style>", unsafe_allow_html=True)


def _render_live_analysis_status() -> None:
    """Render worker progress without waiting for the rest of Overview to load."""
    progress_html = render_analysis_status(AnalysisStatusStore().load())
    if progress_html:
        st.markdown(progress_html, unsafe_allow_html=True)


_fragment = getattr(st, "fragment", getattr(st, "experimental_fragment", None))
if _fragment is not None:
    _fragment(run_every="2s")(_render_live_analysis_status)()
else:
    _render_live_analysis_status()


def _fmt_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%y · %H:%M")
    except Exception:
        return value


def _sensitivity_label(value: str) -> str:
    return {
        "HEADLINE_SENSITIVE": "OVERSKRIFTSFØLSOMT",
        "COMMODITY_SENSITIVE": "VAREFØLSOMT",
        "MACRO_POLICY_SENSITIVE": "MAKRO-/POLITIKKFØLSOMT",
        "MIXED": "BLANDET REGIME",
        "UNCLEAR": "UKLAR FØLSOMHET",
    }.get(value, value)


def _render_live_market_cards() -> None:
    render_v2_overview_market_cards(
        st,
        asset_color=asset_color,
        market_detail_href=market_detail_href,
    )


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

st.subheader("Siste markedsflytter")
alert = data.latest_alert
if alert is None:
    st.info("Ingen hendelse har passert markedsflytter-terskelen ennå.")
else:
    move_low = float(getattr(alert, "expected_move_low_pct", 0.0))
    move_high = float(getattr(alert, "expected_move_high_pct", 0.0))
    estimated_label = f"{move_low:+.2f}% til {move_high:+.2f}%".replace(".", ",")
    observation = observe_market_mover(alert, MarketHistoryStore())
    if observation is None:
        observed_label = "Ikke observert ennå"
    else:
        observed_label = (
            f"{observation.move_pct:+.2f}% i løpet av {format_elapsed(observation.elapsed_minutes)}"
        ).replace(".", ",")
    st.markdown(
        f"""
        <article class="pg-alert-card">
          <div class="pg-alert-row">
            <div class="pg-alert-main">
              <div class="pg-alert-severity">{html.escape(str(alert.severity))} · {html.escape(str(alert.status))}</div>
              <div class="pg-alert-title">{html.escape(str(alert.headline))}</div>
            </div>
            <div class="pg-alert-summary">{html.escape(str(alert.summary))}</div>
            <div class="pg-alert-stat"><strong>{html.escape(str(alert.market))}</strong><br>{html.escape(str(alert.expected_direction))}</div>
            <div class="pg-alert-stat">
              Estimert bevegelse:<br><strong>{html.escape(estimated_label)}</strong><br><br>
              Observert bevegelse:<br><strong>{html.escape(observed_label)}</strong>
            </div>
            <div class="pg-alert-stat"><strong>{float(alert.horizon_hours):g} t</strong><br>hovedhorisont</div>
            <div class="pg-alert-stat"><strong>{float(alert.source_quality):.0%}</strong><br>kildekvalitet</div>
          </div>
          <div class="pg-meta">Oppdatert {_fmt_time(str(alert.updated_at))} · kontekstfaktor {float(alert.context_multiplier):.2f}</div>
        </article>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Se full markedsflytter-vurdering"):
        st.write(alert.rationale)
        st.write(f"Nyhetsverdi: {float(alert.novelty):.0%}")
        st.write(f"Tilstandsnudge: {float(alert.state_delta):+.2f}")
        st.write(f"Prisbekreftelse: {float(alert.price_confirmation):+.2f}")

st.subheader("Teknisk analyse og prognose · v2")
if _fragment is not None:
    _fragment(run_every="15s")(_render_live_market_cards)()
else:
    _render_live_market_cards()

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
