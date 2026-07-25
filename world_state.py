from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import tanh
from typing import Any

from google.cloud import bigquery


GDELT_GKG_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
MAX_BYTES_BILLED = 2 * 1024**3

CATEGORY_PATTERNS: dict[str, str] = {
    "Geopolitical tension": r"(MILITARY|ARMEDCONFLICT|TERROR|REBELLION|WAR|BORDER)",
    "Military activity": r"(MILITARY|AIRSTRIKE|MISSILE|DRONE|BOMBING|NAVAL|ARMEDCONFLICT)",
    "Diplomatic activity": r"(DIPLOMACY|NEGOTIATIONS|CEASEFIRE|PEACE|MEDIATION|TREATY)",
    "Economic stress": r"(ECON_|RECESSION|INFLATION|UNEMPLOYMENT|DEBT|BANKRUPTCY|FINANCIAL_CRISIS)",
    "Energy / supply risk": r"(ENERGY|OIL|GAS|PIPELINE|REFINERY|SHIPPING|PORT|SUPPLY_CHAIN)",
    "Social unrest": r"(PROTEST|RIOT|STRIKE|CIVIL_UNREST|DEMONSTRATION|REVOLUTION)",
    "Global uncertainty": r"(CRISIS|EMERGENCY|THREAT|RISK|UNCERTAINTY|DISRUPTION)",
}

# Approximate prevalence per 1,000 GKG documents at which a category reaches
# the middle of the visual scale. These are explicit MVP priors and should be
# replaced by rolling historical percentiles after enough snapshots exist.
CATEGORY_MIDPOINTS: dict[str, float] = {
    "Geopolitical tension": 85.0,
    "Military activity": 55.0,
    "Diplomatic activity": 40.0,
    "Economic stress": 80.0,
    "Energy / supply risk": 55.0,
    "Social unrest": 45.0,
    "Global uncertainty": 100.0,
}

MOOD_WEIGHTS: dict[str, float] = {
    "Geopolitical tension": 0.19,
    "Military activity": 0.16,
    "Diplomatic activity": -0.12,
    "Economic stress": 0.18,
    "Energy / supply risk": 0.16,
    "Social unrest": 0.12,
    "Global uncertainty": 0.21,
}

ASSET_WEIGHTS: dict[str, dict[str, float]] = {
    "Brent": {
        "Geopolitical tension": 0.25,
        "Military activity": 0.18,
        "Diplomatic activity": -0.12,
        "Economic stress": -0.13,
        "Energy / supply risk": 0.44,
        "Social unrest": 0.03,
        "Global uncertainty": 0.09,
    },
    "Gold": {
        "Geopolitical tension": 0.20,
        "Military activity": 0.10,
        "Diplomatic activity": -0.08,
        "Economic stress": 0.18,
        "Energy / supply risk": 0.04,
        "Social unrest": 0.08,
        "Global uncertainty": 0.32,
    },
    "Silver": {
        "Geopolitical tension": 0.10,
        "Military activity": 0.05,
        "Diplomatic activity": -0.04,
        "Economic stress": -0.18,
        "Energy / supply risk": 0.10,
        "Social unrest": 0.03,
        "Global uncertainty": 0.12,
    },
    "DXY": {
        "Geopolitical tension": 0.10,
        "Military activity": 0.04,
        "Diplomatic activity": -0.03,
        "Economic stress": 0.10,
        "Energy / supply risk": 0.02,
        "Social unrest": 0.03,
        "Global uncertainty": 0.18,
    },
}


@dataclass(frozen=True, slots=True)
class WorldStateCategory:
    name: str
    score: int
    previous_score: int
    change: int
    current_rate_per_1000: float
    previous_rate_per_1000: float
    current_documents: int
    previous_documents: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssetMood:
    asset: str
    score: int
    bias: str
    confidence: int

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorldState:
    calculated_at: str
    window_hours: int
    window_start: str
    window_end: str
    previous_window_start: str
    document_count: int
    previous_document_count: int
    average_tone: float | None
    previous_average_tone: float | None
    mood_score: int
    mood_label: str
    direction: str
    confidence: int
    categories: tuple[WorldStateCategory, ...]
    asset_moods: tuple[AssetMood, ...]
    bytes_processed: int
    limitations: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        result = asdict(self)
        result["categories"] = [item.to_record() for item in self.categories]
        result["asset_moods"] = [item.to_record() for item in self.asset_moods]
        return result


def _bounded(value: float, lower: int = 0, upper: int = 100) -> int:
    return int(max(lower, min(upper, round(value))))


def _score_rate(rate: float, midpoint: float) -> int:
    if midpoint <= 0:
        return 0
    # 0 at no coverage, 50 around the explicit midpoint and asymptotically 100.
    return _bounded(100.0 * rate / (rate + midpoint))


def _direction(change: int) -> str:
    if change >= 7:
        return "DETERIORATING"
    if change <= -7:
        return "IMPROVING"
    return "STABLE"


def _mood_label(score: int) -> str:
    if score >= 70:
        return "STRONGLY RISK-OFF"
    if score >= 55:
        return "RISK-OFF"
    if score <= 30:
        return "STRONGLY RISK-ON"
    if score <= 45:
        return "RISK-ON"
    return "MIXED"


def _asset_bias(score: int) -> str:
    if score >= 65:
        return "BULLISH"
    if score >= 55:
        return "MIXED-BULLISH"
    if score <= 35:
        return "BEARISH"
    if score <= 45:
        return "MIXED-BEARISH"
    return "NEUTRAL"


def _query(window_hours: int) -> str:
    category_columns = ",\n".join(
        f"COUNTIF(REGEXP_CONTAINS(UPPER(COALESCE(Themes, '')), r'{pattern}')) AS category_{index}"
        for index, pattern in enumerate(CATEGORY_PATTERNS.values())
    )
    return f"""
    WITH source AS (
      SELECT
        SAFE.PARSE_TIMESTAMP('%Y%m%d%H%M%S', CAST(DATE AS STRING)) AS published_at,
        SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
        Themes
      FROM `{GDELT_GKG_TABLE}`
      WHERE _PARTITIONDATE BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY) AND CURRENT_DATE()
    ), windowed AS (
      SELECT
        CASE
          WHEN published_at >= @current_start AND published_at < @window_end THEN 'current'
          WHEN published_at >= @previous_start AND published_at < @current_start THEN 'previous'
        END AS period,
        tone,
        Themes
      FROM source
      WHERE published_at >= @previous_start AND published_at < @window_end
    )
    SELECT
      period,
      COUNT(*) AS document_count,
      AVG(tone) AS average_tone,
      {category_columns}
    FROM windowed
    WHERE period IS NOT NULL
    GROUP BY period
    """


def fetch_world_state(
    *,
    client: bigquery.Client | None = None,
    window_hours: int = 12,
    now: datetime | None = None,
    maximum_bytes_billed: int = MAX_BYTES_BILLED,
) -> WorldState:
    if window_hours < 1 or window_hours > 24:
        raise ValueError("window_hours must be between 1 and 24")

    client = client or bigquery.Client()
    window_end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    current_start = window_end - timedelta(hours=window_hours)
    previous_start = current_start - timedelta(hours=window_hours)
    sql = _query(window_hours)
    parameters = [
        bigquery.ScalarQueryParameter("previous_start", "TIMESTAMP", previous_start),
        bigquery.ScalarQueryParameter("current_start", "TIMESTAMP", current_start),
        bigquery.ScalarQueryParameter("window_end", "TIMESTAMP", window_end),
    ]
    config = bigquery.QueryJobConfig(
        query_parameters=parameters,
        maximum_bytes_billed=maximum_bytes_billed,
        use_query_cache=True,
    )

    dry_config = bigquery.QueryJobConfig(
        query_parameters=parameters,
        dry_run=True,
        use_query_cache=False,
    )
    dry_job = client.query(sql, job_config=dry_config, location="US")
    if dry_job.total_bytes_processed > maximum_bytes_billed:
        raise RuntimeError(
            f"World State query requires {dry_job.total_bytes_processed / 1024**3:.2f} GiB, "
            f"above the configured limit of {maximum_bytes_billed / 1024**3:.2f} GiB"
        )

    job = client.query(sql, job_config=config, location="US")
    rows = {str(row.period): dict(row.items()) for row in job.result()}
    current = rows.get("current", {})
    previous = rows.get("previous", {})
    current_docs = int(current.get("document_count") or 0)
    previous_docs = int(previous.get("document_count") or 0)

    categories: list[WorldStateCategory] = []
    for index, name in enumerate(CATEGORY_PATTERNS):
        current_count = int(current.get(f"category_{index}") or 0)
        previous_count = int(previous.get(f"category_{index}") or 0)
        current_rate = 1000.0 * current_count / current_docs if current_docs else 0.0
        previous_rate = 1000.0 * previous_count / previous_docs if previous_docs else 0.0
        score = _score_rate(current_rate, CATEGORY_MIDPOINTS[name])
        previous_score = _score_rate(previous_rate, CATEGORY_MIDPOINTS[name])
        categories.append(
            WorldStateCategory(
                name=name,
                score=score,
                previous_score=previous_score,
                change=score - previous_score,
                current_rate_per_1000=current_rate,
                previous_rate_per_1000=previous_rate,
                current_documents=current_count,
                previous_documents=previous_count,
            )
        )

    scores = {item.name: item.score for item in categories}
    previous_scores = {item.name: item.previous_score for item in categories}
    current_tone = current.get("average_tone")
    previous_tone = previous.get("average_tone")
    risk_component = sum(scores[name] * weight for name, weight in MOOD_WEIGHTS.items())
    previous_risk = sum(previous_scores[name] * weight for name, weight in MOOD_WEIGHTS.items())
    # Negative GDELT tone increases risk-off; positive tone reduces it.
    tone_adjustment = -8.0 * tanh(float(current_tone or 0.0) / 4.0)
    previous_tone_adjustment = -8.0 * tanh(float(previous_tone or 0.0) / 4.0)
    mood_score = _bounded(risk_component + tone_adjustment)
    previous_mood = _bounded(previous_risk + previous_tone_adjustment)

    data_coverage = min(1.0, current_docs / 5000.0)
    continuity = min(1.0, previous_docs / 5000.0)
    confidence = _bounded(35 + 35 * data_coverage + 20 * continuity + 10 * min(1.0, window_hours / 12.0))

    asset_moods: list[AssetMood] = []
    for asset, weights in ASSET_WEIGHTS.items():
        raw = 50.0 + sum((scores[name] - 50.0) * weight for name, weight in weights.items())
        if asset == "Silver":
            # Silver combines safe-haven and industrial-demand channels.
            raw -= max(0.0, scores["Economic stress"] - 50.0) * 0.12
        asset_score = _bounded(raw)
        asset_moods.append(
            AssetMood(
                asset=asset,
                score=asset_score,
                bias=_asset_bias(asset_score),
                confidence=confidence,
            )
        )

    return WorldState(
        calculated_at=datetime.now(timezone.utc).isoformat(),
        window_hours=window_hours,
        window_start=current_start.isoformat(),
        window_end=window_end.isoformat(),
        previous_window_start=previous_start.isoformat(),
        document_count=current_docs,
        previous_document_count=previous_docs,
        average_tone=float(current_tone) if current_tone is not None else None,
        previous_average_tone=float(previous_tone) if previous_tone is not None else None,
        mood_score=mood_score,
        mood_label=_mood_label(mood_score),
        direction=_direction(mood_score - previous_mood),
        confidence=confidence,
        categories=tuple(categories),
        asset_moods=tuple(asset_moods),
        bytes_processed=int(job.total_bytes_processed or dry_job.total_bytes_processed or 0),
        limitations=(
            "Scores are transparent MVP indices, not historically calibrated probabilities.",
            "GDELT measures published coverage and language, not private emotion or causal direction.",
            "A later lead-lag layer must compare first measurable state changes with timestamped market moves.",
        ),
    )
