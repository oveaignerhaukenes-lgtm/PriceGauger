from __future__ import annotations

import streamlit as st


_LEGEND_HOVER_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const registryKey = String(data.uirevision || '');
    let graph = null;
    let observer = null;
    let originalOpacity = [];
    let traceFingerprint = '';

    function findGraph() {
        return Array.from(document.querySelectorAll('.js-plotly-plot')).find(
            (candidate) => String(candidate?.layout?.uirevision || '') === registryKey
        ) || null;
    }

    function currentTraceFingerprint(candidate) {
        return Array.from(candidate?.data || []).map((trace, index) => [
            index,
            String(trace?.name || ''),
            trace?.showlegend === false ? '0' : '1',
            String(trace?.visible ?? true),
        ].join(':')).join('|');
    }

    function captureOpacity(candidate) {
        const fingerprint = currentTraceFingerprint(candidate);
        if (candidate !== graph || fingerprint !== traceFingerprint) {
            originalOpacity = Array.from(candidate?.data || []).map((trace) => {
                const value = trace?.opacity;
                return value === undefined || value === null ? 1.0 : Number(value);
            });
            traceFingerprint = fingerprint;
        }
    }

    function restyleOpacity(values, indexes) {
        const plotly = window.Plotly;
        if (!plotly?.restyle || !graph || !indexes.length) return;
        plotly.restyle(graph, { opacity: values }, indexes);
    }

    function restore() {
        if (!graph) return;
        const indexes = originalOpacity.map((_, index) => index);
        restyleOpacity(originalOpacity.slice(), indexes);
    }

    function highlightedTraceIndex(legendItem) {
        if (!graph || !legendItem) return null;
        const legendItems = Array.from(graph.querySelectorAll('.legend .traces'));
        const ordinal = legendItems.indexOf(legendItem);
        if (ordinal < 0) return null;
        const traceIndexes = Array.from(graph._fullData || []).map((trace, index) => ({ trace, index }))
            .filter(({ trace }) => trace?.showlegend !== false && trace?.visible !== false)
            .map(({ index }) => index);
        return ordinal < traceIndexes.length ? traceIndexes[ordinal] : null;
    }

    function onPointerOver(event) {
        const item = event.target?.closest?.('.legend .traces');
        if (!item || !graph?.contains(item)) return;
        const from = event.relatedTarget?.closest?.('.legend .traces');
        if (from === item) return;
        captureOpacity(graph);
        const targetIndex = highlightedTraceIndex(item);
        if (targetIndex === null) return;
        const indexes = originalOpacity.map((_, index) => index);
        const dimmed = originalOpacity.map((value, index) => index === targetIndex ? Math.max(1.0, value) : Math.min(0.14, value));
        restyleOpacity(dimmed, indexes);
    }

    function onPointerOut(event) {
        const item = event.target?.closest?.('.legend .traces');
        if (!item || !graph?.contains(item)) return;
        const to = event.relatedTarget?.closest?.('.legend .traces');
        if (to === item) return;
        restore();
    }

    function detach() {
        if (!graph) return;
        graph.removeEventListener('pointerover', onPointerOver);
        graph.removeEventListener('pointerout', onPointerOut);
        restore();
        graph = null;
    }

    function attach(candidate) {
        if (!candidate || candidate === graph) return;
        detach();
        graph = candidate;
        traceFingerprint = '';
        captureOpacity(graph);
        graph.addEventListener('pointerover', onPointerOver);
        graph.addEventListener('pointerout', onPointerOut);
    }

    attach(findGraph());
    observer = new MutationObserver(() => attach(findGraph()));
    observer.observe(document.body, { childList: true, subtree: true });

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        detach();
    };
}
"""


_legend_hover_component = st.components.v2.component(
    "pricegauger_trading_desk_legend_hover_v1",
    js=_LEGEND_HOVER_JS,
    isolate_styles=False,
)


def render_trading_desk_legend_hover_v1(*, uirevision: str) -> None:
    """Highlight one Plotly trace while its visible legend item is hovered.

    This is browser-only presentation behavior. It never mutates chart data,
    persisted state, strategy state, signal state or execution authority.
    """
    _legend_hover_component(
        key=f"pg-trading-desk-legend-hover:{uirevision}",
        data={"uirevision": str(uirevision)},
        height=0,
    )


__all__ = ["render_trading_desk_legend_hover_v1"]
