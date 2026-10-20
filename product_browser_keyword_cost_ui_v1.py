"""New prominent Product Browser search dialog for low-ticket metal/CFD research."""
from __future__ import annotations

import streamlit as st

from product_browser_keyword_cost_v1 import (
    FEE_OPTIONS,KeywordCostFilterV1,KeywordCostSearchResultV1,
    search_keyword_cost_products_v1,keyword_cost_rows_v1,
)
from saxo_low_friction_candidates_v2 import LowFrictionAccountV2
from saxo_provider import SaxoError,configured_client

_RESULT="pg_product_keyword_cost_results_v1"


def _accounts_for_costs(client):
    rows=client._get("port/v1/accounts/me").get("Data") or []
    if not isinstance(rows,list):
        return ()
    result=[]
    for row in rows:
        if (not isinstance(row,dict) or not row.get("AccountKey")
            or row.get("Active") is False):
            continue
        result.append(LowFrictionAccountV2(
            account_key=str(row["AccountKey"]),
            account_id=str(row.get("AccountId") or ""),
            currency=str(row.get("Currency") or ""),
        ))
    return tuple(result)


def render_keyword_cost_browser_v1() -> None:
    st.subheader("Søk etter handelsinstrument · pris og kurtasje")
    st.caption(
        "Skriv f.eks. Gold, XAUUSD, Silver eller XAGUSD. Vi søker på tvers av "
        "Saxos produktfamilier og inspiserer faktiske konto-/produktvilkår, "
        "markedspris, lovlig handelstrinn og kostnadsillustrasjoner."
    )
    st.info(
        "NOK-beløp er indikative bruttoeksponeringer (ikke kontantbehov/margin). "
        "Spread, finansiering, valutaveksling og kurtasje kommer i tillegg. "
        "Saxo-precheck og støtte i V3 LIVE kreves før AutoTrader kan handle produktet."
    )
    try:
        client=configured_client()
    except Exception as exc:
        st.error("Saxo-forbindelse kunne ikke åpnes: "+type(exc).__name__)
        return
    if client is None:
        st.warning("Koble til Saxo før instrumenter og kostnader kan kontrolleres.")
        return
    environment="LIVE" if "gateway.saxobank.com/openapi" in client.base_url.lower() else "SIM"
    try:
        accounts=_accounts_for_costs(client)
    except SaxoError as exc:
        accounts=()
        st.warning("Kontoer kan ikke leses fra Saxo; kurtasjemodell forblir ukjent: "+str(exc))
    st.caption(f"Datakilde: Saxo {environment} · lesende API-kall, ingen ordregivning.")
    with st.form("pg_product_keyword_cost_search_form"):
        a,b=st.columns([2.2,1.15])
        keyword=a.text_input(
            "Søkeord",
            value="Gold",
            placeholder="Gold, XAUUSD, Silver, XAGUSD, ETC ...",
            help="Saxos fritekstsøk; prøv også XAU/XAG hvis ordet gir for mange gruveselskaper.",
        )
        max_step=b.number_input(
            "Maks. minste handelstrinn (NOK)",
            min_value=1.0,max_value=1_000_000.0,value=500.0,step=100.0,
            help="Øvre grense for verdien av ett lovlig ordreinkrement, "
                 "ikke minste initialordre eller beløpet som kreves i margin.",
        )
        c,d=st.columns([1.3,1.8])
        model=c.selectbox(
            "Kurtasjemodell",FEE_OPTIONS,
            help="Basert på Saxos kostnadsillustrasjon ved 1x og 2x "
                 "minimumsstørrelse; kun en indikasjon på fast/variabel avgift.",
        )
        pick=d.selectbox(
            "Saxo-konto for kostnader",
            [None,*accounts],
            format_func=lambda x: (
                "Ingen konto – kurtasje ukjent"
                if x is None else f"…{x.account_id[-4:]} · {x.currency}"
            ),
            help="Velg en konto for kontoavhengig tilgang og kurtasje.",
        )
        e,f=st.columns(2)
        limit=e.selectbox("Antall produkter å inspisere",(6,12,20),index=1)
        include_unknown=f.checkbox(
            "Ta med ukjent NOK-handelstrinn",value=True,
            help="Uten verifisert IncrementSize eller FX vises produktet "
                 "som uavklart, ikke som billig eller dyrt.",
        )
        submitted=st.form_submit_button(
            "Søk og sammenlign",type="primary",use_container_width=True,
        )

    if submitted:
        try:
            options=KeywordCostFilterV1(
                keywords=keyword.strip(),max_increment_nok=float(max_step),
                fee_model=model,
                include_unknown_increment=include_unknown,
                account_key=pick.account_key if pick else None,
                max_inspections=int(limit),raw_results=250,
            )
            with st.spinner("Henter Saxo-produktdetaljer, kurser og kurtasje …"):
                st.session_state[_RESULT]=search_keyword_cost_products_v1(
                    client,options,account=pick,
                )
        except (ValueError,SaxoError) as exc:
            st.session_state.pop(_RESULT,None)
            st.error(f"Søk kunne ikke fullføres: {exc}")
        except Exception as exc:
            st.session_state.pop(_RESULT,None)
            st.error(f"Produktinspeksjon utilgjengelig: {type(exc).__name__}")

    result=st.session_state.get(_RESULT)
    if not isinstance(result,KeywordCostSearchResultV1):
        st.caption("Søket starter først når du trykker «Søk og sammenlign».")
        return

    if result.request.account_key is None:
        st.warning("Ingen Saxo-konto valgt. Kurtasje kan ikke klassifiseres sikkert.")
    st.caption(
        f"Søkeord: {result.request.keywords!r} · rå Saxo-treff: {result.raw_count} "
        f"(maks 250 per søk) · inspisert {result.inspected_count} av "
        f"{result.visible_catalog_count} · viser {len(result.products)} · "
        f"filtrert ut {result.omitted_filter_count}, ukjente "
        f"{result.omitted_unknown_count}."
    )
    if result.raw_count>=250:
        st.warning(
            "Saxo-søket traff 250-grensen. Dette er ikke et uttømmende "
            "metall-/produktunivers. Prøv et smalere søk, som XAUUSD eller XAGUSD."
        )
    if result.inspected_count<result.visible_catalog_count:
        st.caption(
            "Kurtasjesjekk er begrenset til de høyest rangerte treffene "
            "for å unngå mange trege Saxo-kall. Andre treff er ennå ikke vurdert."
        )
    if not result.products:
        st.warning(
            "Ingen inspiserte produkter møtte filteret. Øk grensen, "
            "ta med ukjente, endre kurtasjemodell eller søk mer presist."
        )
        return

    st.dataframe(keyword_cost_rows_v1(result.products),
                 hide_index=True,use_container_width=True,
                 height=min(640,95+35*len(result.products)))
    st.caption(
        "«Ingen eksplisitt kurtasje» gjelder kun kommisjonslinjene i "
        "Saxos illustrasjon, ikke spread/finansiering. Ingen modelltype er "
        "en kontraktsfestet klassifisering. NOK-tallene er ikke Saxo-precheck."
    )
    selected=st.selectbox(
        "Se bevis og begrensninger for produkt",
        result.products,
        format_func=lambda x:(
            f"{x.product.instrument.description or x.product.instrument.symbol}"
            f" · {x.product.instrument.asset_type} · UIC {x.product.instrument.uic}"
        ),
        key="pg_keyword_cost_detail_selected",
    )
    with st.expander("Dokumentasjon for valgt kandidat",expanded=True):
        st.write({
            "Saxo UIC":selected.product.instrument.uic,
            "AssetType":selected.product.instrument.asset_type,
            "Saxo pris":selected.price,
            "Prisvaluta":selected.price_currency,
            "Priskilde":selected.price_source,
            "NOK per valutaenhet":selected.fx_nok_per_unit,
            "FX-kilde":selected.fx_source,
            "Saxo min. trade size":selected.minimum_trade_size,
            "Saxo IncrementSize":selected.trade_step,
            "Saxo kontraktstørrelse":selected.contract_size,
            "Handelstrinn NOK, indikativt":selected.step_nok,
            "Minimum initialt NOK, indikativt":selected.minimum_initial_nok,
            "Kurtasje LONG":selected.long_commission,
            "Kurtasje SHORT":selected.short_commission,
            "Kurtasjevaluta":selected.commission_currency,
            "Totalkost LONG % (Saxo)":selected.total_cost_long_pct,
            "Totalkost SHORT % (Saxo)":selected.total_cost_short_pct,
            "Saxo-verifisering":selected.verification,
        })
        for note in selected.notes:
            st.caption("• "+note)
        st.warning(
            "Dette instrumentet er IKKE automatisk støttet av AutoTrader LIVE. "
            "Vi må verifisere Saxo minimumsordre i begge retninger, margin, "
            "spread/finansiering, fraksjonell lot og eksplisitt V3 instrument-onboarding."
        )


__all__=["render_keyword_cost_browser_v1"]
