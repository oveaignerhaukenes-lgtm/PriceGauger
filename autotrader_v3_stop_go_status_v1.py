"""Fleet stop/go light shows the actual persistent V3 order veto mode.

This is a trading-permission light, not a profitability estimate. The worker
guards OPEN/ADD both at plan time and immediately before broker submission.
"""
from __future__ import annotations

from dataclasses import dataclass

from autotrader_v3_trade_filter_v1 import load_trade_filter_v1


@dataclass(frozen=True, slots=True)
class V3StopGoLightV1:
    symbol: str
    label: str
    detail: str


UNKNOWN = V3StopGoLightV1("⚪", "UKJENT", "Filterstatus kan ikke bekreftes")
NOT_ARMED = V3StopGoLightV1("⚪", "AV", "LIVE er ikke armert")
GO = V3StopGoLightV1("🟢", "KJØR", "Ingen filterblokkering; øvrige handelsvern gjelder")
STOP = V3StopGoLightV1("🔴", "STOPP", "Nye posisjoner/økninger blokkert; risikoreduksjon tillatt")


def load_v3_stop_go_lights_v1(
    instances: tuple[tuple[str, str, bool], ...], *,
    db_path: str = "pricegauger.db",
) -> dict[str, V3StopGoLightV1]:
    """No market inference. Match exact strategy and arming."""
    lights={}
    for instance_id,strategy_key,live_armed in instances:
        if not live_armed:
            lights[instance_id]=NOT_ARMED
            continue
        try:
            state=load_trade_filter_v1(instance_id=instance_id,
                strategy_key=strategy_key,db_path=db_path)
            lights[instance_id]=GO if state.mode=="GO" else STOP
        except Exception:
            lights[instance_id]=UNKNOWN
    return lights


__all__=["V3StopGoLightV1","load_v3_stop_go_lights_v1"]
