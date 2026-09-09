from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.lightweight import contract as _contract
from tradingdesk_ui.charts.lightweight import direct_runtime as _runtime


_INSTALLED = False
_ORIGINAL_MARKER_PAYLOAD = _contract._marker_payload


def _stable_trade_marker_payload_v1(*args, **kwargs):
    """Keep initial/base-refresh marker colors identical to the 1s live overlay."""
    result = _ORIGINAL_MARKER_PAYLOAD(*args, **kwargs)
    for item in result:
        direction = str(item.get("direction") or "").upper()
        if direction == "LONG":
            item["color"] = "#0ea5e9"
        elif direction == "SHORT":
            item["color"] = "#f59e0b"
    return result


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"TradingDesk continuity patch anchor missing: {label}")
    return source.replace(old, new)


def install_chart_runtime_continuity_v1() -> None:
    """Make scheduled chart refreshes update an existing LWC instance in place.

    Streamlit fragment reruns can replace the component wrapper even when chart
    semantics have not changed. The old direct runtime interpreted a new wrapper as
    a new chart and destroyed/rebuilt Lightweight Charts. On mobile that produced a
    visible blank/default-size flash, reset pane geometry until the 1s overlay
    restored it, changed trade-marker colors, and could block gestures while all
    series were synchronously repopulated.

    This presentation-only patch keeps the registered chart root alive across
    same-signature wrapper replacement, restores persisted geometry before paint,
    and defers the heavy setData refresh to browser idle time. A genuine signature
    change (timeframe/indicator/pane contract) still performs a deterministic rebuild.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    js = str(_runtime._DIRECT_LIVE_JS)

    js = _replace_required(
        js,
        "    const registry = window.__pricegaugerLightweightCharts ||= new Map();\n\n    function loadLibrary() {",
        """    const registry = window.__pricegaugerLightweightCharts ||= new Map();
    const geometryKey = `pg:tradingdesk:lightweight-geometry:v1:${chartId}`;

    function readSavedGeometry() {
        try {
            const raw = window.localStorage?.getItem(geometryKey);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : null;
        } catch (_) {
            return null;
        }
    }

    function preferredHeight() {
        const saved = readSavedGeometry();
        const raw = Number(saved?.height);
        if (Number.isFinite(raw) && raw >= 240) return Math.max(320, Math.min(1400, raw));
        return Math.max(320, Number(payload.height || 780));
    }

    function applySavedPaneGeometry(chart) {
        const saved = readSavedGeometry();
        const ratios = Array.isArray(saved?.pane_ratios) ? saved.pane_ratios : null;
        if (!ratios?.length) return;
        window.requestAnimationFrame(() => {
            try {
                const panes = Array.from(chart?.panes?.() || []);
                if (!panes.length || panes.length !== ratios.length) return;
                const total = panes.reduce((sum, pane) => sum + Math.max(0, Number(pane?.getHeight?.() || 0)), 0);
                if (!total) return;
                panes.forEach((pane, index) => {
                    const ratio = Math.max(.04, Number(ratios[index] || 0));
                    pane?.setHeight?.(Math.max(52, total * ratio));
                });
            } catch (_) {}
        });
    }

    function loadLibrary() {""",
        label="geometry helper",
    )

    js = _replace_required(
        js,
        "        parentElement.style.height = `${Math.max(320, Number(payload.height || 780))}px`;",
        "        parentElement.style.height = `${preferredHeight()}px`;",
        label="initial height",
    )
    js = _replace_required(
        js,
        "        entry.parent.style.height = `${Math.max(320, Number(payload.height || 780))}px`;",
        "        entry.parent.style.height = `${preferredHeight()}px`;",
        label="refresh height",
    )

    js = _replace_required(
        js,
        """        if (panes.length === 1) {
            panes[0]?.setStretchFactor?.(1);
        } else {
            panes[0]?.setStretchFactor?.(priceShare);
            const remainder = (1 - priceShare) / Math.max(1, panes.length - 1);
            for (let index = 1; index < panes.length; index += 1) panes[index]?.setStretchFactor?.(remainder);
        }

        chart.subscribeCrosshairMove""",
        """        if (panes.length === 1) {
            panes[0]?.setStretchFactor?.(1);
        } else {
            panes[0]?.setStretchFactor?.(priceShare);
            const remainder = (1 - priceShare) / Math.max(1, panes.length - 1);
            for (let index = 1; index < panes.length; index += 1) panes[index]?.setStretchFactor?.(remainder);
        }
        applySavedPaneGeometry(chart);

        chart.subscribeCrosshairMove""",
        label="saved pane ratios",
    )

    js = _replace_required(
        js,
        """        const sameParent = entry && entry.parent === parentElement && document.body.contains(entry.root);
        const sameSignature = entry && entry.signature === String(payload.signature || '');
        if (entry && (!sameParent || !sameSignature)) {""",
        """        const sameSignature = entry && entry.signature === String(payload.signature || '');
        if (entry && sameSignature && entry.parent !== parentElement) {
            // Streamlit replaced only the fragment wrapper. Reparent the existing
            // chart root instead of destroying the chart and flashing a fresh one.
            parentElement.replaceChildren();
            parentElement.style.width = '100%';
            parentElement.style.height = `${preferredHeight()}px`;
            parentElement.style.minWidth = '0';
            parentElement.style.position = 'relative';
            parentElement.style.overflow = 'hidden';
            parentElement.appendChild(entry.root);
            entry.parent = parentElement;
        }
        const sameParent = entry && entry.parent === parentElement && document.body.contains(entry.root);
        if (entry && (!sameParent || !sameSignature)) {""",
        label="same-signature reparent",
    )

    js = _replace_required(
        js,
        """        updateEntry(entry);
    }).catch((error) => {""",
        """        const refresh = () => {
            try { updateEntry(entry); } catch (_) {}
        };
        // Keep pan/zoom/touch responsive while the periodic canonical payload is
        // arriving. The existing chart remains visible until the browser is idle.
        if (typeof window.requestIdleCallback === 'function') {
            window.requestIdleCallback(refresh, { timeout: 1200 });
        } else {
            window.setTimeout(refresh, 0);
        }
    }).catch((error) => {""",
        label="idle refresh",
    )

    _contract._marker_payload = _stable_trade_marker_payload_v1
    _runtime._direct_live_component = st.components.v2.component(
        "pricegauger_tradingdesk_lightweight_direct_live_continuous_v1",
        js=js,
        isolate_styles=False,
    )
    _INSTALLED = True


install_chart_runtime_continuity_v1()


__all__ = ["install_chart_runtime_continuity_v1"]
