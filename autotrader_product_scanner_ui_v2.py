from __future__ import annotations

import streamlit as st

from autotrader_product_scanner_v2 import ProductScanResultV2, candidate_rows_for_ui_v2, scan_saxo_candidates_v2
from saxo_trading import SaxoTradingSafetyError, configured_trading_client
from trading_desk_products import MARKET_SEARCH_TERMS


_SCAN_KEY = "autotrader_product_scanner_v2"


def render_product_scanner_v2() -> None:
    st.subheader("AutoTrader Product Scanner")
    st.caption(
        "Read-only inspeksjon av Saxo-kandidater mot PriceGaugers separate AutoTrader-univers. "
        "Saxo kan foreslå produkter; bare eksplisitt verifiserte PG-identiteter kan senere bli execution-eligible."
    )

    try:
        trading = configured_trading_client()
    except SaxoTradingSafetyError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.warning(f"Kunne ikke initialisere Saxo for scanner: {exc}")
        return
    if trading is None:
        st.info("Koble til Saxo SIM først for å kjøre Product Scanner.")
        return

    left, right = st.columns([2, 1])
    market = left.selectbox("Marked for scanning", tuple(MARKET_SEARCH_TERMS), key="autotrader_scanner_market")
    limit = right.selectbox("Maks produkter", (10, 20, 40), index=1, key="autotrader_scanner_limit")

    if st.button("Scan kandidater", type="primary", key="autotrader_scan_products"):
        with st.spinner(f"Inspiserer opptil {limit} Saxo-kandidater for {market} …"):
            st.session_state[_SCAN_KEY] = scan_saxo_candidates_v2(
                trading.client,
                market=market,
                max_products=int(limit),
            )

    result = st.session_state.get(_SCAN_KEY)
    if not isinstance(result, ProductScanResultV2):
        st.info("Kjør en scan for å se pris/spread, minste størrelse og PG-eligibility.")
        return

    st.caption(
        f"{result.market}: Saxo fant {result.discovered} gearede kandidater · "
        f"inspiserte {result.inspected} · feil {result.failed}."
    )
    if not result.rows:
        st.warning("Ingen kandidater å vise.")
        return

    st.dataframe(
        candidate_rows_for_ui_v2(result.rows),
        use_container_width=True,
        hide_index=True,
        height=min(680, 110 + 35 * min(len(result.rows), 16)),
    )
    st.caption(
        "Spread beregnes direkte fra Saxo Bid/Ask når begge finnes. Den er ikke det samme som total round-trip-kostnad. "
        "Scanner setter aldri limited-loss, no-margin eller kostnadsverifisering automatisk; ukjent risiko forblir blokkert."
    )

    eligible = [row for row in result.rows if row.pg_eligible]
    in_universe = [row for row in result.rows if row.in_pg_universe]
    st.metric("Execution-eligible nå", len(eligible))
    if not in_universe:
        st.info(
            "PG-universet er foreløpig tomt. Dette er forventet: første oppgave er å identifisere kandidater med "
            "små gyldige ordrebeløp, lav spread og dokumentert limited-loss/no-margin før én eneste identitet tillates."
        )
