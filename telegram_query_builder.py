from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

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
    return plans


def fetch_latest_search_plan(
    channel: str = "Middle_East_Spectator",
    *,
    minimum_signal: int = 2,
    timeout: int = 30,
) -> TelegramSearchPlan | None:
    response = requests.get(
        f"https://t.me/s/{channel.lstrip('@')}",
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 PriceGauger/1.1"},
    )
    response.raise_for_status()
    plans = plans_from_telegram_html(response.text, minimum_signal=minimum_signal)
    return plans[-1] if plans else None
