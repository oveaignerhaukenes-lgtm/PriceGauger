"""Stable, explicitly unit-labelled fleet P/L view based on exact Saxo boundary.

The broker may provide ProfitLossOnTradeInBaseCurrency (account-currency
amount), a dynamic P/L field whose currency is not asserted, or only
price*position inference. Only explicitly account-base-currency figures can
be compared in the money chart. They are NOT percentages, realized profits,
or historical strategy returns. HTML bars are static DOM, not scroll-evicted
Vega canvas, and values are escaped before inclusion in the page.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import isfinite
from typing import Mapping, Sequence

from autotrader_v3_reset_on_loss_v1 import open_pnl_from_net_position_v3


@dataclass(frozen=True)
class FleetPnlValueV1:
    amount: float
    currency: str | None
    unit_verified: bool

    @property
    def unit_label(self) -> str:
        return self.currency if self.unit_verified and self.currency else "enhet uavklart"


def account_currency_v1(account_rows:Sequence[Mapping],account_id:str)->str|None:
    matching=[
        str(row.get("Currency") or "").strip().upper()
        for row in account_rows if isinstance(row,Mapping)
        and str(row.get("AccountId") or "").strip()==str(account_id).strip()
    ]
    if len(matching)!=1:
        return None
    currency=matching[0]
    return currency if len(currency)==3 and currency.isascii() and currency.isalpha() else None


def broker_open_pnl_for_fleet_v1(*,net_position_rows,account_currency):
    """Never assign account-currency units to a fallback/inferred P/L amount."""
    if not isinstance(net_position_rows,(tuple,list)):
        raise ValueError("account net position rows unavailable")
    if len(net_position_rows)>1:
        raise ValueError("ambiguous exact account net position")
    currency=str(account_currency or "").strip().upper()
    verified_currency=(len(currency)==3 and currency.isascii() and currency.isalpha())
    if not net_position_rows:
        return FleetPnlValueV1(0.,currency if verified_currency else None,
                               verified_currency)
    row=net_position_rows[0]
    amount=open_pnl_from_net_position_v3(row)
    if not isfinite(amount):
        raise ValueError("nonfinite P/L")
    view=row.get("NetPositionView") if isinstance(row,dict) else None
    # The exact Saxo named field has base-currency units. Inferred
    # price*lot and dynamic fields do NOT prove unit denomination.
    base_field=isinstance(view,dict) and view.get("ProfitLossOnTradeInBaseCurrency") is not None
    valid=bool(base_field and verified_currency)
    return FleetPnlValueV1(float(amount),currency if valid else None,valid)


def _money(value:float,currency:str)->str:
    sign="+" if value>0 else "−" if value<0 else ""
    return f"{sign}{abs(value):,.2f} {currency}".replace(","," ")


def render_stable_fleet_pnl_html_v1(rows:Sequence[Mapping]) -> str:
    """Generate a simple static signed horizontal bar visualization for mobile.

    Normalize only within same verified currency, with a persistent centre
    line and full labels that wrap naturally. Do not aggregate across FX.
    All user/broker account strings are HTML-escaped.
    """
    valid=[]
    for row in rows:
        value=float(row["amount"])
        currency=str(row["currency"]).strip().upper()
        label=str(row["label"])
        if not isfinite(value):
            continue
        if not (len(currency)==3 and currency.isascii() and currency.isalpha()):
            continue
        valid.append((label,value,currency))
    if not valid:
        return ""
    currencies=sorted({c for _,_,c in valid})
    chunks=['<div class="pg-v3-pnl-plot" aria-label="Åpen Saxo P/L i kontoens valuta">']
    chunks.append('<style>'
      '.pg-v3-pnl-plot{width:100%;font-size:.91rem}'
      '.pg-v3-pnl-plot .pgroup{margin:.75rem 0 1.15rem}'
      '.pg-v3-pnl-plot .pcurrency{font-size:.82rem;opacity:.8;font-weight:600;margin-bottom:.6rem}'
      '.pg-v3-pnl-plot .prow{margin:.35rem 0 .9rem}'
      '.pg-v3-pnl-plot .plabel{overflow-wrap:anywhere;line-height:1.25;margin-bottom:.25rem}'
      '.pg-v3-pnl-plot .pvalue{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:650}'
      '.pg-v3-pnl-plot .ptop{display:flex;justify-content:space-between;gap:.7rem;align-items:start}'
      '.pg-v3-pnl-plot .pbar{display:grid;grid-template-columns:1fr 1fr;'
      'background:rgba(126,139,164,.10);min-height:15px;border-radius:4px;overflow:hidden}'
      '.pg-v3-pnl-plot .pleft{border-right:1px solid rgba(145,156,170,.7);'
      'display:flex;justify-content:flex-end}'
      '.pg-v3-pnl-plot .pright{display:flex;justify-content:flex-start}'
      '.pg-v3-pnl-plot .pneg{background:#d66b72;height:15px;border-radius:3px 0 0 3px}'
      '.pg-v3-pnl-plot .ppos{background:#3baf91;height:15px;border-radius:0 3px 3px 0}'
      '.pg-v3-pnl-plot .pzero{font-size:.78rem;opacity:.7;margin-top:.3rem}'
      '</style>')
    for currency in currencies:
        series=[(name,value) for name,value,ccy in valid if ccy==currency]
        bound=max((abs(v) for _,v in series),default=0.) or 1.
        chunks.append(f'<section class="pgroup"><div class="pcurrency">Åpen P/L · {escape(currency)}</div>')
        for name,value in series:
            width=(100.*abs(value)/bound) if value else 0.
            value_str=escape(_money(value,currency))
            # Need two full 50% halves: negative goes left of centre.
            neg=(f'<div class="pneg" style="width:{width:.2f}%"></div>' if value<0 else '')
            pos=(f'<div class="ppos" style="width:{width:.2f}%"></div>' if value>0 else '')
            chunks.append(
                '<div class="prow">'
                f'<div class="ptop"><span class="plabel">{escape(name)}</span>'
                f'<span class="pvalue">{value_str}</span></div>'
                f'<div class="pbar" role="img" aria-label="{escape(name,quote=True)}: {escape(_money(value,currency),quote=True)}">'
                f'<div class="pleft">{neg}</div><div class="pright">{pos}</div></div></div>')
        chunks.append('</section>')
    chunks.append('</div>')
    return ''.join(chunks)
