"""Aggregate, evidence-bound AI digests. No broker authority or raw account data."""
from __future__ import annotations
from hashlib import sha256
from math import isfinite
import json
import re
from typing import Mapping, Sequence


def prepare_metrics(metrics: Sequence[Mapping]) -> tuple[dict, ...]:
    result, seen = [], set()
    for item in metrics[:6]:
        key = str(item.get("id", ""))
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", key) or key in seen:
            raise ValueError("Ugyldig eller gjentatt analyseindikator")
        value, reference = float(item["value"]), float(item["reference"])
        if not isfinite(value) or not isfinite(reference) or reference <= 0:
            raise ValueError("Endelig måleverdi og positiv referanse kreves")
        seen.add(key)
        result.append({"id": key, "label": str(item["label"])[:100],
                       "value": round(value, 6), "unit": str(item.get("unit", ""))[:20],
                       "reference": round(reference, 6),
                       "reference_label": str(item.get("reference_label") or "visningsskala")[:120]})
    if not result:
        raise ValueError("Ingen numeriske analysefunn")
    return tuple(result)


def parse_ai_summary(raw: str, metrics: Sequence[Mapping]) -> dict:
    text = str(raw or "").strip()
    fence = chr(96)*3
    if text.startswith(fence):
        text = text.strip(chr(96)).removeprefix("json").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("AI-vurderingen mangler JSON-objekt")
    valid = {m["id"] for m in metrics}
    points, used = [], set()
    for p in payload.get("points", []):
        if not isinstance(p, dict):
            continue
        key, note = p.get("metric_id"), str(p.get("insight") or "").strip()[:400]
        if key in valid and key not in used and len(note) >= 10 and not re.search(r"\d", note):
            points.append({"metric_id": key, "insight": note})
            used.add(key)
    if not points:
        raise ValueError("AI-vurderingen har ingen verifiserbare indikatorreferanser")
    return {"title": str(payload.get("title") or "Funn fra data")[:140],
            "points": points[:4], "generated": True}


def summarize_metrics(*, title: str, metrics: Sequence[Mapping],
                      caveat: str, context: Mapping | None = None,
                      key: str | None = None, model: str | None = None, post=None) -> dict:
    clean = prepare_metrics(metrics)
    fallback = {"title": "Tallbasert oppsummering",
                "points": [{"metric_id": m["id"],
                            "insight": "Målt verdi fra valgt datasett; se grafen og forutsetningene."}
                           for m in clean[:4]], "generated": False}
    try:
        from config import openai_api_key, openai_market_model
        from strategy_lab_v2_ai import _call_responses_api, _response_text
        import requests
        token = key if key is not None else openai_api_key()
        if not token:
            return fallback
        body = {
            "model": model or openai_market_model(),
            "instructions": (
                "You are a skeptical Norwegian quantitative research analyst. "
                "Return only JSON with 'title' and 'points' array, each point "
                "containing a supplied 'metric_id' and a short 'insight'. "
                "Each insight must interpret the specific metric or flag a "
                "methodological limitation, not just repeat its label. "
                "Never include digits or numeric claims in insight text: "
                "the app renders verified values separately. "
                "No forecasting, Saxo verified fill claims, or LIVE trading advice. "
                "Pick up to three distinct metric IDs. JSON only."
            ),
            "input": [{"role": "user", "content": json.dumps({
                "analysis": str(title)[:140], "metrics": clean,
                "limitations": str(caveat)[:700], "context": dict(context or {}),
            }, ensure_ascii=False, allow_nan=False)}],
            "max_output_tokens": 1300, "store": False,
        }
        response = _call_responses_api(post or requests.post, token=token, body=body)
        return parse_ai_summary(_response_text(response), clean)
    except Exception:
        # API outages cannot invalidate a completed analysis.
        return fallback


def render_summary(*, scope: str, title: str, metrics: Sequence[Mapping],
                   caveat: str, context: Mapping | None = None) -> None:
    """Call inside an early st.empty().container() to render at the page top."""
    import streamlit as st
    clean = prepare_metrics(metrics)
    serialized = json.dumps([title, clean, caveat, dict(context or {})],
                            ensure_ascii=False, sort_keys=True, allow_nan=False)
    fingerprint = sha256(serialized.encode("utf-8")).hexdigest()
    cache_key = "analysis:digest:" + scope
    cached = st.session_state.get(cache_key)
    if not cached or cached.get("fingerprint") != fingerprint:
        with st.spinner("AI vurderer analyseresultatet"):
            report = summarize_metrics(title=title, metrics=clean, caveat=caveat,
                                       context=context)
        cached = {"fingerprint": fingerprint, "report": report}
        st.session_state[cache_key] = cached
    report = cached["report"]
    values = {m["id"]: m for m in clean}
    st.subheader("AI-vurdering · hovedfunn" if report["generated"]
                 else "Tallbasert sammendrag · AI utilgjengelig")
    st.markdown("**" + report["title"] + "**")
    for point in report["points"]:
        metric = values.get(point["metric_id"])
        if metric is None:
            continue
        st.markdown("**" + metric["label"] + "** — " + point["insight"])
        st.caption(f"Målt: {metric['value']:+,.3f} {metric['unit']} · "
                   f"referanse: {metric['reference']:,.3f} {metric['unit']} "
                   f"({metric['reference_label']}).")
        fraction = min(1., abs(metric["value"]) / metric["reference"])
        st.progress(fraction, text=f"Graf · {fraction*100:.1f} % av referansen")
    st.caption("Søylene viser absolutt målt størrelse mot oppgitt referanse. "
               "De er ikke en kvalitetsgrad, sannsynlighet eller handelsanbefaling.")
    st.caption(caveat)
    st.divider()
