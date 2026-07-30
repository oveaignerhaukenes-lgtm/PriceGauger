from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

import requests

from config import openai_api_key, openai_market_model
from openai_market_provider import OPENAI_RESPONSES_URL, _response_output_text
from overview_service import OverviewData


SUMMARY_ENGINE_VERSION = "overview-summary-v1"
SENSITIVITY_TYPES = (
    "HEADLINE_SENSITIVE",
    "COMMODITY_SENSITIVE",
    "MACRO_POLICY_SENSITIVE",
    "MIXED",
    "UNCLEAR",
)


@dataclass(frozen=True, slots=True)
class OverviewSummary:
    regime: str
    sensitivity: str
    headline: str
    summary: str
    key_driver: str
    caveat: str
    model: str
    engine_version: str = SUMMARY_ENGINE_VERSION


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "regime": {"type": "string", "maxLength": 80},
            "sensitivity": {"type": "string", "enum": list(SENSITIVITY_TYPES)},
            "headline": {"type": "string", "maxLength": 140},
            "summary": {"type": "string", "maxLength": 700},
            "key_driver": {"type": "string", "maxLength": 220},
            "caveat": {"type": "string", "maxLength": 220},
        },
        "required": ["regime", "sensitivity", "headline", "summary", "key_driver", "caveat"],
    }


def _payload(data: OverviewData) -> dict[str, Any]:
    information = dict(data.information_state or {})
    markets = [
        {
            "market": item.market,
            "direction": item.direction,
            "score": round(float(item.score), 4),
            "confidence": round(float(item.confidence), 4),
            "change_from_previous": round(float(item.change_from_previous), 4),
            "event_count": int(item.event_count),
            "top_driver": item.top_driver,
            "status_reason": item.status_reason,
        }
        for item in data.markets
    ]
    posts = []
    for post in data.latest_posts[:6]:
        ranked = sorted(
            post.scores,
            key=lambda score: abs(score.direction * score.impact * score.confidence),
            reverse=True,
        )
        lead = ranked[0] if ranked else None
        posts.append(
            {
                "published_at": post.published_at,
                "channel": post.channel,
                "text": post.text[:900],
                "relation": post.relation,
                "novelty": post.novelty,
                "source_quality": post.source_quality,
                "lead_market": lead.asset if lead else "",
                "lead_direction": lead.direction if lead else 0.0,
                "lead_impact": lead.impact if lead else 0.0,
                "lead_confidence": lead.confidence if lead else 0.0,
            }
        )
    return {
        "information_state": {
            "as_of": information.get("as_of"),
            "conflict_regime": information.get("conflict_regime"),
            "ceasefire_active": information.get("ceasefire_active"),
            "narrative_saturation": information.get("narrative_saturation"),
            "confirmation_quality": information.get("confirmation_quality"),
            "supply_risk": information.get("supply_risk"),
            "active_event_count": information.get("active_event_count"),
        },
        "markets": markets,
        "latest_posts": posts,
        "limitations": [
            "Price and technical confirmation may still be pending.",
            "No economic calendar or external macro feed is included in this payload.",
            "Classify macro-policy sensitivity only when supported by the supplied events or market pattern.",
        ],
    }


def _fallback(data: OverviewData) -> OverviewSummary:
    info = data.information_state or {}
    regime = str(info.get("conflict_regime") or "Uavklart regime")
    strongest = max(data.markets, key=lambda item: abs(item.score), default=None)
    if strongest is None:
        headline = "For lite data til en helhetlig vurdering"
        summary = "Systemet venter på en fersk, konsistent tilstand før markedene kan settes i sammenheng."
        driver = "Ingen tydelig hoveddriver er identifisert."
    else:
        headline = f"{regime}: {strongest.market} har tydeligst informasjonsdrevet bias"
        summary = (
            f"Det helhetlige bildet er foreløpig mest nyhets- og overskriftsfølsomt. "
            f"{strongest.market} har sterkest utslag ({strongest.direction}, {strongest.score:+.2f}), "
            "men pris- og teknisk bekreftelse er ennå ikke fullt koblet inn."
        )
        driver = strongest.top_driver
    return OverviewSummary(
        regime=regime,
        sensitivity="HEADLINE_SENSITIVE",
        headline=headline,
        summary=summary,
        key_driver=driver,
        caveat="Foreløpig sammendrag uten ny modellkall; pris-, teknisk- og kalenderbekreftelse kan mangle.",
        model="deterministic-fallback",
    )


def build_overview_summary(
    data: OverviewData,
    *,
    api_key: str | None = None,
    model: str | None = None,
    session: Any = requests,
    timeout: int = 45,
) -> OverviewSummary:
    key = (api_key if api_key is not None else openai_api_key()).strip()
    selected_model = (model if model is not None else openai_market_model()).strip()
    if not key:
        return _fallback(data)

    system_prompt = """You are the contextual market-regime summarizer for PriceGauger.
Use only the supplied state snapshots and recent scored messages. Write concise Norwegian.
Identify the current regime, the dominant market-moving mechanism, and whether the state is mainly:
- HEADLINE_SENSITIVE: abrupt news and confirmation/denial drive repricing,
- COMMODITY_SENSITIVE: physical supply, shipping, inventories or production dominate,
- MACRO_POLICY_SENSITIVE: rates, Fed, CPI, PPI or policy expectations dominate,
- MIXED, or UNCLEAR.
Do not invent calendar events, prices, technical confirmation or external facts that are absent.
Treat individual Telegram posts as nudges to the existing state, not standalone truth.
Explicitly state uncertainty when price/technical confirmation or macro-calendar data is missing.
The summary should provide context for the market cards below, not a trade recommendation."""

    response = session.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": selected_model,
            "store": False,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(_payload(data), ensure_ascii=False, sort_keys=True)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "overview_context_summary",
                    "schema": _schema(),
                    "strict": True,
                }
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    parsed = json.loads(_response_output_text(response.json()))
    if not isinstance(parsed, Mapping):
        raise ValueError("overview summary response must be an object")
    return OverviewSummary(
        regime=str(parsed["regime"]).strip(),
        sensitivity=str(parsed["sensitivity"]).strip(),
        headline=str(parsed["headline"]).strip(),
        summary=str(parsed["summary"]).strip(),
        key_driver=str(parsed["key_driver"]).strip(),
        caveat=str(parsed["caveat"]).strip(),
        model=selected_model,
    )
