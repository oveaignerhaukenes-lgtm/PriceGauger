from __future__ import annotations

import streamlit as st

from tradingdesk_ui.charts.profile import responsive_chart_profile_payload_v1
from tradingdesk_ui.layout.responsive import render_tradingdesk_responsive_foundation_v1


_RESPONSIVE_CHART_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const profile = data.profile || {};
    const breakpoint = Number(profile.mobile_breakpoint_px || 760);
    const states = new Map();
    let mutationObserver = null;

    function chartKind(graph) {
        const key = String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
        if (key.startsWith('TradingDesk:')) return 'live';
        if (key.startsWith('AutoManagerPnlProduct:')) return 'strategy';
        return null;
    }

    function numberOr(value, fallback) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function captureDesktop(graph) {
        const layout = graph?.layout || {};
        const legend = layout.legend || {};
        const margin = layout.margin || {};
        return {
            height: numberOr(layout.height, 780),
            margin: {
                l: numberOr(margin.l, 60),
                r: numberOr(margin.r, 60),
                t: numberOr(margin.t, 60),
                b: numberOr(margin.b, 50),
            },
            legend: {
                orientation: legend.orientation || 'v',
                yanchor: legend.yanchor || 'top',
                y: legend.y ?? 1.0,
                xanchor: legend.xanchor || 'left',
                x: legend.x ?? 1.01,
                maxheight: legend.maxheight ?? 0.52,
                fontSize: numberOr(legend.font?.size, 11),
                title: legend.title?.text ?? 'Legend · hover / scroll',
            },
        };
    }

    function mobileUpdates(state, kind) {
        const desktop = state.desktop;
        return {
            height: desktop.height + numberOr(profile.mobile_height_extra_px, 200),
            'margin.l': numberOr(profile.mobile_left_margin_px, 46),
            'margin.r': numberOr(profile.mobile_right_margin_px, 16),
            'margin.t': numberOr(profile.mobile_top_margin_px, 96),
            'margin.b': kind === 'strategy'
                ? numberOr(profile.mobile_bottom_margin_strategy_px, 300)
                : numberOr(profile.mobile_bottom_margin_live_px, 280),
            'legend.orientation': 'h',
            'legend.yanchor': 'bottom',
            'legend.y': 1.02,
            'legend.xanchor': 'left',
            'legend.x': 0.0,
            'legend.maxheight': numberOr(profile.mobile_legend_maxheight, 0.10),
            'legend.font.size': numberOr(profile.mobile_legend_font_size, 10),
            'legend.title.text': '',
        };
    }

    function desktopUpdates(state) {
        const desktop = state.desktop;
        return {
            height: desktop.height,
            'margin.l': desktop.margin.l,
            'margin.r': desktop.margin.r,
            'margin.t': desktop.margin.t,
            'margin.b': desktop.margin.b,
            'legend.orientation': desktop.legend.orientation,
            'legend.yanchor': desktop.legend.yanchor,
            'legend.y': desktop.legend.y,
            'legend.xanchor': desktop.legend.xanchor,
            'legend.x': desktop.legend.x,
            'legend.maxheight': desktop.legend.maxheight,
            'legend.font.size': desktop.legend.fontSize,
            'legend.title.text': desktop.legend.title,
        };
    }

    function positionInspector(graph, state, kind) {
        const panel = graph?.querySelector?.(':scope > .pg-chart-inspector');
        if (!panel) return;
        if (state.mode !== 'mobile') return;
        const layout = graph?._fullLayout;
        const size = layout?._size;
        const rect = graph.getBoundingClientRect();
        if (!size || !rect.width) return;
        const gap = kind === 'strategy'
            ? numberOr(profile.mobile_inspector_gap_strategy_px, 125)
            : numberOr(profile.mobile_inspector_gap_live_px, 105);
        const top = size.t + size.h + gap;
        panel.style.position = 'absolute';
        panel.style.left = '8px';
        panel.style.top = `${Math.round(top)}px`;
        panel.style.width = `${Math.max(120, Math.round(rect.width - 16))}px`;
        panel.style.maxHeight = `${Math.max(76, Math.round(rect.height - top - 8))}px`;
        panel.style.boxSizing = 'border-box';
        panel.style.zIndex = '8';
    }

    function applyProfile(graph, state, kind) {
        if (!graph || !window.Plotly?.relayout) return;
        const width = graph.getBoundingClientRect().width;
        if (!Number.isFinite(width) || width <= 0) return;
        const mode = width <= breakpoint ? 'mobile' : 'desktop';
        if (state.mode === mode) {
            positionInspector(graph, state, kind);
            return;
        }
        state.mode = mode;
        const updates = mode === 'mobile' ? mobileUpdates(state, kind) : desktopUpdates(state);
        Promise.resolve(window.Plotly.relayout(graph, updates)).finally(() => {
            window.Plotly?.Plots?.resize?.(graph);
            positionInspector(graph, state, kind);
        });
    }

    function enhance(graph) {
        const kind = chartKind(graph);
        if (!kind || states.has(graph)) return;
        const state = {
            desktop: captureDesktop(graph),
            mode: null,
            resizeObserver: null,
            afterPlot: null,
        };
        states.set(graph, state);
        state.afterPlot = () => positionInspector(graph, state, kind);
        graph.on?.('plotly_afterplot', state.afterPlot);
        if (window.ResizeObserver) {
            state.resizeObserver = new ResizeObserver(() => applyProfile(graph, state, kind));
            state.resizeObserver.observe(graph);
        }
        window.requestAnimationFrame(() => applyProfile(graph, state, kind));
    }

    function cleanupGraph(graph, state) {
        state.resizeObserver?.disconnect?.();
        if (state.afterPlot) graph.removeListener?.('plotly_afterplot', state.afterPlot);
    }

    function scan() {
        for (const graph of Array.from(document.querySelectorAll('.js-plotly-plot'))) enhance(graph);
        for (const [graph, state] of Array.from(states.entries())) {
            if (!document.body.contains(graph) || !chartKind(graph)) {
                cleanupGraph(graph, state);
                states.delete(graph);
            }
        }
    }

    scan();
    mutationObserver = new MutationObserver(scan);
    mutationObserver.observe(document.body, { childList: true, subtree: true });
    window.addEventListener('orientationchange', scan);

    parentElement.style.display = 'none';
    return () => {
        mutationObserver?.disconnect();
        window.removeEventListener('orientationchange', scan);
        for (const [graph, state] of states.entries()) cleanupGraph(graph, state);
        states.clear();
    };
}
"""


_responsive_chart_component = st.components.v2.component(
    "pricegauger_tradingdesk_responsive_charts_v1",
    js=_RESPONSIVE_CHART_JS,
    isolate_styles=False,
)


def render_tradingdesk_responsive_runtime_v1() -> None:
    """Install narrow-screen layout and Plotly presentation adaptation.

    This is strictly presentation state. It never reads or writes orders, strategy
    authority, Saxo identity, sizing, or risk state.
    """

    render_tradingdesk_responsive_foundation_v1()
    _responsive_chart_component(
        key="pg-tradingdesk-responsive-runtime-v1",
        data={"profile": responsive_chart_profile_payload_v1()},
        height=0,
    )


__all__ = ["render_tradingdesk_responsive_runtime_v1"]
