"""Research-only scheduled macro release lead/lag analysis on received Saxo BBO.

No orders, risk settings, leverage selection, REST polling or background tasks.
All times UTC; price timestamps AND reception timestamps are retained.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping
import re

# Confirmed release clock from BLS 2026-11 calendar: 08:30 America/New_York,
# equivalent to 13:30 UTC in November 2026.
RELEASES = (
    ("NFP", "2026-11-06T13:30:00+00:00"),
    ("CPI", "2026-11-10T13:30:00+00:00"),
    ("PPI", "2026-11-13T13:30:00+00:00"),
)
PRE_SECONDS = 180
POST_SECONDS = 900
HORIZONS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600)
MAX_RECEIVE_AGE_SECONDS = 5.0
MAX_RELEASE_QUOTE_GAP_SECONDS = 6.0


def utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("Timezone-aware event/quote timestamp required")
    return parsed.astimezone(timezone.utc)


def releases():
    return tuple((kind, utc(at)) for kind, at in RELEASES)


def release_in_capture_window(at: str | datetime) -> bool:
    """True only within the predefined, narrow observation window."""
    stamp = utc(at)
    return any(
        t - timedelta(seconds=PRE_SECONDS) <= stamp <= t + timedelta(seconds=POST_SECONDS)
        for _, t in releases()
    )


def market_group(name: str) -> str | None:
    """Conservative instrument-name classifier; exact UIC kept separate."""
    token = re.sub(r"[^A-Z0-9]+", "", str(name).upper())
    if any(x in token for x in ("TECH100", "USNAS100", "NASDAQ100", "NAS100", "US100")):
        return "Tech100"
    if "GOLD" in token or "XAU" in token:
        return "Gull"
    if "SILVER" in token or "XAG" in token:
        return "Sølv"
    if "US500" in token or "SP500" in token:
        return "US500"
    return None


def _quotes(rows: list[Mapping[str, Any]], center: datetime):
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    lower = center - timedelta(seconds=PRE_SECONDS)
    upper = center + timedelta(seconds=POST_SECONDS)
    for row in rows:
        try:
            group = market_group(str(row.get("market_name") or ""))
            uic = int(row["provider_uic"])
            quote = utc(row["quote_at"])
            received = utc(row["received_at"])
            bid, ask = float(row["bid"]), float(row["ask"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if group is None or not (lower <= quote <= upper and lower <= received <= upper):
            continue
        if not (isfinite(bid) and isfinite(ask) and 0 < bid <= ask):
            continue
        # A packet with late delivery or future quote time cannot establish
        # latency or an executable next-price counterfactual.
        age = (received - quote).total_seconds()
        if not -2 <= age <= MAX_RECEIVE_AGE_SECONDS:
            continue
        groups[(group, uic)].append({
            "quote": quote, "received": received,
            "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
        })
    for k in groups:
        groups[k].sort(key=lambda q: (q["received"], q["quote"]))
    return groups


def _bps(current: float, initial: float) -> float:
    return (current / initial - 1.0) * 10000.0


def _at_or_after(quotes: list[dict[str, Any]], target: datetime, max_wait: float = 2.5):
    return next(
        (q for q in quotes if target <= q["received"] <= target + timedelta(seconds=max_wait)),
        None,
    )


def study_release(rows: list[Mapping[str, Any]], *, event: str | datetime,
                  threshold_bps: float = 5.0) -> dict[str, Any]:
    """Descriptive receipt-time event study; never interpolate missing quotes."""
    center = utc(event)
    if not 1 <= float(threshold_bps) <= 200:
        raise ValueError("threshold_bps must be in 1..200")
    instruments = _quotes(rows, center)
    result = []
    for (group, uic), observations in sorted(instruments.items()):
        pre = [q for q in observations if q["received"] < center
               and q["quote"] < center]
        post = [q for q in observations if q["received"] >= center]
        last_pre = pre[-1] if pre else None
        first_post = post[0] if post else None
        baseline_ok = (
            last_pre is not None and
            (center - last_pre["received"]).total_seconds() <= 10
        )
        release_gap = (
            (first_post["received"] - last_pre["received"]).total_seconds()
            if first_post is not None and last_pre is not None else None
        )
        quote_gap_ok = (
            baseline_ok and release_gap is not None
            and release_gap <= MAX_RELEASE_QUOTE_GAP_SECONDS
        )
        baseline = last_pre["mid"] if baseline_ok else None
        first_signal = None
        timed = {}
        if baseline is not None:
            for seconds in HORIZONS:
                candidate = _at_or_after(post, center + timedelta(seconds=seconds))
                timed[seconds] = (
                    round(_bps(candidate["mid"], baseline), 3)
                    if candidate else None
                )
            for q in post:
                if q["quote"] < center:
                    continue  # Pre-release source quote cannot establish first post-release impact.
                spread_bps = (q["ask"] - q["bid"]) / q["mid"] * 10000
                minimum = max(float(threshold_bps), 2.0 * spread_bps)
                move = _bps(q["mid"], baseline)
                if abs(move) >= minimum:
                    first_signal = {
                        "seconds": round((q["received"] - center).total_seconds(), 3),
                        "direction": "OPP" if move > 0 else "NED",
                        "move_bps": round(move, 3),
                        "received_at": q["received"].isoformat(),
                    }
                    break
        gap_warning = not quote_gap_ok
        result.append({
            "market": group, "uic": uic, "quotes": len(observations),
            "baseline": baseline, "baseline_at": (
                last_pre["received"].isoformat() if baseline_ok else None
            ),
            "first_post_at": first_post["received"].isoformat() if first_post else None,
            "release_gap_seconds": round(release_gap, 2) if release_gap is not None else None,
            "quality": "GAP_OR_MISSING_BASELINE" if gap_warning else "OK",
            "first_move": first_signal if quote_gap_ok else None,
            "indicative_move": first_signal if gap_warning else None,
            "returns_bps": timed,
        })
    # Different UICs are never joined. Only show one source per named market
    # when it has the most usable quotes in this particular window.
    strongest = {}
    for item in result:
        group = item["market"]
        if group not in strongest or item["quotes"] > strongest[group]["quotes"]:
            strongest[group] = item
    chosen = [strongest[g] for g in ("Gull", "Sølv", "Tech100", "US500")
              if g in strongest]
    gold = next((x for x in chosen if x["market"] == "Gull"), None)
    tech = next((x for x in chosen if x["market"] == "Tech100"), None)
    gold_signal = None if gold is None else gold["first_move"]
    tech_signal = None if tech is None else tech["first_move"]
    relative = (
        round(tech_signal["seconds"] - gold_signal["seconds"], 3)
        if gold_signal is not None and tech_signal is not None else None
    )
    return {
        "event_utc": center.isoformat(), "threshold_bps": float(threshold_bps),
        "markets": chosen, "all_sources": result,
        "tech_minus_gold_first_threshold_seconds": relative,
        "interpretation": (
            "Descriptive time between first RECEIVED BBO threshold crossings; "
            "not proof of exploitable lag or executable order fills."
        ),
    }


def paper_followthrough(rows: list[Mapping[str, Any]], *, event: str | datetime,
                        threshold_bps: float = 5.0, latency_seconds: int = 3,
                        hold_seconds: int = 60) -> dict[str, Any]:
    """Directional Gold signal -> Tech100 cross-spread PAPER counterfactual.

    GOLD signal uses only receipt-time prices. Tech100 entry is its FIRST
    RECEIVED BBO after gold receipt + configured latency, not the quote
    carrying the signal. Costs beyond spread/latency are not included.
    """
    if latency_seconds not in (1, 3, 5, 10) or hold_seconds not in (10, 30, 60, 120, 300):
        raise ValueError("unsupported paper scenario")
    center = utc(event)
    study = study_release(rows, event=center, threshold_bps=threshold_bps)
    g = next((x for x in study["markets"] if x["market"] == "Gull"), None)
    t = next((x for x in study["markets"] if x["market"] == "Tech100"), None)
    if g is None or t is None or g["first_move"] is None or t["quality"] != "OK":
        return {"status": "INSUFFICIENT_VALID_GOLD_TECH_QUOTES"}
    threshold_cross_at = utc(g["first_move"]["received_at"])
    if threshold_cross_at > center + timedelta(seconds=180):
        return {"status": "SIGNAL_TOO_LATE"}
    signed = 1 if g["first_move"]["direction"] == "OPP" else -1
    quotes = _quotes(rows, center).get(("Tech100", t["uic"]), [])
    eligible = [q for q in quotes if q["received"] >= threshold_cross_at + timedelta(seconds=latency_seconds)]
    if not eligible:
        return {"status": "MISSING_ENTRY"}
    entry = eligible[0]
    if (entry["received"] - threshold_cross_at).total_seconds() > latency_seconds + 3:
        return {"status": "ENTRY_QUOTE_GAP"}
    exit_quote = _at_or_after(quotes, entry["received"] + timedelta(seconds=hold_seconds))
    if exit_quote is None:
        return {"status": "MISSING_EXIT"}
    entry_price = entry["ask"] if signed == 1 else entry["bid"]
    exit_price = exit_quote["bid"] if signed == 1 else exit_quote["ask"]
    result_bps = signed * _bps(exit_price, entry_price)
    return {
        "status": "PAPER_BBO_PROXY_ONLY",
        "signal_direction": "LONG" if signed == 1 else "SHORT",
        "signal_received_at": threshold_cross_at.isoformat(),
        "entry_received_at": entry["received"].isoformat(),
        "exit_received_at": exit_quote["received"].isoformat(),
        "latency_seconds": latency_seconds, "hold_seconds": hold_seconds,
        "net_after_spread_bps": round(result_bps, 3),
        "caveat": "Not Saxo fills; excludes commissions, market impact and additional slippage.",
    }
