from __future__ import annotations

import streamlit as st


_NAVIGATION_SYNC_JS = r"""
export default function(component) {
    const { parentElement } = component;
    const states = new Map();
    const viewRegistry = window.__pricegaugerPlotlyViews ||= new Map();
    let observer = null;

    function targetGraph(graph) {
        const key = String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
        return key.startsWith('TradingDesk:') || key.startsWith('AutoManagerPnlProduct:');
    }

    function viewKey(graph) {
        return String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
    }

    function snapshotView(graph) {
        const layout = graph?._fullLayout;
        if (!layout) return null;
        const ranges = {};
        for (const key of Object.keys(layout)) {
            if (!/^(xaxis|yaxis)\d*$/.test(key)) continue;
            const range = layout[key]?.range;
            if (!Array.isArray(range) || range.length !== 2) continue;
            ranges[key] = range.map((value) => value instanceof Date ? value.toISOString() : value);
        }
        return Object.keys(ranges).length ? { ranges } : null;
    }

    function rememberView(graph) {
        const key = viewKey(graph);
        const snapshot = snapshotView(graph);
        if (key && snapshot) viewRegistry.set(key, snapshot);
    }

    function pointerInsidePlot(graph, event) {
        const size = graph?._fullLayout?._size;
        if (!size) return false;
        const rect = graph.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;
        return x >= size.l && x <= size.l + size.w && y >= size.t && y <= size.t + size.h;
    }

    function enhance(graph) {
        if (!graph || states.has(graph) || !targetGraph(graph)) return;

        const state = {
            onPointerDown: null,
            onPointerUp: null,
            onRelayouting: null,
            onRelayout: null,
        };

        // The older persistence layer may restore its last saved range from
        // plotly_afterplot. During a fresh drag that saved range is stale until the
        // final plotly_relayout event arrives, which can visibly snap the chart back.
        // Clear it as soon as a genuine plot gesture begins, then continuously replace
        // it with the range Plotly is actually showing while the gesture is in flight.
        state.onPointerDown = (event) => {
            if (!pointerInsidePlot(graph, event)) return;
            const key = viewKey(graph);
            if (key) viewRegistry.delete(key);
        };
        state.onPointerUp = () => window.requestAnimationFrame(() => rememberView(graph));
        state.onRelayouting = () => rememberView(graph);
        state.onRelayout = () => rememberView(graph);

        graph.addEventListener('pointerdown', state.onPointerDown, { passive: true });
        graph.addEventListener('pointerup', state.onPointerUp, { passive: true });
        graph.addEventListener('pointercancel', state.onPointerUp, { passive: true });
        graph.on?.('plotly_relayouting', state.onRelayouting);
        graph.on?.('plotly_relayout', state.onRelayout);
        states.set(graph, state);
    }

    function cleanup(graph, state) {
        graph.removeEventListener('pointerdown', state.onPointerDown);
        graph.removeEventListener('pointerup', state.onPointerUp);
        graph.removeEventListener('pointercancel', state.onPointerUp);
        graph.removeListener?.('plotly_relayouting', state.onRelayouting);
        graph.removeListener?.('plotly_relayout', state.onRelayout);
    }

    function scan() {
        for (const graph of Array.from(document.querySelectorAll('.js-plotly-plot'))) enhance(graph);
        for (const [graph, state] of Array.from(states.entries())) {
            if (!document.body.contains(graph) || !targetGraph(graph)) {
                cleanup(graph, state);
                states.delete(graph);
            }
        }
    }

    scan();
    observer = new MutationObserver(scan);
    observer.observe(document.body, { childList: true, subtree: true });

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        for (const [graph, state] of states.entries()) cleanup(graph, state);
        states.clear();
    };
}
"""


_navigation_sync_component = st.components.v2.component(
    "pricegauger_tradingdesk_navigation_sync_v1",
    js=_NAVIGATION_SYNC_JS,
    isolate_styles=False,
)


def render_tradingdesk_navigation_sync_v1() -> None:
    """Keep user-driven Plotly pan/zoom authoritative during an active gesture.

    Presentation/browser state only. No Streamlit session writes and no execution,
    strategy, risk, sizing, Product Admission, or Saxo authority.
    """

    _navigation_sync_component(
        key="pg-tradingdesk-navigation-sync-v1",
        data={},
        height=0,
    )


__all__ = ["render_tradingdesk_navigation_sync_v1"]
