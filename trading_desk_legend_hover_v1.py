from __future__ import annotations

import streamlit as st


_LEGEND_HOVER_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const liveKey = String(data.uirevision || '');
    const enhanced = new Map();
    const viewRegistry = window.__pricegaugerPlotlyViews ||= new Map();
    let observer = null;

    function targetKind(graph) {
        const key = String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
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
        if (indexes.length) window.Plotly.restyle(graph, { opacity: state.opacity.slice() }, indexes);
    }

    function highlight(graph, state, targetIndex) {
        if (!window.Plotly?.restyle || targetIndex == null) return;
        const fingerprint = traceFingerprint(graph);
        if (fingerprint !== state.fingerprint) {
            state.fingerprint = fingerprint;
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

    function xMillis(value) {
        if (value instanceof Date) return value.getTime();
        if (typeof value === 'number' && Number.isFinite(value)) return value;
        const parsed = new Date(String(value)).getTime();
        return Number.isFinite(parsed) ? parsed : NaN;
    }

    function formatTimestamp(value) {
        const millis = xMillis(value);
        if (!Number.isFinite(millis)) return String(value ?? '');
        return new Date(millis).toLocaleString('nb-NO', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function viewKey(graph) {
        return String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
    }

    function isNavigationRelayout(eventData) {
        return Object.keys(eventData || {}).some((key) =>
            /^(xaxis|yaxis)\d*\.(range(?:\[\d\])?|autorange)$/.test(key)
        );
    }

    function snapshotBrowserView(graph) {
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

    function rangeScalar(axisKey, value) {
        if (axisKey.startsWith('xaxis')) return xMillis(value);
        const number = Number(value);
        return Number.isFinite(number) ? number : NaN;
    }

    function sameRange(axisKey, left, right) {
        if (!Array.isArray(left) || !Array.isArray(right) || left.length !== 2 || right.length !== 2) return false;
        return left.every((value, index) => {
            const a = rangeScalar(axisKey, value);
            const b = rangeScalar(axisKey, right[index]);
            if (!Number.isFinite(a) || !Number.isFinite(b)) return String(value) === String(right[index]);
            const scale = axisKey.startsWith('xaxis') ? 1 : Math.max(1, Math.abs(a), Math.abs(b));
            const tolerance = axisKey.startsWith('xaxis') ? 1 : scale * 1e-9;
            return Math.abs(a - b) <= tolerance;
        });
    }

    function browserViewAlreadyApplied(graph, saved) {
        const layout = graph?._fullLayout;
        if (!layout || !saved?.ranges) return true;
        return Object.entries(saved.ranges).every(([axisKey, range]) =>
            sameRange(axisKey, layout[axisKey]?.range, range)
        );
    }

    function applyBrowserView(graph, state) {
        const key = viewKey(graph);
        const saved = key ? viewRegistry.get(key) : null;
        if (!saved || state.restoringView || !window.Plotly?.relayout || browserViewAlreadyApplied(graph, saved)) return;
        const updates = {};
        for (const [axisKey, range] of Object.entries(saved.ranges || {})) {
            if (!Array.isArray(range) || range.length !== 2 || !graph?._fullLayout?.[axisKey]) continue;
            updates[`${axisKey}.range`] = range.slice();
            updates[`${axisKey}.autorange`] = false;
        }
        if (!Object.keys(updates).length) return;
        state.restoringView = true;
        Promise.resolve(window.Plotly.relayout(graph, updates)).finally(() => {
            state.restoringView = false;
        });
    }

    function plotGeometry(graph) {
        const layout = graph?._fullLayout;
        const size = layout?._size;
        if (!layout || !size) return null;
        return { layout, size, rect: graph.getBoundingClientRect() };
    }

    function localPoint(graph, clientX, clientY) {
        const geometry = plotGeometry(graph);
        if (!geometry) return null;
        return {
            geometry,
            x: clientX - geometry.rect.left,
            y: clientY - geometry.rect.top,
        };
    }

    function pointerInsidePlot(graph, clientX, clientY) {
        const point = localPoint(graph, clientX, clientY);
        if (!point) return false;
        const { size } = point.geometry;
        return point.x >= size.l && point.x <= size.l + size.w &&
            point.y >= size.t && point.y <= size.t + size.h;
    }

    function axisKeyFromTraceRef(ref) {
        const value = String(ref || 'y');
        return value === 'y' ? 'yaxis' : `yaxis${value.slice(1)}`;
    }

    function priceYAxis(graph) {
        const layout = graph?._fullLayout;
        if (!layout) return null;
        const candle = Array.from(graph?._fullData || graph?.data || []).find(
            (trace) => String(trace?.type || '') === 'candlestick' && trace?.visible !== false
        );
        const key = axisKeyFromTraceRef(candle?.yaxis || 'y');
        const axis = layout[key];
        return axis ? { key, axis } : (layout.yaxis ? { key: 'yaxis', axis: layout.yaxis } : null);
    }

    function visibleYAxisCandidates(graph) {
        const layout = graph?._fullLayout;
        if (!layout) return [];
        return Object.keys(layout)
            .filter((key) => /^yaxis\d*$/.test(key))
            .map((key) => ({ key, axis: layout[key] }))
            .filter(({ axis }) => axis && axis.visible !== false);
    }

    function pointerAxisTarget(graph, clientX, clientY) {
        const point = localPoint(graph, clientX, clientY);
        if (!point) return null;
        const { size } = point.geometry;
        if (point.y < size.t || point.y > size.t + size.h) return null;
        const leftDistance = size.l - point.x;
        const rightDistance = point.x - (size.l + size.w);
        let side = null;
        if (leftDistance >= -8 && leftDistance <= 72) side = 'left';
        if (rightDistance >= -8 && rightDistance <= 72) side = 'right';
        if (!side) return null;

        const price = priceYAxis(graph);
        const candidates = visibleYAxisCandidates(graph).filter(({ axis }) =>
            String(axis.side || 'left') === side
        );
        if (price && String(price.axis.side || 'left') === side) return price;
        return candidates[0] || price;
    }

    function pointerXValue(graph, clientX) {
        const geometry = plotGeometry(graph);
        const axis = geometry?.layout?.xaxis;
        if (!geometry || !axis?.p2c) return NaN;
        const pixel = clientX - geometry.rect.left - geometry.size.l;
        if (pixel < 0 || pixel > geometry.size.w) return NaN;
        return Number(axis.p2c(pixel));
    }

    function ensureCrosshair(graph) {
        let line = graph.querySelector(':scope > .pg-linked-crosshair');
        if (!line) {
            line = document.createElement('div');
            line.className = 'pg-linked-crosshair';
            Object.assign(line.style, {
                position: 'absolute', width: '1px', background: 'rgba(17,24,39,.34)',
                pointerEvents: 'none', display: 'none', zIndex: '7',
            });
            graph.style.position = 'relative';
            graph.appendChild(line);
        }
        return line;
    }

    function hideLinkedCrosshairs() {
        for (const graph of enhanced.keys()) {
            const line = graph.querySelector(':scope > .pg-linked-crosshair');
            if (line) line.style.display = 'none';
        }
    }

    function showLinkedCrosshairs(sourceGraph, clientX) {
        const sourceGeometry = plotGeometry(sourceGraph);
        const sourceAxis = sourceGeometry?.layout?.xaxis;
        if (!sourceGeometry || !sourceAxis?.p2c) return NaN;
        const sourcePixel = clientX - sourceGeometry.rect.left - sourceGeometry.size.l;
        if (sourcePixel < 0 || sourcePixel > sourceGeometry.size.w) {
            hideLinkedCrosshairs();
            return NaN;
        }
        const xValue = sourceAxis.p2c(sourcePixel);
        if (!Number.isFinite(xValue)) return NaN;
        for (const graph of enhanced.keys()) {
            const geometry = plotGeometry(graph);
            const axis = geometry?.layout?.xaxis;
            if (!geometry || !axis?.c2p) continue;
            const pixel = axis.c2p(xValue);
            const line = ensureCrosshair(graph);
            if (!Number.isFinite(pixel) || pixel < 0 || pixel > geometry.size.w) {
                line.style.display = 'none';
                continue;
            }
            line.style.left = `${geometry.size.l + pixel}px`;
            line.style.top = `${geometry.size.t}px`;
            line.style.height = `${geometry.size.h}px`;
            line.style.display = 'block';
        }
        return Number(xValue);
    }

    function ensureInspector(graph) {
        let panel = graph.querySelector(':scope > .pg-chart-inspector');
        if (!panel) {
            panel = document.createElement('div');
            panel.className = 'pg-chart-inspector';
            Object.assign(panel.style, {
                position: 'absolute', zIndex: '6', boxSizing: 'border-box',
                border: '1px solid rgba(17,24,39,.12)', borderRadius: '6px',
                background: 'rgba(255,255,255,.96)', color: '#374151',
                font: '500 11px/1.35 system-ui, -apple-system, sans-serif',
                padding: '7px 8px', pointerEvents: 'none', overflowY: 'auto',
                overflowX: 'hidden', boxShadow: '0 1px 2px rgba(17,24,39,.04)',
            });
            graph.style.position = 'relative';
            graph.appendChild(panel);
        }
        positionInspector(graph, panel);
        return panel;
    }

    function positionInspector(graph, panel = null) {
        const target = panel || graph.querySelector(':scope > .pg-chart-inspector');
        const geometry = plotGeometry(graph);
        if (!target || !geometry) return;
        const { size, rect } = geometry;
        let left = size.l + size.w + 12;
        let top = size.t + Math.max(110, size.h * 0.56);
        const legend = graph.querySelector('.legend');
        if (legend) {
            const legendRect = legend.getBoundingClientRect();
            const candidateLeft = legendRect.left - rect.left;
            const candidateTop = legendRect.bottom - rect.top + 8;
            if (Number.isFinite(candidateLeft) && candidateLeft >= size.l + size.w - 4) left = candidateLeft;
            if (Number.isFinite(candidateTop) && candidateTop > size.t) top = candidateTop;
        }
        const availableWidth = Math.max(118, rect.width - left - 8);
        const availableHeight = Math.max(78, rect.height - top - 8);
        target.style.left = `${Math.round(left)}px`;
        target.style.top = `${Math.round(top)}px`;
        target.style.width = `${Math.round(Math.min(202, availableWidth))}px`;
        target.style.maxHeight = `${Math.round(availableHeight)}px`;
    }

    function nearestIndex(trace, targetMillis) {
        const xs = Array.from(trace?.x || []);
        if (!xs.length || !Number.isFinite(targetMillis)) return null;
        let low = 0;
        let high = xs.length - 1;
        while (low < high) {
            const mid = Math.floor((low + high) / 2);
            const value = xMillis(xs[mid]);
            if (!Number.isFinite(value) || value < targetMillis) low = mid + 1;
            else high = mid;
        }
        const candidates = [low, low - 1].filter((index) => index >= 0 && index < xs.length);
        let best = null;
        for (const index of candidates) {
            const value = xMillis(xs[index]);
            if (!Number.isFinite(value)) continue;
            const distance = Math.abs(value - targetMillis);
            if (best === null || distance < best.distance) best = { index, millis: value, distance };
        }
        return best;
    }

    function nearestAnchor(graph, targetMillis) {
        let best = null;
        const traces = Array.from(graph?.data || []);
        const preferred = traces.find((trace) => trace?.type === 'candlestick' && trace?.visible !== false);
        const candidates = preferred ? [preferred, ...traces.filter((trace) => trace !== preferred)] : traces;
        for (const trace of candidates) {
            if (trace?.visible === false || trace?.visible === 'legendonly') continue;
            const nearest = nearestIndex(trace, targetMillis);
            if (!nearest) continue;
            if (preferred && trace === preferred) return nearest.millis;
            if (best === null || nearest.distance < best.distance) best = nearest;
        }
        return best?.millis ?? NaN;
    }

    function customSummary(value) {
        if (typeof value === 'string' && value) return value;
        if (!Array.isArray(value) || !value.length) return '';
        const text = value.find((item) => typeof item === 'string' && item);
        return text ? String(text) : '';
    }

    function inspectorRows(graph, anchorMillis) {
        const rows = [];
        const isPnl = String(graph.layout?.uirevision || '').startsWith('AutoManagerPnlProduct:');
        for (const trace of Array.from(graph?.data || [])) {
            if (trace?.visible === false || trace?.visible === 'legendonly') continue;
            const nearest = nearestIndex(trace, anchorMillis);
            if (!nearest) continue;
            const index = nearest.index;
            const name = String(trace?.name || 'Serie');
            if (String(trace?.type || '') === 'candlestick') {
                rows.push({
                    name,
                    value: `O ${formatNumber(trace.open?.[index])}  H ${formatNumber(trace.high?.[index])}  L ${formatNumber(trace.low?.[index])}  C ${formatNumber(trace.close?.[index])}`,
                    extra: '',
                });
                continue;
            }
            const number = Number(trace?.y?.[index]);
            if (!Number.isFinite(number)) continue;
            rows.push({
                name,
                value: formatNumber(number, isPnl ? '%' : ''),
                extra: customSummary(trace?.customdata?.[index]),
            });
        }
        return rows.slice(0, 16);
    }

    function renderInspector(graph, targetX) {
        const targetMillis = Number(targetX);
        if (!Number.isFinite(targetMillis)) return;
        const anchorMillis = nearestAnchor(graph, targetMillis);
        if (!Number.isFinite(anchorMillis)) return;
        const panel = ensureInspector(graph);
        panel.replaceChildren();
        const header = document.createElement('div');
        header.textContent = formatTimestamp(anchorMillis);
        Object.assign(header.style, {
            fontWeight: '700', color: '#111827', marginBottom: '5px',
            paddingBottom: '4px', borderBottom: '1px solid rgba(17,24,39,.10)',
        });
        panel.appendChild(header);
        const rows = inspectorRows(graph, anchorMillis);
        if (!rows.length) {
            const empty = document.createElement('div');
            empty.textContent = 'Ingen verdi ved markøren';
            empty.style.color = '#6b7280';
            panel.appendChild(empty);
            return;
        }
        for (const row of rows) {
            const item = document.createElement('div');
            item.style.marginBottom = '5px';
            const name = document.createElement('div');
            name.textContent = row.name;
            Object.assign(name.style, { color: '#6b7280', fontSize: '10px', lineHeight: '1.2' });
            const value = document.createElement('div');
            value.textContent = row.value;
            Object.assign(value.style, { color: '#1f2937', fontWeight: '600', overflowWrap: 'anywhere' });
            item.appendChild(name);
            item.appendChild(value);
            if (row.extra) {
                const extra = document.createElement('div');
                extra.textContent = row.extra;
                Object.assign(extra.style, { color: '#6b7280', fontSize: '10px' });
                item.appendChild(extra);
            }
            panel.appendChild(item);
        }
    }

    function renderInspectorsAtX(xValue) {
        if (!Number.isFinite(Number(xValue))) return;
        for (const graph of enhanced.keys()) renderInspector(graph, Number(xValue));
    }

    function renderInspectorPlaceholder(graph) {
        const panel = ensureInspector(graph);
        if (!panel || panel.childNodes.length) return;
        const text = document.createElement('div');
        text.textContent = 'Flytt markøren over grafen';
        text.style.color = '#6b7280';
        panel.appendChild(text);
    }

    function compactPresentation(graph, kind) {
        const plotly = window.Plotly;
        if (!plotly?.relayout) return;
        const updates = {};
        const layout = graph.layout || {};
        for (const key of Object.keys(layout).filter((key) => /^xaxis\d*$/.test(key))) {
            updates[`${key}.tickformat`] = '%H:%M';
            updates[`${key}.hoverformat`] = '%H:%M';
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
        if (kind === 'live' && graph._context) graph._context.scrollZoom = false;
        plotly.relayout(graph, updates);
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

    function relayoutXZoom(graph, clientX, factor) {
        const geometry = plotGeometry(graph);
        const xaxis = geometry?.layout?.xaxis;
        const range = dateRange(xaxis);
        if (!geometry || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const pixel = clientX - geometry.rect.left - geometry.size.l;
        const ratio = Math.max(0, Math.min(1, pixel / Math.max(1, geometry.size.w)));
        const anchor = start + (end - start) * ratio;
        const bounded = Math.max(0.72, Math.min(1.36, factor));
        window.Plotly.relayout(graph, {
            'xaxis.range': [
                new Date(anchor + (start - anchor) * bounded).toISOString(),
                new Date(anchor + (end - anchor) * bounded).toISOString(),
            ],
            'xaxis.autorange': false,
        });
    }

    function relayoutXPan(graph, dx) {
        const geometry = plotGeometry(graph);
        const range = dateRange(geometry?.layout?.xaxis);
        if (!geometry || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const shift = (dx / Math.max(1, geometry.size.w)) * (end - start);
        window.Plotly.relayout(graph, {
            'xaxis.range': [new Date(start + shift).toISOString(), new Date(end + shift).toISOString()],
            'xaxis.autorange': false,
        });
    }

    function relayoutYScale(graph, axisTarget, clientY, factor) {
        const geometry = plotGeometry(graph);
        const target = axisTarget || priceYAxis(graph);
        const range = yRange(target?.axis);
        if (!geometry || !target || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const pixel = clientY - geometry.rect.top - geometry.size.t;
        const ratioFromBottom = 1 - Math.max(0, Math.min(1, pixel / Math.max(1, geometry.size.h)));
        const anchor = start + (end - start) * ratioFromBottom;
        const bounded = Math.max(0.72, Math.min(1.36, factor));
        window.Plotly.relayout(graph, {
            [`${target.key}.range`]: [
                anchor + (start - anchor) * bounded,
                anchor + (end - anchor) * bounded,
            ],
            [`${target.key}.autorange`]: false,
        });
    }

    function graphAtPoint(clientX, clientY, requireLive = false) {
        const graphs = Array.from(enhanced.keys());
        for (const graph of graphs) {
            if (requireLive && targetKind(graph) !== 'live') continue;
            const rect = graph.getBoundingClientRect();
            if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) return graph;
        }
        return null;
    }

    function enhance(graph, kind) {
        if (!graph || enhanced.has(graph)) return;
        const state = {
            opacity: originalOpacity(graph),
            fingerprint: traceFingerprint(graph),
            restoringView: false,
            resettingView: false,
            wheelFrame: null,
            wheel: null,
            activePointers: new Map(),
            pinch: null,
            axisDrag: null,
        };
        enhanced.set(graph, state);
        compactPresentation(graph, kind);
        if (kind === 'live') graph.style.touchAction = 'none';
        hideHoverPopup(graph);
        ensureCrosshair(graph);
        renderInspectorPlaceholder(graph);
        window.requestAnimationFrame(() => applyBrowserView(graph, state));

        const onLegendOver = (event) => {
            const item = event.target?.closest?.('.legend .traces');
            if (!item || !graph.contains(item)) return;
            highlight(graph, state, legendTraceIndex(graph, item));
        };
        const onLegendOut = (event) => {
            const item = event.target?.closest?.('.legend .traces');
            if (!item || !graph.contains(item)) return;
            restore(graph, state);
        };
        const onPointerMove = (event) => {
            if (!pointerInsidePlot(graph, event.clientX, event.clientY)) {
                hideLinkedCrosshairs();
                return;
            }
            const xValue = showLinkedCrosshairs(graph, event.clientX);
            if (Number.isFinite(xValue)) renderInspectorsAtX(xValue);
        };
        const onPointerLeave = () => hideLinkedCrosshairs();
        const onPlotHover = (event) => {
            const point = event?.points?.[0];
            if (point) highlight(graph, state, Number(point.curveNumber));
            hideHoverPopup(graph);
        };
        const onPlotUnhover = () => restore(graph, state);
        const onPlotClick = (event) => {
            const point = event?.points?.[0];
            const value = point ? xMillis(point.x) : NaN;
            if (Number.isFinite(value)) renderInspectorsAtX(value);
        };
        const onRelayout = (eventData) => {
            if (state.restoringView || state.resettingView || !isNavigationRelayout(eventData)) return;
            const snapshot = snapshotBrowserView(graph);
            const key = viewKey(graph);
            if (snapshot && key) viewRegistry.set(key, snapshot);
        };
        const onDoubleClick = () => {
            const key = viewKey(graph);
            if (key) viewRegistry.delete(key);
            state.resettingView = true;
            window.setTimeout(() => { state.resettingView = false; }, 350);
        };
        const onAfterPlot = () => {
            hideHoverPopup(graph);
            positionInspector(graph);
            applyBrowserView(graph, state);
        };

        function flushWheel() {
            state.wheelFrame = null;
            const gesture = state.wheel;
            state.wheel = null;
            if (!gesture || kind !== 'live') return;
            if (gesture.ctrl) {
                relayoutXZoom(graph, gesture.clientX, Math.exp(gesture.dy * 0.0024));
            } else if (Math.abs(gesture.dx) > Math.abs(gesture.dy)) {
                relayoutXPan(graph, gesture.dx);
            } else {
                relayoutYScale(graph, priceYAxis(graph), gesture.clientY, Math.exp(gesture.dy * 0.0024));
            }
        }

        const onWheel = (event) => {
            if (kind !== 'live' || !pointerInsidePlot(graph, event.clientX, event.clientY)) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            const current = state.wheel || {
                dx: 0, dy: 0, ctrl: false, clientX: event.clientX, clientY: event.clientY,
            };
            current.dx += Number(event.deltaX || 0);
            current.dy += Number(event.deltaY || 0);
            current.ctrl = current.ctrl || Boolean(event.ctrlKey || event.metaKey);
            current.clientX = event.clientX;
            current.clientY = event.clientY;
            state.wheel = current;
            if (!state.wheelFrame) state.wheelFrame = window.requestAnimationFrame(flushWheel);
        };

        graph.addEventListener('pointerover', onLegendOver);
        graph.addEventListener('pointerout', onLegendOut);
        graph.addEventListener('pointermove', onPointerMove);
        graph.addEventListener('pointerleave', onPointerLeave);
        graph.addEventListener('wheel', onWheel, { passive: false, capture: true });
        graph.on?.('plotly_hover', onPlotHover);
        graph.on?.('plotly_unhover', onPlotUnhover);
        graph.on?.('plotly_click', onPlotClick);
        graph.on?.('plotly_relayout', onRelayout);
        graph.on?.('plotly_doubleclick', onDoubleClick);
        graph.on?.('plotly_afterplot', onAfterPlot);

        state.cleanup = () => {
            graph.removeEventListener('pointerover', onLegendOver);
            graph.removeEventListener('pointerout', onLegendOut);
            graph.removeEventListener('pointermove', onPointerMove);
            graph.removeEventListener('pointerleave', onPointerLeave);
            graph.removeEventListener('wheel', onWheel, true);
            graph.removeListener?.('plotly_hover', onPlotHover);
            graph.removeListener?.('plotly_unhover', onPlotUnhover);
            graph.removeListener?.('plotly_click', onPlotClick);
            graph.removeListener?.('plotly_relayout', onRelayout);
            graph.removeListener?.('plotly_doubleclick', onDoubleClick);
            graph.removeListener?.('plotly_afterplot', onAfterPlot);
            if (state.wheelFrame) window.cancelAnimationFrame(state.wheelFrame);
            graph.querySelector(':scope > .pg-linked-crosshair')?.remove();
            graph.querySelector(':scope > .pg-chart-inspector')?.remove();
            restore(graph, state);
        };
    }

    function onDocumentPointerDown(event) {
        const graph = graphAtPoint(event.clientX, event.clientY, true);
        if (!graph) return;
        const state = enhanced.get(graph);
        if (!state) return;

        const axisTarget = pointerAxisTarget(graph, event.clientX, event.clientY);
        if (axisTarget) {
            state.axisDrag = {
                pointerId: event.pointerId,
                axisTarget,
                startY: event.clientY,
                lastY: event.clientY,
            };
            event.preventDefault();
            event.stopPropagation();
            return;
        }

        if (event.pointerType !== 'touch' || !pointerInsidePlot(graph, event.clientX, event.clientY)) return;
        state.activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
        if (state.activePointers.size === 2) {
            const points = Array.from(state.activePointers.values());
            const dx = points[1].x - points[0].x;
            const dy = points[1].y - points[0].y;
            state.pinch = {
                distance: Math.max(12, Math.hypot(dx, dy)),
                midpointX: (points[0].x + points[1].x) / 2,
                midpointY: (points[0].y + points[1].y) / 2,
            };
            event.preventDefault();
            event.stopPropagation();
        }
    }

    function onDocumentPointerMove(event) {
        for (const [graph, state] of enhanced.entries()) {
            if (targetKind(graph) !== 'live') continue;
            if (state.axisDrag?.pointerId === event.pointerId) {
                const dy = event.clientY - state.axisDrag.lastY;
                state.axisDrag.lastY = event.clientY;
                relayoutYScale(
                    graph,
                    state.axisDrag.axisTarget,
                    event.clientY,
                    Math.exp(dy * 0.006)
                );
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            if (event.pointerType !== 'touch' || !state.activePointers.has(event.pointerId)) continue;
            state.activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
            if (state.activePointers.size < 2) continue;
            const points = Array.from(state.activePointers.values());
            const dx = points[1].x - points[0].x;
            const dy = points[1].y - points[0].y;
            const distance = Math.max(12, Math.hypot(dx, dy));
            const midpointX = (points[0].x + points[1].x) / 2;
            const midpointY = (points[0].y + points[1].y) / 2;
            if (!state.pinch) {
                state.pinch = { distance, midpointX, midpointY };
                continue;
            }
            const previous = state.pinch;
            const scale = previous.distance / distance;
            const moveX = midpointX - previous.midpointX;
            const moveY = midpointY - previous.midpointY;
            if (Math.abs(distance - previous.distance) >= 2) {
                relayoutXZoom(graph, midpointX, scale);
            } else if (Math.abs(moveX) > Math.abs(moveY) && Math.abs(moveX) >= 1) {
                relayoutXPan(graph, -moveX);
            } else if (Math.abs(moveY) >= 1) {
                relayoutYScale(graph, priceYAxis(graph), midpointY, Math.exp(moveY * 0.006));
            }
            state.pinch = { distance, midpointX, midpointY };
            event.preventDefault();
            event.stopPropagation();
            return;
        }
    }

    function onDocumentPointerUp(event) {
        for (const state of enhanced.values()) {
            if (state.axisDrag?.pointerId === event.pointerId) state.axisDrag = null;
            state.activePointers.delete(event.pointerId);
            if (state.activePointers.size < 2) state.pinch = null;
        }
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

    document.addEventListener('pointerdown', onDocumentPointerDown, { capture: true, passive: false });
    document.addEventListener('pointermove', onDocumentPointerMove, { capture: true, passive: false });
    document.addEventListener('pointerup', onDocumentPointerUp, { capture: true, passive: false });
    document.addEventListener('pointercancel', onDocumentPointerUp, { capture: true, passive: false });

    scan();
    observer = new MutationObserver(scan);
    observer.observe(document.body, { childList: true, subtree: true });

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        document.removeEventListener('pointerdown', onDocumentPointerDown, true);
        document.removeEventListener('pointermove', onDocumentPointerMove, true);
        document.removeEventListener('pointerup', onDocumentPointerUp, true);
        document.removeEventListener('pointercancel', onDocumentPointerUp, true);
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
    """Install browser-local interaction and navigation for TradingDesk Plotly charts.

    The LIVE chart keeps navigation in the browser: trackpad pinch zooms X, horizontal
    two-finger motion pans X, vertical two-finger motion scales the candlestick price
    axis, and direct drag on either visible Y-axis margin scales that exact axis.
    Native one-pointer plot dragging remains available for ordinary pan.
    """
    _legend_hover_component(
        key=f"pg-trading-desk-legend-hover:{uirevision}",
        data={"uirevision": str(uirevision)},
        height=0,
    )


__all__ = ["render_trading_desk_legend_hover_v1"]
