from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd

from gdelt_ingestion import GdeltCandidateRecord
from saxo_provider import SaxoClient, SaxoError, SaxoInstrument, select_contract_for_timestamp

BRENT_CONTINUOUS_UIC = 4055


@dataclass(frozen=True, slots=True)
class SaxoAnalogueReaction:
    candidate_event_id: str
    published_at: str
    contract_symbol: str
    contract_uic: int | None
    price_at_event: float | None
    return_15m_pct: float | None
    return_1h_pct: float | None
    return_4h_pct: float | None
    return_24h_pct: float | None
    mfe_4h_pct: float | None
    mae_4h_pct: float | None
    status: str
    error: str = ""

    def to_record(self) -> dict:
        return asdict(self)


def _timestamp(candidate: GdeltCandidateRecord) -> pd.Timestamp | None:
    value = candidate.published_at or ""
    if not value:
        return None
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _close_at_or_after(frame: pd.DataFrame, target: pd.Timestamp) -> float | None:
    rows = frame[frame["timestamp"] >= target]
    if rows.empty:
        return None
    return float(rows.iloc[0]["close"])


def _return_pct(entry: float | None, exit_price: float | None) -> float | None:
    if entry is None or exit_price is None or entry == 0:
        return None
    return ((exit_price / entry) - 1.0) * 100.0


def measure_candidate_reaction(
    candidate: GdeltCandidateRecord,
    *,
    client: SaxoClient,
    contracts: list[SaxoInstrument],
    horizon_minutes: int = 5,
) -> SaxoAnalogueReaction:
    event_time = _timestamp(candidate)
    if event_time is None:
        return SaxoAnalogueReaction(
            candidate_event_id=candidate.event_id,
            published_at="",
            contract_symbol="",
            contract_uic=None,
            price_at_event=None,
            return_15m_pct=None,
            return_1h_pct=None,
            return_4h_pct=None,
            return_24h_pct=None,
            mfe_4h_pct=None,
            mae_4h_pct=None,
            status="TIMESTAMP_MISSING",
        )

    try:
        contract = select_contract_for_timestamp(contracts, event_time)
        frame = client.chart(
            contract,
            horizon_minutes=horizon_minutes,
            count=360,
            time=event_time,
            mode="From",
        )
        if frame.empty:
            raise SaxoError("ingen chartbarer for hendelsen", status="PRICE_UNAVAILABLE")

        entry = _close_at_or_after(frame, event_time)
        p15 = _close_at_or_after(frame, event_time + pd.Timedelta(minutes=15))
        p1h = _close_at_or_after(frame, event_time + pd.Timedelta(hours=1))
        p4h = _close_at_or_after(frame, event_time + pd.Timedelta(hours=4))
        p24h = _close_at_or_after(frame, event_time + pd.Timedelta(hours=24))

        mfe = mae = None
        if entry is not None:
            window = frame[(frame["timestamp"] >= event_time) & (frame["timestamp"] <= event_time + pd.Timedelta(hours=4))]
            if not window.empty:
                high = float(window["high"].max()) if "high" in window else float(window["close"].max())
                low = float(window["low"].min()) if "low" in window else float(window["close"].min())
                mfe = ((high / entry) - 1.0) * 100.0
                mae = ((low / entry) - 1.0) * 100.0

        return SaxoAnalogueReaction(
            candidate_event_id=candidate.event_id,
            published_at=event_time.isoformat(),
            contract_symbol=contract.symbol,
            contract_uic=contract.uic,
            price_at_event=entry,
            return_15m_pct=_return_pct(entry, p15),
            return_1h_pct=_return_pct(entry, p1h),
            return_4h_pct=_return_pct(entry, p4h),
            return_24h_pct=_return_pct(entry, p24h),
            mfe_4h_pct=mfe,
            mae_4h_pct=mae,
            status="OK",
        )
    except Exception as exc:
        return SaxoAnalogueReaction(
            candidate_event_id=candidate.event_id,
            published_at=event_time.isoformat(),
            contract_symbol="",
            contract_uic=None,
            price_at_event=None,
            return_15m_pct=None,
            return_1h_pct=None,
            return_4h_pct=None,
            return_24h_pct=None,
            mfe_4h_pct=None,
            mae_4h_pct=None,
            status=getattr(exc, "status", "PRICE_UNAVAILABLE"),
            error=str(exc),
        )


def measure_brent_reactions(
    candidates: Iterable[GdeltCandidateRecord],
    *,
    client: SaxoClient,
    continuous_uic: int = BRENT_CONTINUOUS_UIC,
) -> list[SaxoAnalogueReaction]:
    contracts = client.future_space(continuous_uic)
    return [measure_candidate_reaction(candidate, client=client, contracts=contracts) for candidate in candidates]
