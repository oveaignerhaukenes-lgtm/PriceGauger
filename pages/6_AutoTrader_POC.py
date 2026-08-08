from __future__ import annotations

import json

import streamlit as st

from build_info import render_build_badge
from saxo_auth import configured_oauth_client
from saxo_provider import SaxoError, configured_instruments
from saxo_trading import SaxoOrderRequest, SaxoTradingSafetyError, configured_trading_client


st.set_page_config(page_title="AutoTrader POC · PriceGauger", page_icon="🧪", layout="wide")
render_build_badge()
st.title("AutoTrader · proof of concept")
st.caption("Isolert Saxo SIM-test. Ingen kobling til PriceGauger-analyser eller worker.")

st.warning(
    "Denne siden er hardlåst til Saxo SIM. Den kan ikke sende ordre til LIVE-miljøet. "
    "Ordre sendes bare etter eksplisitt manuell bekreftelse."
)

try:
    oauth = configured_oauth_client()
    auth_status = oauth.status() if oauth is not None else {"connected": False, "status": "NOT_CONFIGURED"}
except Exception as exc:
    oauth = None
    auth_status = {"connected": False, "status": f"STATUS_ERROR: {exc}"}

status_col, env_col = st.columns(2)
status_col.metric("Saxo-tilkobling", "Tilkoblet" if auth_status.get("connected") else "Ikke tilkoblet")
env_col.metric("Miljø", str(auth_status.get("environment") or "ukjent").upper())
st.caption(str(auth_status.get("status") or "UKJENT").replace("_", " "))

if not auth_status.get("connected"):
    st.info("Koble til Saxo fra Saxo-siden først. AutoTrader bruker den samme delte OAuth-tokenen.")
    st.page_link("pages/1_Saxo_OpenAPI.py", label="Åpne Saxo-tilkobling", icon="🔌")
    st.stop()

try:
    trading = configured_trading_client()
except SaxoTradingSafetyError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:
    st.error(f"Kunne ikke initialisere Saxo SIM trading-klient: {exc}")
    st.stop()

if trading is None:
    st.error("Saxo-klienten er ikke konfigurert.")
    st.stop()

try:
    accounts = tuple(account for account in trading.accounts() if account.active)
except Exception as exc:
    st.error(f"Kunne ikke hente Saxo-kontoer: {exc}")
    st.stop()

if not accounts:
    st.error("Fant ingen aktive Saxo SIM-kontoer.")
    st.stop()

instruments = configured_instruments()
if not instruments:
    st.error("Ingen Saxo-instrumenter er konfigurert i config/saxo_instruments.json.")
    st.stop()

st.subheader("1. Bygg en manuell SIM-ordre")
account = st.selectbox(
    "Konto",
    accounts,
    format_func=lambda value: f"{value.account_id} · {value.currency or 'valuta ukjent'}",
)
asset_name = st.selectbox("Instrument", tuple(instruments.keys()))
instrument = instruments[asset_name]
side = st.radio("Retning", ("Buy", "Sell"), horizontal=True)
amount = st.number_input("Antall", min_value=0.000001, value=1.0, step=1.0, format="%.6f")

st.caption(
    f"{asset_name}: {instrument.symbol or instrument.description or 'ukjent symbol'} · "
    f"UIC {instrument.uic} · {instrument.asset_type}"
)

order = SaxoOrderRequest(
    account_key=account.account_key,
    instrument=instrument,
    amount=float(amount),
    buy_sell=side,
)
request_key = json.dumps(order.payload(), sort_keys=True)

if st.session_state.get("autotrader_precheck_key") != request_key:
    st.session_state.pop("autotrader_precheck", None)
    st.session_state.pop("autotrader_order_result", None)

st.subheader("2. Pre-check hos Saxo")
if st.button("Kjør Saxo pre-check", type="primary"):
    try:
        with st.spinner("Validerer ordren mot Saxo SIM …"):
            result = trading.precheck(order)
        st.session_state["autotrader_precheck"] = result
        st.session_state["autotrader_precheck_key"] = request_key
        st.session_state.pop("autotrader_order_result", None)
    except (SaxoError, ValueError, SaxoTradingSafetyError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Pre-check feilet: {exc}")

precheck = st.session_state.get("autotrader_precheck")
if precheck is not None and st.session_state.get("autotrader_precheck_key") == request_key:
    precheck_result = str(precheck.get("PreCheckResult") or "UKJENT")
    if precheck_result.lower() == "ok":
        st.success("Saxo pre-check: OK")
    else:
        st.warning(f"Saxo pre-check: {precheck_result}")
    with st.expander("Se pre-check-respons"):
        st.json(precheck)

    disclaimers = precheck.get("PreTradeDisclaimers")
    if disclaimers:
        st.error(
            "Saxo krever pre-trade disclaimer for denne ordren. POC-en sender ikke ordre før "
            "disclaimer-flyten er implementert."
        )
        st.stop()

    if precheck_result.lower() != "ok":
        st.stop()

    st.subheader("3. Send SIM-ordre")
    st.write(
        f"Klar til å sende **{side} {amount:g} × {asset_name}** som en manuell market/day-order på SIM-kontoen."
    )
    confirmed = st.checkbox("Jeg bekrefter at dette er en Saxo SIM-testordre")
    if st.button("Send SIM-ordre", disabled=not confirmed):
        try:
            with st.spinner("Sender ordre til Saxo SIM …"):
                result = trading.place_order(order, confirm_sim=True)
            st.session_state["autotrader_order_result"] = result
        except (SaxoError, ValueError, SaxoTradingSafetyError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Ordren feilet: {exc}")

order_result = st.session_state.get("autotrader_order_result")
if order_result is not None:
    order_id = order_result.get("OrderId") or order_result.get("OrderIds") or "ukjent"
    st.success(f"Saxo SIM svarte på ordreforespørselen. OrderId: {order_id}")
    with st.expander("Se Saxo-ordrerespons"):
        st.json(order_result)
