from __future__ import annotations

import streamlit as st


_PRESENTATION_CLEANUP_JS = r"""
export default function(component) {
    const { parentElement } = component;
    const bound = new WeakMap();
    let observer = null;
    let timer = null;

    function legendFor(entry) {
        const root = entry?.root;
        if (!root) return null;
        return Array.from(root.children).find((node) => {
            if (!(node instanceof HTMLElement)) return false;
            return node.style?.position === 'absolute' && node.style?.pointerEvents === 'none';
        }) || null;
    }

    function cleanEntry(entry) {
        if (!entry?.root || !document.body.contains(entry.root)) return;

        // Keep only the current candle price permanently visible. Indicator/overlay
        // names and last-value chips are available through the inspector instead of
        // occupying the plot and price scale all the time.
        try {
            entry.candles?.applyOptions?.({ title: '', lastValueVisible: true });
        } catch (_) {}
        for (const series of Array.from(entry.apis || [])) {
            try {
                series?.applyOptions?.({ title: '', lastValueVisible: false, priceLineVisible: false });
            } catch (_) {}
        }

        const legend = legendFor(entry);
        if (!legend || bound.has(entry.root)) return;
        legend.style.opacity = '0';
        legend.style.transition = 'opacity 90ms ease';
        legend.style.maxWidth = 'calc(100% - 16px)';
        legend.style.fontSize = '10px';
        legend.style.padding = '3px 6px';

        let hideTimer = null;
        const show = () => {
            if (hideTimer) window.clearTimeout(hideTimer);
            legend.style.opacity = '1';
        };
        const hideSoon = () => {
            if (hideTimer) window.clearTimeout(hideTimer);
            hideTimer = window.setTimeout(() => { legend.style.opacity = '0'; }, 500);
        };
        const hide = () => {
            if (hideTimer) window.clearTimeout(hideTimer);
            legend.style.opacity = '0';
        };

        entry.root.addEventListener('pointermove', show, { passive: true });
        entry.root.addEventListener('pointerdown', show, { passive: true });
        entry.root.addEventListener('pointerup', hideSoon, { passive: true });
        entry.root.addEventListener('pointercancel', hideSoon, { passive: true });
        entry.root.addEventListener('pointerleave', hide, { passive: true });
        bound.set(entry.root, { show, hideSoon, hide });
    }

    function scan() {
        const registry = window.__pricegaugerLightweightPlotlyBridge;
        if (!registry?.values) return;
        for (const entry of registry.values()) cleanEntry(entry);
    }

    scan();
    observer = new MutationObserver(scan);
    observer.observe(document.body, { childList: true, subtree: true });
    timer = window.setInterval(scan, 1000);

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        if (timer) window.clearInterval(timer);
    };
}
"""


_cleanup_component = st.components.v2.component(
    "pricegauger_lightweight_presentation_cleanup_v1",
    js=_PRESENTATION_CLEANUP_JS,
    isolate_styles=False,
)


def render_lightweight_presentation_cleanup_v1() -> None:
    """Declutter the transitional Lightweight LIVE chart in browser presentation only."""

    _cleanup_component(
        key="pg-lightweight-presentation-cleanup-v1",
        data={},
        height=0,
    )


__all__ = ["render_lightweight_presentation_cleanup_v1"]
