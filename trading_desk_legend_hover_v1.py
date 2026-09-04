from __future__ import annotations

import streamlit as st


_LEGEND_HOVER_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const liveKey = String(data.uirevision || '');
    const enhanced = new Map();
    let observer = null;

    function targetKind(graph) {
        const key = String(graph?.layout?.uirevision || '');
        if (key === liveKey) return 'live';
        if (key.startsWith('AutoManagerPnlProduct:')) return 'strategy';
        return null;
    }

    function traceFingerprint(graph) {
        return Array.from(graph?.data || []).map((trace, index) => [
            index,
            String(trace?.name || ''),
            String(trace?.type || ''),
            trace?.showlegend === false ? '0' : '1',
            String(trace?.visible ?? true),
        ].join(':')).join('|');
    }

    function originalOpacity(graph) {
        return Array.from(graph?.data || []).map((trace) => {
            const value = trace?.opacity;
            return value === undefined || value === null ? 1.0 : Number(value);
        });
    }

    function restore(graph, state) {
        if (!window.Plotly?.restyle || !graph) return;
        const indexes = state.opacity.map((_, index) => index);
        if (!indexes.length) return;
        window.Plotly.restyle(graph, { opacity: state.opacity.slice() }, indexes);
    }

    function highlight(graph, state, targetIndex) {
        if (!window.Plotly?.restyle || !graph || targetIndex == null) return;
        const currentFingerprint = traceFingerprint(graph);
        if (currentFingerprint !== state.fingerprint) {
            state.fingerprint = currentFingerprint;
            state.opacity = originalOpacity(graph);
        }
        const indexes = state.opacity.map((_, index) => index);
        const values = state.opacity.map((value, index) =>
            index === targetIndex ? Math.max(1.0, value) : Math.min(0.12, value)
        );
        window.Plotly.restyle(graph, { opacity: values }, indexes);
    }

    function legendTraceIndex(graph, legendItem) {
        const items = Array.from(graph.querySelectorAll('.legend .traces'));
        const ordinal = items.indexOf(legendItem);
        if (ordinal < 0) return null;
        const traceIndexes = Array.from(graph._fullData || [])
            .map((trace, index) => ({ trace, index }))
            .filter(({ trace }) => trace?.showlegend !== false && trace?.visible !== false)
            .map(({ index }) => index);
        return ordinal < traceIndexes.length ? traceIndexes[ordinal] : null;
    }

    function hideHoverPopup(graph) {
        const layer = graph.querySelector('.hoverlayer');
        if (layer) {
            layer.style.opacity = '0';
            layer.style.pointerEvents = 'none';
        }
    }

    function formatNumber(value, suffix = '') {
        const number = Number(value);
        if (!Number.isFinite(number)) return '—';
        let digits = 4;
        const abs = Math.abs(number);
        if (abs >= 1000) digits = 1;
        else if (abs >= 100) digits = 2;
        else if (abs >= 1) digits = 3;
        return number.toLocaleString('nb-NO', { maximumFractionDigits: digits }) + suffix;
    }

    function formatClock(value) {
        if (value == null) return '';
        const text = String(value);
        const match = text.match(/(?:T|\s)(\d{2}:\d{2})/);
        if (match) return match[1];
        const date = new Date(text);
        if (!Number.isFinite(date.getTime())) return text.slice(0, 5);
        return date.toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
    }

    function infoHost(graph) {
        return graph.closest('[data-testid="stPlotlyChart"]') || graph.parentElement;
    }

    function ensureInfoLine(graph) {
        const host = infoHost(graph);
        if (!host) return null;
        let line = host.querySelector(':scope > .pg-chart-click-info');
        if (!line) {
            line = document.createElement('div');
            line.className = 'pg-chart-click-info';
            Object.assign(line.style, {
                minHeight: '1.25rem',
                marginTop: '.2rem',
                padding: '0 .2rem',
                font: '500 12px/1.35 system-ui, -apple-system, sans-serif',
                color: '#4b5563',
                whiteSpace: 'normal',
            });
            host.appendChild(line);
        }
        return line;
    }

    function renderPointInfo(graph, point) {
        if (!point) return;
        const traceIndex = Number(point.curveNumber);
        const trace = graph.data?.[traceIndex];
        if (!trace) return;
        const pointIndex = Number(point.pointNumber ?? point.pointIndex ?? 0);
        const name = String(trace.name || 'Serie');
        const clock = formatClock(point.x);
        const pieces = [name];
        if (clock) pieces.push(clock);

        if (String(trace.type || '') === 'candlestick') {
            pieces.push(`O ${formatNumber(trace.open?.[pointIndex])}`);
            pieces.push(`H ${formatNumber(trace.high?.[pointIndex])}`);
            pieces.push(`L ${formatNumber(trace.low?.[pointIndex])}`);
            pieces.push(`C ${formatNumber(trace.close?.[pointIndex])}`);
        } else {
            const isPnl = String(graph.layout?.uirevision || '').startsWith('AutoManagerPnlProduct:');
            pieces.push(formatNumber(point.y, isPnl ? '%' : ''));
            const custom = point.customdata;
            if (typeof custom === 'string' && custom) pieces.push(custom);
            else if (Array.isArray(custom) && custom.length && typeof custom[0] === 'string') pieces.push(custom[0]);
        }
        const line = ensureInfoLine(graph);
        if (line) line.textContent = pieces.join(' · ');
    }

    function compactPresentation(graph, kind) {
        const plotly = window.Plotly;
        if (!plotly?.relayout) return;
        const updates = {};
        const layout = graph.layout || {};
        const xAxes = Object.keys(layout).filter((key) => /^xaxis\d*$/.test(key));
        for (const key of xAxes) {
            updates[`${key}.tickformat`] = '%H:%M';
            updates[`${key}.hoverformat`] = '%H:%M';
            const title = layout[key]?.title?.text;
            if (title) updates[`${key}.title.text`] = title.includes('Tid') ? 'Tid' : title;
        }
        if (kind === 'strategy') {
            updates['legend.orientation'] = 'v';
            updates['legend.yanchor'] = 'top';
            updates['legend.y'] = 1.0;
            updates['legend.xanchor'] = 'left';
            updates['legend.x'] = 1.01;
            updates['legend.maxheight'] = 0.52;
            updates['legend.title.text'] = 'Legend · hover / scroll';
            updates['legend.font.size'] = 11;
            updates['margin.r'] = Math.max(Number(layout.margin?.r || 0), 225);
        }
        plotly.relayout(graph, updates);

        if (kind === 'live' && plotly.restyle) {
            const candleIndexes = [];
            const lineIndexes = [];
            Array.from(graph.data || []).forEach((trace, index) => {
                if (trace?.type === 'candlestick') candleIndexes.push(index);
                if (trace?.type === 'scatter' && trace?.mode?.includes?.('lines')) lineIndexes.push(index);
            });
            if (candleIndexes.length) {
                plotly.restyle(graph, {
                    'increasing.line.width': 0.8,
                    'decreasing.line.width': 0.8,
                    'increasing.fillcolor': 'rgba(22,163,74,0.62)',
                    'decreasing.fillcolor': 'rgba(220,38,38,0.62)',
                    opacity: 0.94,
                }, candleIndexes);
            }
            for (const index of lineIndexes) {
                const width = Number(graph.data[index]?.line?.width || 1.2);
                if (width > 1.35) plotly.restyle(graph, { 'line.width': 1.35 }, [index]);
            }
        }
    }

    function dateRange(axis) {
        const range = axis?.range;
        if (!Array.isArray(range) || range.length !== 2) return null;
        const start = axis.d2c(range[0]);
        const end = axis.d2c(range[1]);
        return Number.isFinite(start) && Number.isFinite(end) && start !== end ? [start, end] : null;
    }

    function yRange(axis) {
        const range = axis?.range;
        if (!Array.isArray(range) || range.length !== 2) return null;
        const start = Number(range[0]);
        const end = Number(range[1]);
        return Number.isFinite(start) && Number.isFinite(end) && start !== end ? [start, end] : null;
    }

    function enhance(graph, kind) {
        if (!graph || enhanced.has(graph)) return;
        const state = {
            opacity: originalOpacity(graph),
            fingerprint: traceFingerprint(graph),
            wheelFrame: null,
            wheel: null,
        };
        enhanced.set(graph, state);
        compactPresentation(graph, kind);
        hideHoverPopup(graph);

        const onLegendOver = (event) => {
            const item = event.target?.closest?.('.legend .traces');
            if (!item || !graph.contains(item)) return;
            const from = event.relatedTarget?.closest?.('.legend .traces');
            if (from === item) return;
            highlight(graph, state, legendTraceIndex(graph, item));
        };
        const onLegendOut = (event) => {
            const item = event.target?.closest?.('.legend .traces');
            if (!item || !graph.contains(item)) return;
            const to = event.relatedTarget?.closest?.('.legend .traces');
            if (to === item) return;
            restore(graph, state);
        };
        const onPlotHover = (event) => {
            const point = event?.points?.[0];
            if (point) highlight(graph, state, Number(point.curveNumber));
            hideHoverPopup(graph);
        };
        const onPlotUnhover = () => restore(graph, state);
        const onPlotClick = (event) => renderPointInfo(graph, event?.points?.[0]);
        const onAfterPlot = () => hideHoverPopup(graph);

        function flushWheel() {
            state.wheelFrame = null;
            const gesture = state.wheel;
            state.wheel = null;
            if (!gesture || !window.Plotly?.relayout || kind !== 'live') return;
            const layout = graph._fullLayout;
            const xaxis = layout?.xaxis;
            const yaxis = layout?.yaxis;
            const size = layout?._size;
            if (!xaxis || !yaxis || !size) return;

            if (gesture.ctrl) {
                const range = dateRange(xaxis);
                if (!range) return;
                const [start, end] = range;
                const span = end - start;
                const rect = graph.getBoundingClientRect();
                const pixel = gesture.clientX - rect.left - size.l;
                const ratio = Math.max(0, Math.min(1, pixel / Math.max(1, size.w)));
                const anchor = start + span * ratio;
                const factor = Math.max(0.84, Math.min(1.18, Math.exp(gesture.dy * 0.0024)));
                const nextStart = anchor + (start - anchor) * factor;
                const nextEnd = anchor + (end - anchor) * factor;
                window.Plotly.relayout(graph, {
                    'xaxis.range': [new Date(nextStart).toISOString(), new Date(nextEnd).toISOString()],
                    'xaxis.autorange': false,
                });
                return;
            }

            if (Math.abs(gesture.dx) > Math.abs(gesture.dy)) {
                const range = dateRange(xaxis);
                if (!range) return;
                const [start, end] = range;
                const shift = (gesture.dx / Math.max(1, size.w)) * (end - start);
                window.Plotly.relayout(graph, {
                    'xaxis.range': [new Date(start + shift).toISOString(), new Date(end + shift).toISOString()],
                    'xaxis.autorange': false,
                });
                return;
            }

            const range = yRange(yaxis);
            if (!range) return;
            const [start, end] = range;
            const shift = (gesture.dy / Math.max(1, size.h)) * (end - start);
            window.Plotly.relayout(graph, {
                'yaxis.range': [start + shift, end + shift],
                'yaxis.autorange': false,
            });
        }

        const onWheel = (event) => {
            if (kind !== 'live') return;
            event.preventDefault();
            event.stopImmediatePropagation();
            const current = state.wheel || { dx: 0, dy: 0, ctrl: false, clientX: event.clientX };
            current.dx += Number(event.deltaX || 0);
            current.dy += Number(event.deltaY || 0);
            current.ctrl = current.ctrl || Boolean(event.ctrlKey || event.metaKey);
            current.clientX = event.clientX;
            state.wheel = current;
            if (!state.wheelFrame) state.wheelFrame = window.requestAnimationFrame(flushWheel);
        };

        graph.addEventListener('pointerover', onLegendOver);
        graph.addEventListener('pointerout', onLegendOut);
        graph.addEventListener('wheel', onWheel, { passive: false, capture: true });
        graph.on?.('plotly_hover', onPlotHover);
        graph.on?.('plotly_unhover', onPlotUnhover);
        graph.on?.('plotly_click', onPlotClick);
        graph.on?.('plotly_afterplot', onAfterPlot);

        state.cleanup = () => {
            graph.removeEventListener('pointerover', onLegendOver);
            graph.removeEventListener('pointerout', onLegendOut);
            graph.removeEventListener('wheel', onWheel, true);
            graph.removeListener?.('plotly_hover', onPlotHover);
            graph.removeListener?.('plotly_unhover', onPlotUnhover);
            graph.removeListener?.('plotly_click', onPlotClick);
            graph.removeListener?.('plotly_afterplot', onAfterPlot);
            if (state.wheelFrame) window.cancelAnimationFrame(state.wheelFrame);
            restore(graph, state);
        };
    }

    function scan() {
        const graphs = Array.from(document.querySelectorAll('.js-plotly-plot'));
        for (const graph of graphs) {
            const kind = targetKind(graph);
            if (kind) enhance(graph, kind);
        }
        for (const [graph, state] of Array.from(enhanced.entries())) {
            if (!document.body.contains(graph) || !targetKind(graph)) {
                state.cleanup?.();
                enhanced.delete(graph);
            }
        }
    }

    scan();
    observer = new MutationObserver(scan);
    observer.observe(document.body, { childList: true, subtree: true });

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        for (const state of enhanced.values()) state.cleanup?.();
        enhanced.clear();
    };
}
"""


_legend_hover_component = st.components.v2.component(
    "pricegauger_trading_desk_legend_hover_v1",
    js=_LEGEND_HOVER_JS,
    isolate_styles=False,
)


def render_trading_desk_legend_hover_v1(*, uirevision: str) -> None:
    """Install lightweight browser interactions for TradingDesk Plotly charts.

    Hover highlights the focused trace without opening Plotly's large tooltip layer;
    click leaves one compact information line below the chart. On the LIVE chart,
    trackpad pinch zooms only X, horizontal two-finger motion pans X, and vertical
    two-finger motion pans the price Y-axis. This is presentation-only behavior.
    """
    _legend_hover_component(
        key=f"pg-trading-desk-legend-hover:{uirevision}",
        data={"uirevision": str(uirevision)},
        height=0,
    )


__all__ = ["render_trading_desk_legend_hover_v1"]
