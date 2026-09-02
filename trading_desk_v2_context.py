from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from database import connect
from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
from overview_v2_read_model import OverviewTechnicalV2, load_v2_overview_snapshots
from runtime_health_v2 import RuntimeHealthV2, load_runtime_health_v2
from tradingdesk_workspace_state_v2 import sync_tradingdesk_workspace_state_v2


@dataclass(frozen=True, slots=True)
class TradingDeskV2Health:
    status: str
    detail: str
    delay_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class TradingDeskV2Context:
    market_id: int
    market_name: str
    instrument: InstrumentSourceV2 | None
    forecast: OverviewTechnicalV2
    health: TradingDeskV2Health

    @property
    def instrument_id(self) -> int | None:
        return None if self.instrument is None else int(self.instrument.instrument_id)

    @property
    def instrument_label(self) -> str:
        if self.instrument is None:
            return "Ingen aktiv v2-instrumentkilde"
        source = self.instrument
        symbol = f" · {source.symbol}" if source.symbol else ""
        return f"{source.display_name}{symbol} · {source.provider}:{source.provider_instrument_id}"


def _health_for_view(
    view: OverviewTechnicalV2,
    persisted: RuntimeHealthV2 | None,
    *,
    instrument: InstrumentSourceV2 | None,
) -> TradingDeskV2Health:
    """Use runtime canonical feed health; never re-age a 30m TA snapshot."""
    delay = view.feed_delay_minutes
    if persisted is None:
        status = "NO_DATA"
        parts = ["ingen runtime-health registrert"]
    else:
        status = persisted.status
        parts = [persisted.detail or f"runtime {persisted.status}"]

    if delay is not None:
        parts.append(f"feed delay={delay:g}m")

    if instrument is None:
        status = "DEGRADED"
        parts.append("ingen aktiv/subscribed v2-instrumentkilde")

    return TradingDeskV2Health(
        status=status,
        detail=" · ".join(parts),
        delay_minutes=delay,
    )


def _sources_by_market() -> dict[str, tuple[InstrumentSourceV2, ...]]:
    grouped: dict[str, list[InstrumentSourceV2]] = {}
    for source in list_subscribed_sources_v2(provider="saxo"):
        grouped.setdefault(source.market_name, []).append(source)
    return {
        market: tuple(sorted(items, key=lambda item: (item.instrument_id, item.provider_instrument_id)))
        for market, items in grouped.items()
    }


def _active_market_ids() -> dict[str, int]:
    with connect() as db:
        rows = db.execute(
            "SELECT market_id, name FROM pg_v2_markets WHERE active = TRUE ORDER BY market_id"
        ).fetchall()
    result: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            market_id, name = row["market_id"], row["name"]
        else:
            try:
                market_id, name = row["market_id"], row["name"]
            except (TypeError, IndexError):
                market_id, name = row[0], row[1]
        result[str(name)] = int(market_id)
    return result


def load_trading_desk_contexts_v2(
    *,
    requested_horizons: Mapping[str, int] | None = None,
    interpreter_by_market: Mapping[str, bool] | None = None,
) -> dict[str, TradingDeskV2Context]:
    """Load TradingDesk's authoritative v2 market/workspace identity.

    Forecast/workspace and runtime health are v2-only. Instrument identity is
    resolved from the dynamic subscribed Saxo registry. Missing instrument identity
    is explicit and degraded; this function never guesses from legacy mappings.
    """
    views = load_v2_overview_snapshots(
        requested_horizons=requested_horizons,
        interpreter_by_market=interpreter_by_market,
    )
    market_ids = _active_market_ids()
    sources = _sources_by_market()
    try:
        health_by_market = {
            item.stage: item for item in load_runtime_health_v2(service="v2-technical-runtime")
        }
    except Exception:
        health_by_market = {}

    result: dict[str, TradingDeskV2Context] = {}
    for market, view in views.items():
        market_id = market_ids.get(market)
        if market_id is None:
            continue
        candidates = sources.get(market, ())
        instrument = candidates[-1] if candidates else None
        result[market] = TradingDeskV2Context(
            market_id=market_id,
            market_name=market,
            instrument=instrument,
            forecast=view,
            health=_health_for_view(view, health_by_market.get(market), instrument=instrument),
        )

    # Sync only read-model UI preferences. The workspace-state layer has no access
    # to strategy enrollment, OPEN/CLOSE arming, approvals or order authority.
    sync_tradingdesk_workspace_state_v2(result.keys())
    return result
