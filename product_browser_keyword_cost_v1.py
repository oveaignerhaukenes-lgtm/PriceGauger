"""Read-only Saxo keyword discovery with *verified-or-unknown* NOK/cost filters.

A product-search hit cannot certify minimum order, available margin, fee model
or permission to use V3 LIVE. Saxo details, quotes, FX reference and cost
illustration are evidence; missing/ambiguous parts never default to zero.
No Saxo order endpoint or product-onboarding write is used by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isclose, isfinite
import re
from typing import Any

from autotrader_product_explorer import (
    ProductSearchRequest, ProductSummary, ProductSearchResult,
    search_product_universe,load_product_details,
)
from saxo_low_friction_candidates_v2 import (
    LowFrictionAccountV2,_cost_illustration,_quote_fields,
)
from saxo_provider import SaxoClient, SaxoInstrument

FEE_ANY="Alle kostnadsmodeller"
FEE_ZERO="Ingen eksplisitt kurtasje"
FEE_VARIABLE="Prosentvis / ordrestørrelseavhengig"
FEE_FIXED="Fast / minstekurtasje"
FEE_MIXED="Både fast og variabel"
FEE_UNKNOWN="Ukjent"
FEE_OPTIONS=(FEE_ANY,FEE_ZERO,FEE_VARIABLE,FEE_FIXED,FEE_MIXED,FEE_UNKNOWN)
_FEE_TO_CLASS={
    FEE_ZERO:"ZERO",FEE_VARIABLE:"VARIABLE",FEE_FIXED:"FIXED",
    FEE_MIXED:"MIXED",FEE_UNKNOWN:"UNKNOWN",
}
MIN_QUOTE_CURRENCIES=("NOK","USD","EUR","GBP","SEK","DKK","CHF")


@dataclass(frozen=True,slots=True)
class KeywordCostFilterV1:
    keywords:str
    max_increment_nok:float|None=500.
    fee_model:str=FEE_ANY
    include_unknown_increment:bool=True
    account_key:str|None=None
    max_inspections:int=12
    raw_results:int=200

    def __post_init__(self)->None:
        if not self.keywords.strip() or len(self.keywords)>120:
            raise ValueError("Søkeord må være 1–120 tegn")
        if self.fee_model not in FEE_OPTIONS:
            raise ValueError("Ukjent kostnadsfilter")
        if self.max_increment_nok is not None and (
            not isfinite(float(self.max_increment_nok)) or
            self.max_increment_nok<=0
        ):
            raise ValueError("Maks handelstrinn i NOK må være positiv")
        if not 1<=self.max_inspections<=30:
            raise ValueError("Maks inspeksjoner må være 1–30")
        if not 1<=self.raw_results<=250:
            raise ValueError("Saxo-søk kan hente 1–250 treff")


@dataclass(frozen=True,slots=True)
class InspectedKeywordProductV1:
    product:ProductSummary
    price:float|None
    price_currency:str|None
    price_source:str
    fx_nok_per_unit:float|None
    fx_source:str
    trade_step:float|None
    minimum_trade_size:float|None
    minimum_order_value:float|None
    contract_size:float|None
    step_nok:float|None
    minimum_initial_nok:float|None
    long_commission:float|None
    short_commission:float|None
    commission_currency:str|None
    commission_model:str
    total_cost_long_pct:float|None
    total_cost_short_pct:float|None
    spread_pct:float|None
    verification:str
    notes:tuple[str,...]


@dataclass(frozen=True,slots=True)
class KeywordCostSearchResultV1:
    request:KeywordCostFilterV1
    products:tuple[InspectedKeywordProductV1,...]
    raw_count:int
    visible_catalog_count:int
    inspected_count:int
    omitted_unknown_count:int
    omitted_filter_count:int


def positive_number(value:Any)->float|None:
    try:
        number=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return number if isfinite(number) and number>0 else None


def nonnegative_number(value:Any)->float|None:
    try:
        number=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return number if isfinite(number) and number>=0 else None


def cost_model_from_two_sizes_v1(
    first:tuple[float|None,float|None],
    second:tuple[float|None,float|None],
)->str:
    """Compare actual absolute Saxo commissions for 1x versus 2x quantity.

    This is an observational classification (possibly a minimum fee), not
    the broker's contractual fee schedule or the cost of financing/spread.
    """
    vals=[nonnegative_number(v) for v in (*first,*second)]
    if any(x is None for x in vals):
        return "UNKNOWN"
    a,b,c,d=vals
    if a==b==c==d==0:
        return "ZERO"
    if not a>0 or not b>0:
        return "UNKNOWN"
    if any(x<y*0.99 for x,y in ((c,a),(d,b))):
        return "UNKNOWN"
    fixed=(isclose(c,a,rel_tol=.03,abs_tol=.005)
           and isclose(d,b,rel_tol=.03,abs_tol=.005))
    variable=(isclose(c,2*a,rel_tol=.05,abs_tol=.005)
              and isclose(d,2*b,rel_tol=.05,abs_tol=.005))
    if fixed:
        return "FIXED"
    if variable:
        return "VARIABLE"
    if a*1.02<c<2*a*.98 and b*1.02<d<2*b*.98:
        return "MIXED"
    return "UNKNOWN"


def candidate_rank_v1(product:ProductSummary,query:str)->tuple:
    text=f"{product.instrument.symbol} {product.instrument.description}".lower()
    keyword=query.lower().strip()
    # Search results for Gold can contain Goldman Sachs, miners, and bonds.
    # Exact metal/contract aliases are prioritized, without inventing identity.
    exact_alias={
        "gold":("xau","gold spot","gold futures","gold cfd"),
        "silver":("xag","silver spot","silver futures","silver cfd"),
    }
    matches=exact_alias.get(keyword,())
    relevant=(any(x in text for x in matches) if matches
              else keyword in text)
    derivatives=product.instrument.asset_type in {
        "FxSpot","CfdOnFutures","CfdOnIndex","CfdOnEtf","CfdOnEtc",
        "Etc","Etf","Etn","MiniFuture","ContractFutures",
    }
    return (not relevant,not product.is_tradable,not derivatives,
            product.instrument.description.lower(),product.instrument.uic)


def _price_currency(product:ProductSummary,details:dict)->str|None:
    cur=str(details.get("PriceCurrency") or details.get("CurrencyCode")
            or product.currency or "").upper().strip()
    symbol=re.sub(r"[^A-Z]","",product.instrument.symbol.upper())
    if product.instrument.asset_type=="FxSpot":
        # FxSpot instruments are usually priced in the *quote* currency,
        # while CurrencyCode may describe the base currency.
        if len(symbol)>=6 and symbol[:6] in {
            "XAUUSD","XAGUSD","XAUEUR","XAGEUR",
            "USDNOK","EURNOK","SEKNOK","DKKNOK",
            "EURUSD","GBPUSD","USDSEK","USDDKK",
        }:
            return symbol[3:6]
        return cur if details.get("PriceCurrency") else None
    return cur or None


def _fx_mid(client:SaxoClient,currency:str,cache:dict[str,tuple[float|None,str]])->tuple[float|None,str]:
    cur=currency.upper().strip()
    if cur=="NOK":
        return 1.,"NOK"
    if cur in cache:
        return cache[cur]
    # Only use exact Saxo FX spot identities, no implicit assumptions
    # such as 1 USD = 1 NOK and no cross via an unrelated metal quote.
    for cross,inverse in ((cur+"NOK",False),("NOK"+cur,True)):
        try:
            pairs=client.search_instruments(cross,asset_types="FxSpot")
            match=next((
                x for x in pairs
                if x.asset_type=="FxSpot" and
                re.sub(r"[^A-Z]","",x.symbol.upper()).startswith(cross)
            ),None)
            if match is None:
                continue
            price=client.info_price(match)
            bid,ask,_=_quote_fields(price)
            rate=(bid+ask)/2 if bid and ask and ask>=bid else None
            if rate is None:
                continue
            nok_per=1/rate if inverse else rate
            cache[cur]=(nok_per,"Saxo FxSpot indikativ "+cross)
            return cache[cur]
        except Exception:
            continue
    cache[cur]=(None,"Ingen verifisert "+cur+"/NOK-kurs")
    return cache[cur]


def _contract_multiplier(product:ProductSummary,details:dict)->tuple[float|None,str|None]:
    multiplier=positive_number(details.get("ContractSize"))
    typ=product.instrument.asset_type
    # Contract futures/options cannot be valued as one price tick or share
    # without a Saxo-verified multiplier.
    if typ in {"ContractFutures","FuturesOption","StockOption","StockIndexOption"}:
        if multiplier is None:
            return None,"Kontraktstørrelse mangler; NOK-verdi ukjent"
        return multiplier,None
    # Some CFDs also publish explicit contract sizes; prefer broker detail.
    return multiplier or 1.,None


def inspect_keyword_product_v1(client:SaxoClient,product:ProductSummary,*,
    account:LowFrictionAccountV2|None,
    fx_cache:dict[str,tuple[float|None,str]],
)->InspectedKeywordProductV1:
    notes=[]
    details={}
    try:
        details=load_product_details(client,product,
             account_key=account.account_key if account else None)
    except Exception as exc:
        notes.append("Saxo detalj utilgjengelig: "+type(exc).__name__)
    order=details.get("OrderSetting") if isinstance(details.get("OrderSetting"),dict) else {}
    minimum=positive_number(details.get("MinimumTradeSize") or details.get("MinimumLotSize")
                            or order.get("MinimumTradeSize"))
    increment=positive_number(details.get("IncrementSize") or order.get("IncrementSize"))
    order_value=positive_number(details.get("MinimumOrderValue") or order.get("MinOrderValue"))
    # MinimumTradeSize governs first order; IncrementSize is the *step*.
    # Do not label a missing IncrementSize as verified just because min
    # ticket size is known.
    step=increment
    quote_currency=_price_currency(product,details)
    multiplier,mult_note=_contract_multiplier(product,details)
    if mult_note:
        notes.append(mult_note)
    bid=ask=spread=None
    quote_price=None
    try:
        quote=client.info_price(product.instrument)
        bid,ask,spread=_quote_fields(quote)
        quote_price=(bid+ask)/2 if bid and ask and ask>=bid else ask or bid
    except Exception as exc:
        notes.append("Saxo pris utilgjengelig: "+type(exc).__name__)
    fx,fx_source=_fx_mid(client,quote_currency,fx_cache) if quote_currency else (
        None,"Prisvaluta ikke verifisert")
    unit=(quote_price*multiplier*fx if all(x is not None for x in
          (quote_price,multiplier,fx)) else None)
    step_nok=step*unit if step and unit else None
    # Minimum initial position must obey minimum trade size and legal step.
    initial_quantity=None
    if minimum and step:
        initial_quantity=ceil((minimum/step)-1e-9)*step
    elif minimum:
        initial_quantity=minimum
    initial_nok=initial_quantity*unit if initial_quantity and unit else None
    if order_value is not None:
        notes.append("Saxo MinOrderValue finnes, men valuta/krav må precheckes; "
                     "ikke inkludert som garantert minste kontantbehov")
    if step is None:
        notes.append("IncrementSize ikke bekreftet – NOK-trinn ukjent")
    if initial_nok is None:
        notes.append("Minste ordreverdi i NOK ikke verifisert")
    if not product.is_tradable:
        notes.append("Saxo merker produktet som ikke handlbart")

    long_fee=short_fee=long_pct=short_pct=None
    fee_currency=None
    fee_class="UNKNOWN"
    if quote_price and account:
        cost_amount=initial_quantity
        if cost_amount is None:
            notes.append("Saxo minimumsstørrelse mangler; avgiftsmodell ikke verifisert")
        else:
            (long_fee,short_fee,fee_currency,long_pct,short_pct,_zero,err)=_cost_illustration(
                client,account=account,instrument=product.instrument,
                amount=cost_amount,price=quote_price)
            if err:
                notes.append("Saxo kostnadsillustrasjon: "+err[:130])
            else:
                (double_long,double_short,_,_,_,_,err2)=_cost_illustration(
                    client,account=account,instrument=product.instrument,
                    amount=2*cost_amount,price=quote_price)
                if err2:
                    notes.append("Avgiftsmodell 2x størrelse kunne ikke testes")
                fee_class=cost_model_from_two_sizes_v1(
                    (long_fee,short_fee),(double_long,double_short))
                if fee_class=="UNKNOWN":
                    notes.append("Avgiftsmodell kan ikke avgjøres sikkert fra illustrasjonen")
    else:
        notes.append("Kostnadsmodell krever Saxo-konto, pris og verifisert minimumsstørrelse")
    return InspectedKeywordProductV1(
        product=product,price=quote_price,price_currency=quote_currency,
        price_source="Saxo infoPrice (indikativ)" if quote_price is not None else "Ukjent",
        fx_nok_per_unit=fx,fx_source=fx_source,
        trade_step=step,minimum_trade_size=minimum,
        minimum_order_value=order_value,contract_size=multiplier,
        step_nok=step_nok,minimum_initial_nok=initial_nok,
        long_commission=long_fee,short_commission=short_fee,
        commission_currency=fee_currency,commission_model=fee_class,
        total_cost_long_pct=long_pct,total_cost_short_pct=short_pct,
        spread_pct=spread,verification=(
            "INDIKATIV – precheck kreves"
            if step_nok is not None and fee_class!="UNKNOWN" else
            "UFULLSTENDIG – må verifiseres"
        ),notes=tuple(notes),
    )


def product_matches_filters_v1(row:InspectedKeywordProductV1,
                               options:KeywordCostFilterV1)->tuple[bool,str]:
    if options.max_increment_nok is not None:
        if row.step_nok is None:
            if not options.include_unknown_increment:
                return False,"unknown"
        elif row.step_nok>options.max_increment_nok:
            return False,"filter"
    if options.fee_model!=FEE_ANY and (
        row.commission_model!=_FEE_TO_CLASS[options.fee_model]
    ):
        return False,"filter"
    return True,"included"


def search_keyword_cost_products_v1(client:SaxoClient,
    options:KeywordCostFilterV1, *,
    account:LowFrictionAccountV2|None=None,
)->KeywordCostSearchResultV1:
    if options.account_key and (account is None or
                                account.account_key!=options.account_key):
        raise ValueError("Kostnadsforespørselen må bruke valgt Saxo AccountKey")
    broad=search_product_universe(client,ProductSearchRequest(
        keywords=options.keywords,top=options.raw_results,
        account_key=options.account_key))
    ranked=sorted(broad.products,key=lambda x:candidate_rank_v1(x,options.keywords))
    fx_cache:dict[str,tuple[float|None,str]]={}
    inspected=tuple(inspect_keyword_product_v1(client,row,account=account,
                  fx_cache=fx_cache) for row in ranked[:options.max_inspections])
    included=[]
    unknown=filtered=0
    for item in inspected:
        yes,reason=product_matches_filters_v1(item,options)
        if yes:
            included.append(item)
        elif reason=="unknown":
            unknown+=1
        else:
            filtered+=1
    included.sort(key=lambda x:(
        x.step_nok is None,
        x.step_nok if x.step_nok is not None else float("inf"),
        x.product.instrument.description.lower(),
    ))
    return KeywordCostSearchResultV1(
        request=options,products=tuple(included),raw_count=broad.raw_count,
        visible_catalog_count=len(broad.products),inspected_count=len(inspected),
        omitted_unknown_count=unknown,omitted_filter_count=filtered,
    )


def keyword_cost_rows_v1(rows:tuple[InspectedKeywordProductV1,...])->list[dict[str,object]]:
    labels={
        "ZERO":"Ingen eksplisitt","VARIABLE":"Prosent/variabel (indikasjon)",
        "FIXED":"Fast/minimum (indikasjon)","MIXED":"Blandet (indikasjon)",
        "UNKNOWN":"Ukjent",
    }
    return [{
        "Saxo-produkt":item.product.instrument.description or item.product.instrument.symbol,
        "Symbol":item.product.instrument.symbol,
        "Type":item.product.instrument.asset_type,
        "UIC":item.product.instrument.uic,
        "Trinn NOK (anslag)":round(item.step_nok,2) if item.step_nok is not None else None,
        "Min. ordre NOK (anslag)":round(item.minimum_initial_nok,2)
                                   if item.minimum_initial_nok is not None else None,
        "Handelstrinn (enheter)":item.trade_step,
        "Kurtasjemodell":labels[item.commission_model],
        "Kjøp kurtasje":item.long_commission,
        "Selg kurtasje":item.short_commission,
        "Kurtasjevaluta":item.commission_currency,
        "Spread %":round(item.spread_pct*100,4) if item.spread_pct is not None else None,
        "Valuta":item.price_currency,
        "Saxo-signal":item.verification,
        "Handlbar i Saxo-katalog":"Ja" if item.product.is_tradable else "Nei",
        "AutoTrader LIVE-godkjent":"Nei – discovery alene",
    } for item in rows]


__all__=[
    "KeywordCostFilterV1","KeywordCostSearchResultV1",
    "InspectedKeywordProductV1","FEE_OPTIONS","FEE_ANY","FEE_UNKNOWN",
    "FEE_ZERO","FEE_FIXED","FEE_VARIABLE","FEE_MIXED",
    "search_keyword_cost_products_v1","product_matches_filters_v1",
    "cost_model_from_two_sizes_v1","keyword_cost_rows_v1",
]
