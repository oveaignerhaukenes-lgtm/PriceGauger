from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


@dataclass(slots=True)
class MarketAssessment:
    asset: str
    direction: str
    confidence_pct: float
    expected_move_pct: float | None
    horizon: str
    historical_sample: int
    historical_positive_share_pct: float | None
    historical_median_pct: float | None
    live_event_score: float
    momentum_pct: float | None
    evidence_grade: str
    rationale: list[str]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StrategySuggestion:
    action: str
    max_leverage: float
    take_profit_pct: float | None
    stop_loss_pct: float | None
    max_holding_time: str
    methodology: str
    warning: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _recent_message_score(messages: pd.DataFrame, now: pd.Timestamp) -> float:
    if messages.empty or "published_at" not in messages:
        return 0.0
    frame = messages.copy()
    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["published_at"])
    frame = frame[frame["published_at"] >= now - pd.Timedelta(hours=12)]
    if frame.empty:
        return 0.0
    age_hours = (now - frame["published_at"]).dt.total_seconds() / 3600.0
    weights = 1.0 / (1.0 + age_hours / 2.0)
    impact = pd.to_numeric(frame.get("impact", 0.0), errors="coerce").fillna(0.0)
    return float((impact * weights).sum())


def _momentum_pct(market: pd.DataFrame) -> float | None:
    if market.empty or "close" not in market:
        return None
    closes = pd.to_numeric(market["close"], errors="coerce").dropna()
    if len(closes) < 3:
        return None
    lookback = min(24, len(closes) - 1)
    base = float(closes.iloc[-lookback - 1])
    if base == 0:
        return None
    return (float(closes.iloc[-1]) / base - 1.0) * 100.0


def _historical_frame(reactions: Iterable[Any], asset: str) -> pd.DataFrame:
    records = []
    for item in reactions:
        record = item.to_record() if hasattr(item, "to_record") else dict(item)
        if record.get("asset") == asset:
            records.append(record)
    return pd.DataFrame(records)


def _profile_record(profile: Any | None) -> dict[str, Any]:
    if profile is None:
        return {}
    if hasattr(profile, "to_record"):
        return dict(profile.to_record())
    if isinstance(profile, Mapping):
        return dict(profile)
    return dict(vars(profile))


def _direction_from_value(value: float | None, dead_zone: float) -> str:
    if value is None:
        return "NEUTRAL"
    if value > dead_zone:
        return "LONG"
    if value < -dead_zone:
        return "SHORT"
    return "NEUTRAL"


def build_market_assessment(
    *,
    asset: str,
    messages: pd.DataFrame,
    market: pd.DataFrame,
    intraday_reactions: Iterable[Any] | None = None,
    market_profile: Any | None = None,
) -> MarketAssessment:
    """Build an assessment from live flow, momentum and optional EventDNA analogues.

    When ``market_profile`` is supplied, its similarity-weighted analogue sample is
    used instead of the unfiltered asset-wide reaction history. The historical
    analogue expectation anchors direction; live flow and current momentum adjust
    confidence but cannot silently reverse a positive expectation into SHORT, or a
    negative expectation into LONG.
    """
    now = pd.Timestamp.now(tz="UTC")
    live_score = _recent_message_score(messages, now)
    momentum = _momentum_pct(market)
    profile = _profile_record(market_profile)
    history = _historical_frame(intraday_reactions or [], asset)

    sample = len(history)
    effective_sample = float(sample)
    median_1h = None
    positive_share = None
    expected_move = None
    median_adverse = None
    median_quality = None
    profile_confidence = None
    profile_direction = "NEUTRAL"
    analogue_mode = bool(profile)

    if analogue_mode:
        sample = int(profile.get("sample_size") or 0)
        effective_sample = float(profile.get("effective_sample_size") or 0.0)
        median_1h = profile.get("median_1h_pct")
        positive_share = profile.get("positive_share_pct")
        expected_move = profile.get("weighted_mean_4h_pct")
        if expected_move is None:
            expected_move = profile.get("median_4h_pct")
        if expected_move is None:
            expected_move = profile.get("weighted_mean_1h_pct")
        if expected_move is None:
            expected_move = median_1h
        adverse_value = profile.get("median_max_down_24h_pct")
        median_adverse = abs(float(adverse_value)) if adverse_value is not None else None
        profile_confidence = float(profile.get("confidence_pct") or 0.0)
        candidate_direction = str(profile.get("direction") or "NEUTRAL").upper()
        profile_direction = candidate_direction if candidate_direction in {"LONG", "SHORT", "NEUTRAL"} else "NEUTRAL"
    elif not history.empty:
        one_hour = pd.to_numeric(history.get("return_1h_pct"), errors="coerce").dropna()
        four_hour = pd.to_numeric(history.get("return_4h_pct"), errors="coerce").dropna()
        adverse = pd.to_numeric(history.get("max_down_24h_pct"), errors="coerce").dropna()
        quality = pd.to_numeric(history.get("quality_score"), errors="coerce").dropna()
        if not one_hour.empty:
            median_1h = float(one_hour.median())
            positive_share = float((one_hour > 0).mean() * 100.0)
        if not four_hour.empty:
            expected_move = float(four_hour.median())
        elif median_1h is not None:
            expected_move = median_1h
        if not adverse.empty:
            median_adverse = float(abs(adverse.median()))
        if not quality.empty:
            median_quality = float(quality.median())

    asset_live_weight = {
        "Brent": 0.10,
        "Silver": 0.055,
        "Gold": 0.045,
        "DXY": 0.015,
    }.get(asset, 0.03)
    live_component = live_score * asset_live_weight
    momentum_component = (momentum or 0.0) * 0.35
    history_scale = min(1.0, effective_sample / 12.0) if analogue_mode else min(1.0, sample / 20.0)
    historical_component = (float(expected_move) if expected_move is not None else 0.0) * history_scale
    context_component = live_component + momentum_component
    combined = historical_component + context_component

    dead_zone = 0.12
    historical_direction = _direction_from_value(
        float(expected_move) if expected_move is not None else None,
        dead_zone,
    )
    context_direction = _direction_from_value(context_component, dead_zone)
    direction_conflict = False

    if analogue_mode:
        # Historical analogues are the primary signal. The profile's aggregate
        # direction is only a fallback when the expected move lies in the dead zone.
        direction = historical_direction if historical_direction != "NEUTRAL" else profile_direction
        direction_conflict = (
            direction in {"LONG", "SHORT"}
            and context_direction in {"LONG", "SHORT"}
            and direction != context_direction
        )
    else:
        direction = _direction_from_value(combined, dead_zone)

    if analogue_mode:
        sample_score = min(30.0, effective_sample * 3.0)
        directional_score = min(25.0, abs(float(positive_share) - 50.0)) if positive_share is not None else 0.0
        live_confidence = min(15.0, abs(live_score) * 1.25)
        momentum_confidence = min(10.0, abs(momentum or 0.0) * 2.0)
        confidence = 15.0 + sample_score + directional_score + live_confidence + momentum_confidence
        if profile_confidence is not None:
            confidence = (confidence * 0.55) + (profile_confidence * 0.45)
        if direction_conflict:
            confidence -= 12.0
        confidence = round(max(0.0, min(95.0, confidence)), 1)
    else:
        sample_score = min(30.0, sample * 1.5)
        quality_score = 20.0 if median_quality is None else min(25.0, median_quality * 0.25)
        directional_score = 0.0
        if positive_share is not None:
            directional_score = min(25.0, abs(positive_share - 50.0))
        live_confidence = min(20.0, abs(live_score) * 1.5)
        confidence = round(min(95.0, 20.0 + sample_score + quality_score + directional_score + live_confidence), 1)

    minimum_sample = 3 if analogue_mode else 8
    if sample < minimum_sample or (analogue_mode and effective_sample < 1.5):
        grade = "INSUFFICIENT"
    elif confidence >= 80:
        grade = "HIGH"
    elif confidence >= 65:
        grade = "MEDIUM"
    else:
        grade = "LOW"

    horizon = "1–4 timer" if expected_move is not None else "ukjent"
    rationale = [f"Live Telegram-score siste 12 timer: {live_score:.2f}"]
    if analogue_mode:
        rationale.append(
            f"EventDNA-utvalg for {asset}: {sample} reaksjoner, effektivt utvalg {effective_sample:.2f}"
        )
        if profile_confidence is not None:
            rationale.append(f"Market Profile-konfidens: {profile_confidence:.1f} %")
    else:
        rationale.append(f"Historisk utvalg for {asset}: {sample} koblinger")
    if median_1h is not None:
        rationale.append(f"Historisk median etter 1 time: {float(median_1h):+.3f} %")
    if expected_move is not None:
        label = "Likhetsvektet forventning etter 4 timer" if analogue_mode else "Historisk forventning etter 4 timer"
        rationale.append(f"{label}: {float(expected_move):+.3f} %")
    if positive_share is not None:
        rationale.append(f"Historisk andel positive etter 1 time: {float(positive_share):.0f} %")
    if momentum is not None:
        rationale.append(f"Kort markedsmomentum: {momentum:+.3f} %")
    if median_adverse is not None:
        rationale.append(f"Historisk median ugunstig 24t-ekstrem: {median_adverse:.3f} %")
    if analogue_mode:
        rationale.append(
            f"Retningsanker: historiske analoger ({direction}); live/momentum brukes som konfidensjustering."
        )
        rationale.append(
            f"Komponenter: historikk {historical_component:+.3f}, live {live_component:+.3f}, momentum {momentum_component:+.3f}."
        )
        if direction_conflict:
            rationale.append(
                "Aktuell markedsmomentum/liveflyt peker motsatt av analoghistorikken; retningen beholdes, men konfidensen er redusert."
            )

    return MarketAssessment(
        asset=asset,
        direction=direction,
        confidence_pct=confidence,
        expected_move_pct=float(expected_move) if expected_move is not None else None,
        horizon=horizon,
        historical_sample=sample,
        historical_positive_share_pct=float(positive_share) if positive_share is not None else None,
        historical_median_pct=float(median_1h) if median_1h is not None else None,
        live_event_score=round(live_score, 3),
        momentum_pct=momentum,
        evidence_grade=grade,
        rationale=rationale,
    )


def build_strategy_suggestion(
    assessment: MarketAssessment,
    *,
    profit_capture: float = 0.80,
) -> StrategySuggestion:
    if assessment.evidence_grade == "INSUFFICIENT" or assessment.direction == "NEUTRAL":
        return StrategySuggestion(
            action="NO TRADE",
            max_leverage=1.0,
            take_profit_pct=None,
            stop_loss_pct=None,
            max_holding_time="Ingen posisjon",
            methodology="Avstå når datagrunnlaget er utilstrekkelig eller retningen er nøytral.",
            warning="Analyse og handlingsregel er separate. Dette er en pilotregel, ikke en ordre.",
        )

    confidence = assessment.confidence_pct
    if confidence >= 88:
        leverage = 10.0
    elif confidence >= 78:
        leverage = 7.0
    elif confidence >= 68:
        leverage = 4.0
    else:
        leverage = 2.0

    expected = abs(assessment.expected_move_pct or assessment.historical_median_pct or 0.0)
    take_profit = round(expected * profit_capture, 3) if expected > 0 else None
    stop = round(max(0.25, min(1.5, expected * 0.45)), 3) if expected > 0 else None

    return StrategySuggestion(
        action=assessment.direction,
        max_leverage=leverage,
        take_profit_pct=take_profit,
        stop_loss_pct=stop,
        max_holding_time=assessment.horizon,
        methodology=(
            "Retning følger analysegrunnlaget. Maks gearing trappes etter konfidens. "
            f"Gevinstmål settes til {profit_capture:.0%} av forventet underliggende bevegelse."
        ),
        warning=(
            "Forslaget må backtestes før det brukes som fast metodologi. Produktets gearing, spread, "
            "knock-out-avstand og gap-risiko må vurderes separat."
        ),
    )
