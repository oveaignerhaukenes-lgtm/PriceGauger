from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
import os
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("pricegauger.telegram_ingest")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")

_EVENT_TERMS: dict[str, tuple[str, ...]] = {
    "attack": ("attack", "attacked", "strike", "struck", "airstrike", "missile", "drone", "bomb", "bombed", "explosion", "shelling"),
    "blockade": ("blockade", "closure", "closed", "halted", "disrupted", "seized"),
    "sanctions": ("sanction", "sanctions", "embargo", "export ban", "restriction"),
    "diplomacy": ("ceasefire", "negotiation", "talks", "agreement", "deal", "truce"),
    "production": ("production", "output", "supply", "quota", "cut", "increase"),
}

_TARGET_TERMS: dict[str, tuple[str, ...]] = {
    "diplomatic facility": ("embassy", "consulate", "diplomatic mission", "ambassador residence"),
    "energy infrastructure": ("refinery", "pipeline", "oilfield", "oil field", "gas field", "terminal", "lng", "power plant", "energy infrastructure"),
    "shipping": ("tanker", "vessel", "ship", "port", "strait", "shipping", "maritime"),
    "military": ("airbase", "military base", "base", "troops", "navy", "army", "irgc"),
    "government": ("ministry", "parliament", "government", "presidential palace"),
    "civilian": ("hospital", "school", "residential", "civilian"),
}

_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "Bahrain": ("bahrain", "bahraini", "manama"),
    "Iran": ("iran", "iranian", "tehran", "isfahan", "south pars", "kharg"),
    "Israel": ("israel", "israeli", "tel aviv", "haifa", "jerusalem"),
    "Iraq": ("iraq", "iraqi", "baghdad", "basra", "kirkuk"),
    "Saudi Arabia": ("saudi arabia", "saudi", "riyadh", "aramco", "jeddah"),
    "Yemen": ("yemen", "yemeni", "sanaa", "houthi", "houthis"),
    "Lebanon": ("lebanon", "lebanese", "beirut", "hezbollah"),
    "Syria": ("syria", "syrian", "damascus", "latakia"),
    "Qatar": ("qatar", "qatari", "doha"),
    "United Arab Emirates": ("united arab emirates", "uae", "emirati", "abu dhabi", "dubai"),
    "Oman": ("oman", "omani", "muscat"),
}

_DOMAIN_BY_TARGET = {
    "diplomatic facility": "POLITICAL",
    "energy infrastructure": "INFRASTRUCTURE",
    "shipping": "INFRASTRUCTURE",
    "military": "POLITICAL",
    "government": "POLITICAL",
    "civilian": "CRIME",
}

_STOPWORDS = {
    "after", "against", "amid", "breaking", "claims", "from", "have", "into", "near", "over",
    "reported", "reports", "says", "that", "their", "there", "this", "with", "were", "will",
}


@dataclass(frozen=True, slots=True)
class TelegramSearchPlan:
    message_id: str
    message_url: str
    message_text: str
    event_type: str
    target: str
    country: str
    domain: str
    search: str
    signal_score: int
    published_at: str = ""
    regime_id: str = "GEOPOLITICAL_CONFLICT"
    taxonomy_version: str = "geopolitical-conflict-v1"
    interpretation_source: str = "rules"
    interpretation_model: str = ""
    interpretation_version: str = "rules-v1"
    interpretation_confidence: float | None = None
    actor: str = ""
    market_channel: str = ""
    search_terms: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _first_match(text: str, groups: dict[str, tuple[str, ...]], default: str = "") -> str:
    for label, terms in groups.items():
        if any(term in text for term in terms):
            return label
    return default


def _country(text: str) -> str:
    return _first_match(text, _COUNTRY_ALIASES)


def _distinct_keywords(text: str, *, limit: int = 4) -> list[str]:
    found: list[str] = []
    for token in _TOKEN_RE.findall(text):
        lowered = token.lower()
        if lowered in _STOPWORDS or lowered in found:
            continue
        found.append(lowered)
        if len(found) >= limit:
            break
    return found


def _plan_sort_key(plan: TelegramSearchPlan) -> tuple[float, int, str]:
    timestamp = 0.0
    if plan.published_at:
        try:
            parsed = datetime.fromisoformat(plan.published_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamp = parsed.timestamp()
        except ValueError:
            pass
    try:
        numeric_id = int(plan.message_id)
    except ValueError:
        numeric_id = -1
    return timestamp, numeric_id, plan.message_id


def build_search_plan(*, message_id: str, message_url: str, text: str, published_at: str = "") -> TelegramSearchPlan:
    lowered = _normalise(text)
    event_type = _first_match(lowered, _EVENT_TERMS, "event")
    target = _first_match(lowered, _TARGET_TERMS, "")
    country = _country(lowered)
    domain = _DOMAIN_BY_TARGET.get(target, "POLITICAL" if event_type in {"attack", "blockade", "sanctions", "diplomacy"} else "")

    parts: list[str] = []
    if event_type != "event":
        parts.append(event_type)
    if target:
        parts.append(target)
    if country:
        parts.append(country)
    if len(parts) < 2:
        parts.extend(_distinct_keywords(text, limit=4 - len(parts)))

    search = " ".join(dict.fromkeys(part for part in parts if part)).strip()
    signal_score = int(event_type != "event") + int(bool(target)) + int(bool(country))
    return TelegramSearchPlan(
        message_id=str(message_id),
        message_url=message_url,
        message_text=text,
        event_type=event_type,
        target=target or "unspecified",
        country=country,
        domain=domain,
        search=search,
        signal_score=signal_score,
        published_at=published_at,
        search_terms=tuple(parts),
    )


def plans_from_telegram_html(html: str, *, minimum_signal: int = 2) -> list[TelegramSearchPlan]:
    soup = BeautifulSoup(html, "html.parser")
    plans: list[TelegramSearchPlan] = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        post = wrap.select_one(".tgme_widget_message")
        text_node = wrap.select_one(".tgme_widget_message_text")
        time_node = wrap.select_one("time")
        if post is None or text_node is None:
            continue
        data_post = str(post.get("data-post") or "")
        if "/" not in data_post:
            continue
        channel_name, message_id = data_post.rsplit("/", 1)
        text = text_node.get_text("\n", strip=True)
        if not text:
            continue
        plan = build_search_plan(
            message_id=message_id,
            message_url=f"https://t.me/{channel_name}/{message_id}",
            text=text,
            published_at=str(time_node.get("datetime") or "") if time_node else "",
        )
        if plan.signal_score >= minimum_signal and plan.search:
            plans.append(plan)
    return sorted(plans, key=_plan_sort_key)


def _fetch_web_search_plans(
    channel: str,
    *,
    minimum_signal: int,
    timeout: int,
) -> list[TelegramSearchPlan]:
    cache_buster = int(datetime.now(timezone.utc).timestamp())
    response = requests.get(
        f"https://t.me/s/{channel.lstrip('@')}",
        params={"_pg": cache_buster},
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 PriceGauger/1.3",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
    response.raise_for_status()
    plans = plans_from_telegram_html(response.text, minimum_signal=minimum_signal)
    LOGGER.info("telegram ingest provider=web channel=%s fetched=%s", channel, len(plans))
    return plans


def _fetch_telethon_search_plans(
    channel: str,
    *,
    minimum_signal: int,
) -> list[TelegramSearchPlan]:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session = os.getenv("TELEGRAM_SESSION", "").strip()
    if not raw_api_id or not api_hash or not session:
        raise RuntimeError("Telethon credentials are incomplete")
    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_API_ID must be numeric") from exc

    try:
        fetch_limit = max(20, min(500, int(os.getenv("TELEGRAM_FETCH_LIMIT", "100"))))
    except ValueError:
        fetch_limit = 100

    username = channel.lstrip("@")
    plans: list[TelegramSearchPlan] = []
    with TelegramClient(StringSession(session), api_id, api_hash) as client:
        messages = client.get_messages(username, limit=fetch_limit)
        for message in messages:
            text = str(getattr(message, "message", "") or "").strip()
            if not text:
                continue
            published = getattr(message, "date", None)
            published_at = ""
            if published is not None:
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published_at = published.astimezone(timezone.utc).isoformat()
            plan = build_search_plan(
                message_id=str(message.id),
                message_url=f"https://t.me/{username}/{message.id}",
                text=text,
                published_at=published_at,
            )
            if plan.signal_score >= minimum_signal and plan.search:
                plans.append(plan)

    plans = sorted(plans, key=_plan_sort_key)
    latest = plans[-1] if plans else None
    LOGGER.info(
        "telegram ingest provider=telethon channel=%s fetched=%s latest_id=%s latest_at=%s",
        channel,
        len(plans),
        latest.message_id if latest else "none",
        latest.published_at if latest else "none",
    )
    return plans


def fetch_search_plans(
    channel: str = "Middle_East_Spectator",
    *,
    minimum_signal: int = 2,
    timeout: int = 30,
) -> list[TelegramSearchPlan]:
    provider = os.getenv("TELEGRAM_INGEST_PROVIDER", "auto").strip().lower()
    credentials_present = all(
        os.getenv(name, "").strip()
        for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION")
    )
    use_telethon = provider == "telethon" or (provider == "auto" and credentials_present)

    if use_telethon:
        try:
            return _fetch_telethon_search_plans(channel, minimum_signal=minimum_signal)
        except Exception as exc:
            fallback_enabled = os.getenv("TELEGRAM_WEB_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}
            if not fallback_enabled:
                raise
            LOGGER.warning("telethon ingest failed; falling back to public web source: %s", exc)

    return _fetch_web_search_plans(channel, minimum_signal=minimum_signal, timeout=timeout)


def fetch_latest_search_plan(
    channel: str = "Middle_East_Spectator",
    *,
    minimum_signal: int = 2,
    timeout: int = 30,
) -> TelegramSearchPlan | None:
    plans = fetch_search_plans(channel, minimum_signal=minimum_signal, timeout=timeout)
    return plans[-1] if plans else None
