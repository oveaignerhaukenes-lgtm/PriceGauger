from __future__ import annotations

import streamlit as st

from autotrader_index_training_scanner_ui_v2 import render_index_training_scanner_v2
from autotrader_margin_precheck_ui_v2 import render_margin_precheck_v2
from autotrader_product_explorer_ui import render_saxo_product_explorer
from autotrader_product_scanner_ui_v2 import render_product_scanner_v2
from build_info import render_build_badge


st.set_page_config(page_title="Produktbrowser · PriceGauger", page_icon="🧭", layout="wide")
render_build_badge()
st.title("Produktbrowser")
st.caption(
    "Finn Saxo-instrumenter etter økonomiske egenskaper fremfor produktnavn. Produktfamilie (CFD, ETF, Turbo, Mini, FX osv.) "
    "er metadata; PriceGauger prioriterer kostnad, minste eksponering, margin, gearing/risikoramme, LONG/SHORT-egenskaper og likviditet."
)

st.info(
    "Browseren er discovery/inspection. Den kan lese LIVE-katalog, priser, kostnader og precheck-data, men gir ikke et produkt "
    "execution-authority. AutoTrader kan senere bare bruke eksakte identiteter som er eksplisitt tatt inn i PG Product Universe."
)

training_tab, market_tab, margin_tab, catalog_tab = st.tabs(
    (
        "Lavfriksjon / trening",
        "Marked og egenskaper",
        "Margin-precheck",
        "Saxo-katalog · avansert",
    )
)

with training_tab:
    st.markdown("### Finn et egnet execution-instrument")
    st.caption(
        "Start med finansielle egenskaper: lav spread, null/lav fast kurtasje og liten mulig posisjon. "
        "Index-CFD-universet er første konkrete treningsunivers fordi flere Saxo Index Trackers kan handles fraksjonelt."
    )
    render_index_training_scanner_v2()

with market_tab:
    st.markdown("### Kartlegg et underliggende marked")
    st.caption(
        "Bruk når du allerede vil følge et bestemt marked. PG kartlegger først Saxos faktiske instrumenter og vurderer deretter "
        "kostnads-/marginegenskaper; AssetType er ikke hovedsorteringen."
    )
    render_product_scanner_v2()

with margin_tab:
    st.markdown("### Faktisk kapital- og marginbehov")
    st.caption(
        "Saxo precheck er autoritativ for hva minste ordre faktisk krever på kontoen. Denne fanen bruker siste lavfriksjon-shortlist "
        "fra markedskartleggingen og sender ingen ordre."
    )
    render_margin_precheck_v2()

with catalog_tab:
    st.markdown("### Rå Saxo-katalog")
    st.caption(
        "Avansert katalogsøk når du kjenner navn, symbol eller tradisjonell produktkategori. Dette er sekundært til den "
        "egenskapsbaserte browseren over."
    )
    render_saxo_product_explorer()
