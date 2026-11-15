"""Same-model BBO PAPER replay and broker-reconciled V3 event observer."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from statistics import median

import pandas as pd
import streamlit as st

from autotrader_impulse_catcher_v1 import ImpulseCatcherConfig
from autotrader_impulse_catcher_replay_v1 import (
    prepare_impulse_quotes,replay_impulse_catcher,summarize_impulse_replay,
)
from database import connect


st.set_page_config(page_title="Impulse Catcher · Tech100",layout="wide")
st.title("Tech100 · Impulse Catcher")
st.caption("LONG/FLAT på C · SHORT/FLAT på D · Stoch 2.1 på E (eksisterende kontroll)")
st.info(
    "PAPER bruker identisk kausal signalmodell som LIVE, men antatt fyll på NESTE "
    "ekte Saxo bid/ask-observasjon. Kontrolldataene er ikke ekte gjennomførte "
    "handler. Reelle priser, kurtasje, kursglipp og Saxo-ordrehistorikk må "
    "avstemmes før simulert profitt kan sammenlignes med faktisk P/L."
)
st.caption(
    "Startregler (hypoteser, ikke optimaliserte nivåer): 3/10s abnormal impuls, "
    "minst 9 indeks­poeng, minst 3× forhistorisk 3/10s-prisbevegelse, "
    "78 % retningskonsistens; 2s utmattelse/retrace eller umiddelbart stort "
    "mottrykk. Ingen strategi-dagsgrense. Account Loss Lock er separat valgfritt."
)
hours=st.selectbox("Samme kurshistorikk for begge strategier",(1,3,6,12),index=1)
max_rows=46000

if st.button("Kjør identisk PAPER-test for C og D",type="primary"):
    try:
        end=datetime.now(timezone.utc)
        start=end-timedelta(hours=hours)
        with connect() as db:
            raw=db.execute("""SELECT quote_at,received_at,bid,ask
                FROM lsim_hyper_quotes_1s WHERE provider_uic=4912
                AND quote_at>=? AND quote_at<=?
                ORDER BY quote_at LIMIT ?""",
                (start.isoformat(),end.isoformat(),max_rows+1)).fetchall()
        if len(raw)>max_rows:
            raise ValueError("Mer enn 46 000 observasjoner: velg et kortere tidsrom")
        quotes=prepare_impulse_quotes([dict(x) for x in raw])
        if len(quotes)<180:
            raise ValueError("For få ekte ferske BBO-observasjoner for en gyldig test")
        reports={side:replay_impulse_catcher(quotes,ImpulseCatcherConfig(side=side))
                 for side in ("LONG","SHORT")}
        st.session_state["impulse_catcher_replay"]={
            "stamp":end.isoformat(),"hours":hours,"quotes":len(quotes),
            "first":quotes[0].at.isoformat(),"last":quotes[-1].at.isoformat(),
            "reports":reports,"source_quotes":quotes,
        }
    except (ValueError,TypeError,OverflowError) as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error("PAPER-data kunne ikke leses: "+type(exc).__name__)

report=st.session_state.get("impulse_catcher_replay")
if report:
    if report["hours"]!=hours:
        st.warning("Observasjonsperioden er endret. Kjør ny test.")
    else:
        st.caption(f"Sist målt {report['stamp']}; {report['quotes']:,} godkjente BBO-prøver "
                   f"fra {report['first']} til {report['last']}.")
        cols=st.columns(2)
        for idx,side in enumerate(("LONG","SHORT")):
            r=report["reports"][side]
            m=summarize_impulse_replay(r)
            with cols[idx]:
                st.subheader("C · LONG" if side=="LONG" else "D · SHORT")
                c1,c2,c3=st.columns(3)
                c1.metric("PAPER-signaler",m["signals"])
                c2.metric("Lukkede PAPER-handler",m["completed"])
                c3.metric("Treffandel",f"{m['win_pct']:.1f}%" if m["win_pct"] is not None else "–")
                st.metric("Sum indekspoeng etter simulert bid/ask",
                          f"{m['net_index_points']:+.2f}")
                st.caption(f"Median per handel: {m['median_points']} poeng; "
                           f"entry-lag: {m['median_entry_delay_s']}s; "
                           f"exit-lag: {m['median_exit_delay_s']}s. "
                           f"Ufylt inngang/utgang: {m['unfilled_entries']}/"
                           f"{m['unfilled_exits']}; fortsatt åpen: {m['unfinished_positions']}.")
                if r.trades:
                    st.dataframe(pd.DataFrame([{
                        "Signal (UTC)":t.signal_at.isoformat(),
                        "PAPER entry":t.filled_at.isoformat(),
                        "PAPER exit":t.exited_at.isoformat(),
                        "P/L poeng":round(t.gross_points,2),
                        "MFE poeng":round(t.max_favorable_points,2),
                        "MAE poeng":round(t.max_adverse_points,2),
                        "Gevinst gitt tilbake":round(t.max_favorable_points-t.gross_points,2),
                    } for t in r.trades[-60:]]),hide_index=True,use_container_width=True)

        st.subheader("Daglig kalibrering · kun forslag")
        st.caption(
            "Velger nivåer på første 70 % av observerte quotes og vurderer de "
            "samme nivåene på siste 30 %. Dette er fremdeles en retrospektiv "
            "test, ikke bevis på morgendagens treff. LIVE-konfigurasjon endres aldri her."
        )
        if st.button("Sammenlign alternative impulsgrenser (7/9/12 poeng)"):
            quotes=report["source_quotes"]
            cutoff=max(150,int(0.7*len(quotes)))
            # Feed both segments a 150-quote warmup; only score fully
            # completed trades whose entry and exit are inside the segment.
            trials=[]
            for side in ("LONG","SHORT"):
                for threshold in (7.,9.,12.):
                    cfg=replace(ImpulseCatcherConfig(side=side),min_impulse_points=threshold)
                    train=replay_impulse_catcher(quotes[:cutoff],cfg)
                    holdout=replay_impulse_catcher(quotes[max(0,cutoff-150):],cfg)
                    valid=tuple(t for t in holdout.trades if
                                t.signal_at>=quotes[cutoff].at)
                    trials.append({
                        "Side":side,"Terskel":threshold,
                        "Kalibrering (handler)":len(train.trades),
                        "Kalibrering (poeng/handel)":round(train.net_points/len(train.trades),2)
                            if train.trades else None,
                        "Holdout (handler)":len(valid),
                        "Holdout (poeng/handel)":round(sum(t.gross_points for t in valid)/len(valid),2)
                            if valid else None,
                        "Foreløpig nok data":len(train.trades)>=30 and len(valid)>=10,
                    })
            st.session_state["impulse_catcher_trials"]=trials
        trials=st.session_state.get("impulse_catcher_trials")
        if trials:
            st.dataframe(pd.DataFrame(trials),hide_index=True,use_container_width=True)
            if any(t["Foreløpig nok data"] for t in trials):
                st.info("Minsteutvalget er nådd for noen varianter. Velg eventuell "
                        "ny versjon først etter kontroll mot en helt ny handelsdag.")
            else:
                st.warning("Ingen variant har foreløpig 30 fullførte handler i "
                           "kalibrering og 10 i holdout. Ingen optimaliseringsbeslutning.")

st.subheader("LIVE-observasjoner · signal vs. Saxo-rekonsiliering")
try:
    with connect() as db:
        instances=db.execute("""SELECT i.instance_id,i.account_id,i.uic,i.asset_type,
            c.strategy_key,c.modifiers_json FROM autotrader_v3_engine_instances i
            JOIN autotrader_v3_config c ON c.trader_id=i.instance_id
            WHERE i.enabled=TRUE AND c.strategy_key IN (?,?)""",
            ("impulse-catcher-long-v1","impulse-catcher-short-v1")).fetchall()
        try:
            since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
            logs=db.execute("""SELECT trader_id,strategy_key,quote_at,direction,
                action,trigger_points,baseline_points,window_seconds
                FROM pg_v3_impulse_signal_events
                WHERE quote_at>=? ORDER BY quote_at DESC LIMIT 250""",
                (since,)).fetchall()
            full_count=int(db.execute("""SELECT COUNT(*) AS n
                FROM pg_v3_impulse_signal_events WHERE quote_at>=?""",
                (since,)).fetchone()["n"])
            daily=db.execute("""SELECT SUBSTR(quote_at,1,10) AS utc_day,
                direction,action,COUNT(*) AS n FROM pg_v3_impulse_signal_events
                WHERE quote_at>=? GROUP BY SUBSTR(quote_at,1,10),direction,action
                ORDER BY utc_day,direction,action""",(since,)).fetchall()
        except Exception:
            logs=[]
            daily=[]
            full_count=0
        executions=[]
        for inst in instances:
            try:
                rows=db.execute("""SELECT executed_at,action,side,amount
                    FROM autotrader_v3_execution_events
                    WHERE instance_id=? AND account_id=? AND uic=? AND asset_type=?
                      AND executed_at>=?
                    ORDER BY executed_at DESC LIMIT 100""",(
                    inst["instance_id"],inst["account_id"],inst["uic"],inst["asset_type"],
                    datetime.now(timezone.utc)-timedelta(days=7))).fetchall()
                executions.extend(dict(r)|{"instance":str(inst["instance_id"])[:8]} for r in rows)
            except Exception:
                pass
    col1,col2,col3=st.columns(3)
    col1.metric("Registrerte impulsinstanser",len(instances))
    col2.metric("LIVE-modellsignaler (7d)",full_count)
    col3.metric("Saxo-rekonsilierte V3-hendelser (7d)",len(executions))
    if logs:
        st.caption("Modellsignal betyr IKKE ordrefyll. UIC, konto-eierskap, "
                   "posisjon, margin og låser avgjør om V3 utfører.")
        st.dataframe(pd.DataFrame([dict(row)|{"trader_id":str(row["trader_id"])[:8]}
                                   for row in logs]),hide_index=True,use_container_width=True)
        st.dataframe(pd.DataFrame(executions),hide_index=True,use_container_width=True)
        st.caption("Daglig frekvens (deterministisk observasjon, ingen automatisk tilpasning)")
        st.dataframe(pd.DataFrame([{"Dag (UTC)":x["utc_day"],
                                   "Retning":x["direction"],"Handling":x["action"],
                                   "Antall":x["n"]} for x in daily]),
                     hide_index=True,use_container_width=True)
    elif instances:
        st.caption("Impulsinstanser finnes, men ingen signaler er logget i siste 7 dager.")
    else:
        st.caption("Ingen nye impulsinstanser er registrert. Dette panelet armer "
                   "ikke kontoer og endrer ikke eksisterende Tech100-E.")
except Exception as exc:
    st.caption("LIVE-logg utilgjengelig inntil instanser/tabell er etablert: "
               +type(exc).__name__)
