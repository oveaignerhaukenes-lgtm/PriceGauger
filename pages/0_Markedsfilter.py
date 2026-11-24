"""Markedsfilter overview; operator-only regime policy settings, read-only data."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from autotrader_v3_config_v1 import load_autotrader_config_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_live_authority_v1 import live_authority_armed_v3
from autotrader_v3_regime_gate_v1 import (
    STATES_V1, classify_regime_v1, load_regime_policy_v1, save_regime_policy_v1,
    decide_regime_entry_v1, load_regime_block_count_v1, strategy_entry_directions_v1,
)
from autotrader_v3_registry_v1 import strategy_v3
from autotrader_v3_stop_go_status_v1 import (
    UNKNOWN, load_v3_stop_go_lights_v1,
)
from build_info import render_build_badge
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect
from impulse_regime_bridge_v1 import (
    MAX_RESEARCH_QUOTES, detect_impulse_pulses_v1, prepare_impulse_sessions_v1,
    score_impulse_regime_v1, summarize_impulse_regime_v1,
)
from instrument_registry_v2 import list_subscribed_sources_v2
from market_filter_module_status_v1 import (
    MODULES_V1, evidence_freshness_v1, latest_observed_timestamp_v1,
    load_market_filter_evidence_v1,
)


st.set_page_config(page_title="Markedsfilter · PriceGauger", page_icon="🚦", layout="wide")
render_build_badge()
st.title("Markedsfilter og modulkart")
st.caption(
    "Se hvilke data modulene bruker, hva de vurderer og om nye observasjoner faktisk kommer inn. "
    "Prisdata leses fra databasen – ingen Saxo-kall eller ordre. "
    "Regimefilterets innstillinger lagres direkte når du endrer dem."
)

now = datetime.now(timezone.utc)
hours = st.selectbox(
    "Statistikkvindu", (6, 24, 72, 168), index=1,
    format_func=lambda h: f"Siste {h} timer" if h != 168 else "Siste 7 døgn",
    help="Endrer bare visningen, aldri filterets LIVE-innstillinger.",
)
try:
    instances = tuple(load_v3_instances_v1())
except Exception as exc:
    st.warning("V3-instansregisteret er utilgjengelig: " + type(exc).__name__)
    instances = ()

try:
    evidence = load_market_filter_evidence_v1(
        instance_ids=(i.instance_id for i in instances),
        instrument_ids=(i.instrument_id for i in instances),
        account_ids=(i.account_id for i in instances),
        hours=hours, now=now,
    )
except Exception as exc:
    st.error("Kan ikke bekrefte modulenes datagrunnlag: " + type(exc).__name__)
    st.stop()

configured = []
valid_lights = []
for item in instances:
    strategy = "UKJENT"
    armed = None
    try:
        strategy = load_autotrader_config_v3(item.instance_id).strategy_key
        armed = live_authority_armed_v3(item.instance_id)
        valid_lights.append((item.instance_id, strategy, armed))
    except Exception:
        pass
    configured.append((item, strategy, armed))
lights = load_v3_stop_go_lights_v1(tuple(valid_lights)) if valid_lights else {}


def _fresh(value, minutes, *, sql_utc=False):
    return evidence_freshness_v1(
        value, now=now, fresh_seconds=minutes * 60, sql_utc=sql_utc)


def _stamp(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return "UKJENT"
        return dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
    except (TypeError, ValueError):
        return "UKJENT"


def _age(status):
    seconds = status["age_seconds"]
    return "—" if seconds is None else f"{seconds // 60}m {seconds % 60}s"


def _stream_state(row):
    if not row:
        return {"symbol": "⚪", "label": "INGEN STREAMSTATUS", "age_seconds": None}
    age = _fresh(row.get("updated_at"), 3)
    if age["label"] != "NYLIGE DATA":
        return age
    state = str(row.get("state") or "UKJENT").upper()
    color = "🟢" if state == "STREAMING" else "🔴" if state == "FAILED" else "🟡"
    return {**age, "symbol": color, "label": state}


filter_tab, module_tab = st.tabs(("🚦 Markedsfilter", "🧩 Moduloversikt"))

with filter_tab:
    st.subheader("Hva filteret gjør – og ennå ikke gjør")
    lane = st.columns(4)
    with lane[0].container(border=True):
        st.markdown("**1 · Inndata**")
        st.caption("Saxo → kanoniske 1m-barer + eksakt V3-konto/strategi")
    with lane[1].container(border=True):
        st.markdown("**2 · Markedsprofil**")
        st.caption("61 ferdige 1m-barer → trend/rytme 3×3")
    with lane[2].container(border=True):
        st.markdown("**3 · Observasjon**")
        st.caption("Tilstand × strategi lagres; fremtidig 5m-pris merkes senere")
    with lane[3].container(border=True):
        st.markdown("**4 · LIVE-kontroll**")
        st.caption("Manuell STOPP/KJØR + valgfri regimeport for OPEN/ADD")
    st.info(
        "Regimefilteret er **AV som standard**. Det kan testes i SKYGGE før manuelt LIVE-valg. "
        "BULL/BEAR/SIDEWAYS er en forhåndsdefinert prisregel, ikke et lært eller "
        "resultatvalidert tapsfilter. Manuell STOPP har alltid forrang. "
        "CLOSE/REDUCE blokkeres aldri av regimet."
    )

    price_stamps = [evidence["bars"].get(i.instrument_id) for i in instances]
    freshest_bar = latest_observed_timestamp_v1(price_stamps)
    price_state = _fresh(freshest_bar, 3)
    latest_stream = max(evidence["streams"].values(),
                        key=lambda row: str(row.get("updated_at") or ""), default=None)
    socket_state = _stream_state(latest_stream)
    observer_state = _fresh(evidence["last_observed"], 10)
    runtime_states = [
        _fresh(evidence["runtime"].get(i.instance_id, {}).get("updated_at"),
               2, sql_utc=True)
        for i in instances
    ]
    n_running = sum(s["label"] == "NYLIGE DATA" for s in runtime_states)
    a, b, c, d = st.columns(4)
    a.metric("LIVE-armede instanser", sum(armed is True for _, _, armed in configured))
    b.metric("🔴 Manuelt STOPP", sum(lights.get(i.instance_id, UNKNOWN).label == "STOPP"
                                      for i, _, _ in configured))
    c.metric("Observasjoner", evidence["total"])
    d.metric("Modne 5m-prisutfall", evidence["matured"])

    st.markdown("**Datatilførsel og arbeidsstatus**")
    st.dataframe([
        {
            "Datalink / arbeid": "Saxo realtime-stream · sist rapportert",
            "Indikator": socket_state["symbol"] + " " + socket_state["label"],
            "Sist": _stamp(evidence["stream_last"]), "Alder": _age(socket_state),
        },
        {
            "Datalink / arbeid": "Saxo 1m → kanonisk lager",
            "Indikator": price_state["symbol"] + " " + price_state["label"],
            "Sist": _stamp(freshest_bar), "Alder": _age(price_state),
        },
        {
            "Datalink / arbeid": "Markedsprofil → strategiobservasjoner (5m)",
            "Indikator": observer_state["symbol"] + " " + observer_state["label"],
            "Sist": _stamp(evidence["last_observed"]), "Alder": _age(observer_state),
        },
        {
            "Datalink / arbeid": "V3 beslutningsløype / runtime",
            "Indikator": f"{n_running} av {len(instances)} med nylig heartbeat",
            "Sist": "Per instans nedenfor", "Alder": "—",
        },
    ], hide_index=True, width="stretch")
    st.caption(
        "🟢 = ferskt, observert data eller nyere STREAMING-status. 🟡 = annen fersk "
        "streamtilstand. 🔴 = fersk, rapportert FAILED-status. 🟠 = ingen nylig observasjon, "
        "**ikke** bevist brudd i Saxo-lenken: markedet kan være stengt. "
        "⚪ = ingen måling eller ukjent. Stream-status er siste lagrede melding, ikke en ny nettverksping. "
        "1m-barer og 5m-observatør er ikke samme forbindelse som Saxos sekund-BBO."
    )
    if evidence["streams"]:
        with st.expander("Saxo stream-status per marked"):
            st.dataframe([
                {
                    "Marked": market,
                    "Sist rapportert stream-state": status["state"],
                    "Datastatus": _stream_state(status)["symbol"]
                                  + " " + _stream_state(status)["label"],
                    "Sist (UTC)": _stamp(status.get("updated_at")),
                }
                for market, status in sorted(evidence["streams"].items())
            ], hide_index=True, width="stretch")
            st.caption(
                "Streamstatus er registrert per markedsnavn, ikke per Saxo-konto/UIC. "
                "Den bekrefter derfor ikke alene en bestemt strategis tickdekning."
            )

    st.subheader("LIVE-filter per strategi")
    if not configured:
        st.warning("Ingen registrerte V3-instanser å vise. Det betyr ikke at noen handler er stoppet.")
    else:
        fleet_rows = []
        for item, strategy, armed in configured:
            light = lights.get(item.instance_id, UNKNOWN)
            account_title = evidence["account_names"].get(item.account_id) or item.account_id
            bar = evidence["bars"].get(item.instrument_id)
            observation = evidence["instances"].get(item.instance_id, {})
            latest_profile = evidence["latest_profiles"].get(item.instance_id, {})
            runtime = evidence["runtime"].get(item.instance_id, {})
            regime_status = "⚪ UKJENT"
            regime_selection = "⚪ kan ikke leses"
            if strategy != "UKJENT":
                try:
                    runtime_key = strategy_v3(strategy).runtime_key or strategy
                    rp = load_regime_policy_v1(
                        instance_id=item.instance_id, strategy_key=runtime_key)
                    regime_selection = rp.mode + " · " + (", ".join(rp.allowed_states) or "ingen")
                    if rp.mode != "OFF":
                        ending = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
                        stored = CanonicalMarketBarStoreV2().load_instrument_range(
                            instrument_id=item.instrument_id,
                            start=ending-timedelta(minutes=63), end=ending, limit=65)
                        observed, _ = classify_regime_v1(stored, now=now)
                        regime_status = observed
                    else:
                        regime_status = "— (AV)"
                except Exception:
                    pass
            fleet_rows.append({
                "Konto": account_title, "Strategi": strategy,
                "Manuell STOPP/KJØR": light.symbol + " " + light.label,
                "Regimeport": regime_selection,
                "Prisregime": regime_status,
                "Regimeblokkerte ordre": load_regime_block_count_v1(instance_id=item.instance_id),
                "Siste 1m-bar": _stamp(bar),
                "Prisdata": _fresh(bar, 3)["symbol"] + " " + _fresh(bar, 3)["label"],
                "Siste 3×3-avlesning": _stamp(observation.get("newest")),
                "3×3-profil": latest_profile.get("state_key") or "UKJENT",
                "Effektivitet": latest_profile.get("efficiency"),
                "1m-volatilitet %": latest_profile.get("volatility_pct_1m"),
                "Antall observasjoner": observation.get("samples") or 0,
                "Modne 5m": observation.get("matured") or 0,
                "Worker": _fresh(runtime.get("updated_at"), 2, sql_utc=True)["symbol"]
                          + " " + str(runtime.get("status") or "UKJENT"),
            })
        st.dataframe(fleet_rows, hide_index=True, width="stretch")
        st.caption("🟢/🔴 under manuell STOPP/KJØR viser **nødstoppen**, ikke "
                   "en garantert tillatelse i regimeporten. Regimeport=LIVE kan "
                   "i tillegg blokkere bare feil retning eller valgt prisregime.")
    st.page_link(
        "pages/0_AutoTrader_V3.py", label="Åpne AutoTrader V3 for manuell STOPP/KJØR og øvrige innstillinger",
        icon="⚙️",
    )

    st.subheader("Regimefilter · BULL / BEAR / SIDEWAYS")
    st.caption(
        "Inndata: eksakt Saxo-UICs lagrede, sammenhengende og ferdige 1m-kurser. "
        "30m er foreløpig; etter 60m brukes 60m-retning, og sterk motsatt 30m gir SIDEWAYS. "
        "UKJENT betyr for få eller gamle priser, ikke SIDEWAYS. Ingen nye Saxo GET-kall."
    )
    if configured:
        chosen_instance = st.selectbox(
            "Konto/strategi å konfigurere",
            tuple(configured),
            format_func=lambda row: (
                f"{evidence['account_names'].get(row[0].account_id) or row[0].account_id} "
                f"· {row[1]} · {'LIVE' if row[2] else 'ikke LIVE'}"),
            key="market-regime-instance",
        )
        chosen, chosen_strategy, chosen_armed = chosen_instance
        try:
            runtime_key = strategy_v3(chosen_strategy).runtime_key or chosen_strategy
            policy = load_regime_policy_v1(instance_id=chosen.instance_id,
                                           strategy_key=runtime_key)
            last_open = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
            bars = CanonicalMarketBarStoreV2().load_instrument_range(
                instrument_id=chosen.instrument_id,
                start=last_open-timedelta(minutes=63), end=last_open, limit=65)
            market_state, market_reason = classify_regime_v1(bars, now=now)
            status_color = "🟢" if market_state == "BULL" else "🔴" if market_state == "BEAR" else "🟡" if market_state == "SIDEWAYS" else "⚪"
            st.write(f"**{status_color} {market_state}** · {market_reason}")
            st.caption(
                f"Lagret filter: {policy.mode} · {', '.join(policy.allowed_states) or 'ingen regimer'} "
                f"· {'kun medgang' if policy.trend_only else 'begge retninger'} "
                f"· UKJENT {'sperret' if policy.block_unknown else 'slippes gjennom'}"
            )
            # Widgets are bound to the exact instance AND runtime strategy.
            # Only the changed field is written, using a fresh saved policy.
            # Rerenders and account switching never write settings.
            prefix = f"regime-policy-auto:{chosen.instance_id}:{runtime_key}:"
            mode_key, states_key, trend_key = (prefix + s for s in ("mode", "states", "trend"))
            error_key = prefix + "error"
            st.session_state[mode_key] = policy.mode
            st.session_state[states_key] = list(policy.allowed_states) + (
                [] if policy.block_unknown else ["UNKNOWN"])
            st.session_state[trend_key] = policy.trend_only

            def save_changed(field, widget_key, instance_id=chosen.instance_id,
                             strategy_key=runtime_key, err_key=error_key):
                try:
                    saved = load_regime_policy_v1(instance_id=instance_id,
                                                  strategy_key=strategy_key)
                    mode, allowed, trend, block_unknown = (
                        saved.mode, saved.allowed_states, saved.trend_only, saved.block_unknown)
                    value = st.session_state[widget_key]
                    if field == "mode":
                        mode = value
                    elif field == "states":
                        allowed = tuple(s for s in STATES_V1 if s in value)
                        block_unknown = "UNKNOWN" not in value
                    elif field == "trend":
                        trend = bool(value)
                    save_regime_policy_v1(instance_id=instance_id, strategy_key=strategy_key,
                        mode=mode, allowed_states=allowed, trend_only=trend,
                        block_unknown=block_unknown)
                    st.session_state.pop(err_key, None)
                except Exception as exc:
                    st.session_state[err_key] = "Endringen ble ikke lagret: " + type(exc).__name__

            if error_key in st.session_state:
                st.error(st.session_state[error_key])
            st.selectbox("Modus", ("OFF", "SHADOW", "LIVE"), key=mode_key,
                format_func=lambda s: {"OFF": "AV – ingen regimeinngrep",
                    "SHADOW": "SKYGGE – vurder uten blokkering",
                    "LIVE": "LIVE – filtrer nye innganger"}[s],
                on_change=save_changed, args=("mode", mode_key))
            st.multiselect("Tillat nye handler i", STATES_V1 + ("UNKNOWN",),
                key=states_key, format_func=lambda s: "UKJENT / manglende data" if s == "UNKNOWN" else s,
                on_change=save_changed, args=("states", states_key))
            directions = strategy_entry_directions_v1(runtime_key)
            # For one-sided strategies with aligned regimes the direction
            # switch cannot change any permitted entry; keep the stored value.
            opposite = "BEAR" if directions == ("LONG",) else "BULL"
            if len(directions) == 2 or opposite in policy.allowed_states:
                st.checkbox("Krev medgang (LONG i BULL, SHORT i BEAR)",
                    key=trend_key, on_change=save_changed, args=("trend", trend_key),
                    help="SIDEWAYS og UKJENT styres av regimevalget. Gjelder bare nye innganger.")
            else:
                st.caption("Retningen bestemmes av strategien: " + directions[0] + "/FLAT.")
            st.caption("Endringer lagres umiddelbart. Lukk og reduser påvirkes aldri av regimefilteret.")

            count = load_regime_block_count_v1(instance_id=chosen.instance_id)
            st.metric("Regimeblokkerte ordreintensjoner", "Ukjent" if count is None else count)
            st.caption("Unike LIVE OPEN/ADD-vetoer siden telleren ble innført, ikke antall kontroller.")
            if policy.mode == "OFF":
                st.info("Regimefilter AV – ingen nye innganger blokkeres av dette filteret.")
            elif policy.mode == "SHADOW":
                st.info("SKYGGE – ingen nye innganger blokkeres; hypotetisk vurdering vises separat.")
            for direction in ("LONG", "SHORT"):
                result = decide_regime_entry_v1(policy, state=market_state, direction=direction)
                if direction not in directions:
                    st.write(f"**{direction}:** Ikke støttet av strategien")
                elif result.allow_new_exposure:
                    hypothetical = (" · SKYGGE ville blokkert" if policy.mode == "SHADOW"
                                    and not result.would_allow else "")
                    st.write(f"**{direction}:** ✅ Slippes gjennom regimefilteret{hypothetical}")
                else:
                    reason = ("UKJENT er ikke tillatt" if market_state == "UNKNOWN"
                              else f"{market_state} er ikke valgt" if market_state not in policy.allowed_states
                              else "Retningen går mot regimet")
                    st.write(f"**{direction}:** ⛔ Sperret – {reason}")
            st.caption("Viser regimefilter og strategiretning, ikke andre ordre- eller kapitalgrenser.")
        except Exception as exc:
            st.error("Regimefilter kan ikke lastes eller lagres: " + type(exc).__name__)

    st.subheader("Hva modellen har observert")
    if not evidence["observer_table_present"]:
        st.warning("Ingen observasjonstabell ennå. Status er ukjent, ikke 0 registrerte handler.")
    elif not evidence["profiles"]:
        st.info("Ingen state × strategi-observasjoner i valgt periode. Dette er ikke evidens for 0 tap.")
    else:
        st.dataframe([
            {
                "Strategi": row["strategy_key"], "Markedsprofil": row["state_key"],
                "Målinger": row["samples"], "5m-prisutfall ferdige": row["matured"],
                "Gjennomsnittlig neste 5m PRIS %":
                    None if row["mean_future_price_pct"] is None
                    else round(float(row["mean_future_price_pct"]), 4),
            }
            for row in evidence["profiles"]
        ], hide_index=True, width="stretch")
        st.caption(
            "Disse markedsprisene følger etter observert tilstand, men er verken Saxo-fill, "
            "strategiens resultat, netto P/L, spredningskostnad eller kausal lønnsomhet. "
            "Det finnes ennå ingen validert grense som setter rødt automatisk."
        )
    with st.expander("Aktive innstillinger og begrensninger", expanded=False):
        st.markdown(
            "- **Markedsvindu:** 61 sammenhengende ferdige 1m-barer (60 returer).\n"
            "- **Observatør:** ca. hvert 5. minutt; resultat merkes først etter fem fremtidige ferdige barer.\n"
            "- **Visuell datastatus:** ny 1m-bar ≤3 minutter, ny observasjon ≤10 minutter; "
            "kun UI-terskler.\n"
            "- **STOPP/KJØR:** standard KJØR, kun operatør kan sette STOPP. "
            "Verdien lagres per instans og aktiv strateginøkkel.\n"
            "- **Regimeport:** OFF/SHADOW/LIVE per instans; eksakt 30m/60m-prisretning. "
            "Ikke dokumentert lønnsomhet; aktiveres aldri automatisk."
        )

    with st.expander("🔬 Impulse Catcher → regime · statistisk prissammenheng", expanded=False):
        st.caption(
            "Lesende SHADOW-analyse: to uavhengige v1.1 LONG/SHORT-detektorer på samme "
            "ekte, tidligere lagrede Saxo bid/ask (maks 8s hull, 5s mottaksforsinkelse). "
            "Signalstyrke og antall impulser i "
            "foregående fem minutter måles FØR videre 5/15/30/60m kursbevegelse. "
            "Ingen nye Saxo-kall, ordre, filterendringer eller automatisk læring."
        )
        try:
            sources = tuple(s for s in list_subscribed_sources_v2(provider="saxo")
                            if ("TECH" in s.market_name.upper() or
                                "NAS" in s.market_name.upper()) and
                            str(s.provider_instrument_id).isdigit())
        except Exception as exc:
            st.warning("Kan ikke lese abonnementene: " + type(exc).__name__)
            sources = ()
        if sources:
            instrument = st.selectbox(
                "Eksakt abonnert instrument for korrelasjonsstudien", sources,
                format_func=lambda s: f"{s.market_name} · UIC {s.provider_instrument_id}",
                key="v3_impulse_regime_source",
            )
            research_hours = st.selectbox(
                "Lagret BBO-periode", (3, 6, 12, 24), index=1,
                format_func=lambda h: f"Siste {h} timer",
                key="v3_impulse_regime_hours",
            )
            research_key = (int(instrument.provider_instrument_id),
                            int(instrument.instrument_id), research_hours)
            if st.button("Mål impulsstyrke → videre prisbevegelse",
                         key="v3_impulse_regime_run"):
                try:
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(hours=research_hours)
                    with connect() as db:
                        rows = db.execute("""SELECT quote_at,received_at,bid,ask
                            FROM lsim_hyper_quotes_1s
                            WHERE provider_uic=? AND quote_at>=? AND quote_at<=?
                            ORDER BY quote_at LIMIT ?""", (
                            research_key[0], start.isoformat(), end.isoformat(),
                            MAX_RESEARCH_QUOTES + 1,
                        )).fetchall()
                    if len(rows) > MAX_RESEARCH_QUOTES:
                        raise ValueError("Over 80 000 BBO-rader; velg kortere intervall")
                    sessions = prepare_impulse_sessions_v1(tuple(dict(r) for r in rows))
                    pulses = detect_impulse_pulses_v1(sessions)
                    last_closed_open = end.replace(second=0, microsecond=0) - timedelta(minutes=1)
                    bars = CanonicalMarketBarStoreV2().load_instrument_range(
                        instrument_id=research_key[1],
                        start=start - timedelta(minutes=1),
                        end=last_closed_open,
                        limit=2000,
                    )
                    outcomes = score_impulse_regime_v1(pulses, bars, as_of=end)
                    cutoff = (pulses[int(len(pulses) * .7)].observed_at
                              if len(pulses) >= 4 else end)
                    groups = summarize_impulse_regime_v1(outcomes, cutoff=cutoff)
                    st.session_state["v3_impulse_regime_report"] = {
                        "key": research_key, "stamp": end.isoformat(),
                        "raw_quotes": len(rows),
                        "valid_quotes": sum(len(s) for s in sessions),
                        "sessions": len(sessions), "bars": len(bars),
                        "pulses": len(pulses), "outcomes": outcomes,
                        "groups": groups, "cutoff": cutoff.isoformat(),
                    }
                except ValueError as exc:
                    st.session_state.pop("v3_impulse_regime_report", None)
                    st.warning(str(exc))
                except Exception as exc:
                    st.session_state.pop("v3_impulse_regime_report", None)
                    st.warning("Målingen kunne ikke fullføres: " + type(exc).__name__)
            report = st.session_state.get("v3_impulse_regime_report")
            if report and report["key"] == research_key:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Lagrede BBO-rader", report["raw_quotes"])
                c2.metric("Godkjente BBO", report["valid_quotes"])
                c3.metric("Impulssignaler", report["pulses"])
                c4.metric("Ferdige 1m-barer", report["bars"])
                st.caption("Målt " + report["stamp"] + " · " +
                           str(report["sessions"]) + " sammenhengende BBO-sekvenser · " +
                           "70/30 kronologisk kalibrering/holdout, med avskåret " +
                           "overlappende treningsutfall.")
                if not report["pulses"]:
                    st.info("Ingen kvalifiserte impulser i gyldig BBO-dekning. "
                            "Dette sier ikke at markedet manglet impulser.")
                elif not report["groups"]:
                    st.warning("Impulser finnes, men ingen modne, sammenhengende "
                               "1m-prisforløp for valgt horisont.")
                else:
                    st.dataframe(list(report["groups"]), hide_index=True, width="stretch")
                    if not any(g["Del"] == "HOLDOUT" and g["Nok hendelser"]
                               for g in report["groups"]):
                        st.warning("Holdout har foreløpig færre enn 10 hendelser per gruppe. "
                                   "Ingen brukbar sannsynlighet er dokumentert.")
                st.caption(
                    "'Videre' betyr retningen fra første FULLFØRTE 1m-close etter "
                    "mottatt impuls til en senere fullført close. 'Maks pluss/minus' er "
                    "prisens mulige senere ytterpunkter, ikke oppnåelige fills. "
                    "Gjentas signaler tett, er observasjonene avhengige: antall "
                    "hendelser er IKKE antall uavhengige forsøk. "
                    "En impuls som fortsetter mens Impulse Catcher allerede holder "
                    "posisjon gir ikke et nytt kvalifisert INN-signal; denne første "
                    "versjonen teller derfor ikke alle underimpulser. "
                    "Sammenfall alene beviser ikke at impulsen forårsaket trenden. "
                    "Dette er markedsprisutvikling, IKKE reell eller simulert "
                    "MACD–Stoch-regimeavkastning. Neste fase kobler samme "
                    "signalhistorikk til tidsriktig PAPER-strategi og handelskostnader."
                )
        else:
            st.info("Ingen eksakt abonnert Saxo Tech100/NAS-kilde tilgjengelig.")

with module_tab:
    st.subheader("Modulkart · datakilder, behandling og utfall")
    st.caption(
        "Hver modul viser sin kontrakt og siste lagrede aktivitet. "
        "Et aktivt datasignal er ikke det samme som dokumentert strategiresultat."
    )
    rest_state = _fresh(evidence["rest_last"], 3)
    statuses = {
        "canonical": socket_state if evidence["streams"] else price_state,
        "profile": observer_state,
        "observer": observer_state,
        "impulse_bridge": {"symbol": "⚪", "label": "Manuelt, kun lagrede priser"},
        "filter": {"symbol": "🟢" if n_running else "⚪",
                   "label": f"{n_running}/{len(instances)} nylige runtime-heartbeats"},
        "rest": rest_state,
        "paper": {"symbol": "⚪", "label": "Startes manuelt"},
    }
    for module in MODULES_V1:
        state = statuses[module.key]
        with st.expander(f"{state['symbol']} {module.name} · {module.mode}", expanded=False):
            st.caption("Datastatus: " + state["label"])
            st.markdown(f"**Kilde:** {module.source}")
            st.markdown(f"**Behandling:** {module.operation}")
            st.markdown(f"**Utdata:** {module.output}")
            st.caption("Innstillinger / begrensning: " + module.settings)
            if module.key == "rest":
                st.caption(f"Observerte REST-kall siste 15 min: {evidence['rest_calls_15m']} · "
                           f"siste lagrede vindu {_stamp(evidence['rest_last'])}")
            elif module.key in ("profile", "observer"):
                st.caption(f"{evidence['total']} observasjoner, {evidence['matured']} "
                           f"modne prisutfall i visningsperioden")
            st.page_link(module.page, label="Åpne detaljside", icon="🔗")
