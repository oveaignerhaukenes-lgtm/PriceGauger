from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ContentEligibility:
    eligible: bool
    reason: str
    promotional_score: float


_CALL_TO_ACTION = re.compile(
    r"\b(join|subscribe|follow|sign up|register|contact us|message us|click here|learn more)\b",
    re.IGNORECASE,
)
_PROMOTIONAL_TOPIC = re.compile(
    r"\b(crypto trading|bitcoin trading|trading opportunities|signals channel|vip channel|premium channel|investment group)\b",
    re.IGNORECASE,
)
_CONTACT_LINK = re.compile(
    r"https?://(?:chat\.whatsapp\.com|wa\.me|t\.me/(?:joinchat|\+)|discord\.gg)/?\S*",
    re.IGNORECASE,
)


def _external_contact_link_count(text: str) -> int:
    count = 0
    for match in re.finditer(r"https?://\S+", text, re.IGNORECASE):
        raw = match.group(0).rstrip(".,);]")
        try:
            host = (urlparse(raw).hostname or "").lower()
        except ValueError:
            continue
        if host in {"chat.whatsapp.com", "wa.me", "discord.gg"}:
            count += 1
        elif host == "t.me" and ("/joinchat/" in raw.lower() or "/+" in raw.lower()):
            count += 1
    return count


def classify_telegram_content(text: str) -> ContentEligibility:
    """Classify whether a Telegram post is eligible for market-state analysis.

    The filter is deliberately conservative: ordinary source links and channel
    mentions are allowed. A post is excluded only when several promotional
    signals indicate that the market headline is being used mainly as bait for
    recruitment, marketing or an unrelated trading offer.
    """
    value = str(text or "").strip()
    if not value:
        return ContentEligibility(False, "empty_post", 1.0)

    lowered = value.lower()
    score = 0.0
    reasons: list[str] = []

    if _CALL_TO_ACTION.search(value):
        score += 0.35
        reasons.append("call_to_action")
    if _PROMOTIONAL_TOPIC.search(value):
        score += 0.45
        reasons.append("promotional_trading_offer")
    if _CONTACT_LINK.search(value) or _external_contact_link_count(value):
        score += 0.45
        reasons.append("external_group_link")
    if "wondering how" in lowered and "trading" in lowered:
        score += 0.20
        reasons.append("marketing_bridge")

    promotional_score = min(1.0, score)
    eligible = promotional_score < 0.70
    reason = "eligible" if eligible else "+".join(dict.fromkeys(reasons))
    return ContentEligibility(eligible, reason, promotional_score)
