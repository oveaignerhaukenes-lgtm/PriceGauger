from __future__ import annotations

import streamlit as st


_INTERACTION_CAPTURE_JS = r"""
export default function(component) {
    const { parentElement } = component;
    const states = new Map();
    let observer = null;
    let axisDrag = null;
    const touchPoints = new Map();
    let pinch = null;
    let wheelFrame = null;
    let wheelGesture = null;
    let axisFrame = null;
    let axisGesture = null;

    function isLiveGraph(graph) {
        const key = String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
        return key.startsWith('TradingDesk:');
    }

    function liveGraphAt(clientX, clientY) {
        for (const graph of states.keys()) {
            if (!isLiveGraph(graph)) continue;
            const rect = graph.getBoundingClientRect();
            if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
                return graph;
            }
        }
        return null;
    }

    function geometry(graph) {
        const layout = graph?._fullLayout;
        const size = layout?._size;
        if (!layout || !size) return null;
        return { layout, size, rect: graph.getBoundingClientRect() };
    }

    function insidePlot(graph, clientX, clientY) {
        const g = geometry(graph);
        if (!g) return false;
        const x = clientX - g.rect.left;
        const y = clientY - g.rect.top;
        return x >= g.size.l && x <= g.size.l + g.size.w && y >= g.size.t && y <= g.size.t + g.size.h;
    }

    function axisKeyFromTrace(ref) {
        const value = String(ref || 'y');
        return value === 'y' ? 'yaxis' : `yaxis${value.slice(1)}`;
    }

    function priceAxis(graph) {
        const layout = graph?._fullLayout;
        if (!layout) return null;
        const candle = Array.from(graph?._fullData || graph?.data || []).find(
            (trace) => String(trace?.type || '') === 'candlestick' && trace?.visible !== false
        );
        const key = axisKeyFromTrace(candle?.yaxis || 'y');
        const axis = layout[key] || layout.yaxis;
        return axis ? { key: layout[key] ? key : 'yaxis', axis } : null;
    }

    function visibleYAxes(graph) {
        const layout = graph?._fullLayout;
        if (!layout) return [];
        return Object.keys(layout)
            .filter((key) => /^yaxis\d*$/.test(key))
            .map((key) => ({ key, axis: layout[key] }))
            .filter(({ axis }) => axis && axis.visible !== false);
    }

    function axisAt(graph, clientX, clientY) {
        const g = geometry(graph);
        if (!g) return null;
        const x = clientX - g.rect.left;
        const y = clientY - g.rect.top;
        if (y < g.size.t || y > g.size.t + g.size.h) return null;
        const leftEdge = g.size.l;
        const rightEdge = g.size.l + g.size.w;
        let side = null;
        if (x >= leftEdge - 84 && x <= leftEdge + 4) side = 'left';
        if (x >= rightEdge - 4 && x <= rightEdge + 84) side = 'right';
        if (!side) return null;
        const price = priceAxis(graph);
        if (price && String(price.axis.side || 'left') === side) return price;
        return visibleYAxes(graph).find(({ axis }) => String(axis.side || 'left') === side) || null;
    }

    function dateRange(axis) {
        const range = axis?.range;
        if (!Array.isArray(range) || range.length !== 2) return null;
        const start = axis.d2c(range[0]);
        const end = axis.d2c(range[1]);
        return Number.isFinite(start) && Number.isFinite(end) && start !== end ? [start, end] : null;
    }

    function numericRange(axis) {
        const range = axis?.range;
        if (!Array.isArray(range) || range.length !== 2) return null;
        const start = Number(range[0]);
        const end = Number(range[1]);
        return Number.isFinite(start) && Number.isFinite(end) && start !== end ? [start, end] : null;
    }

    function zoomX(graph, clientX, factor) {
        const g = geometry(graph);
        const axis = g?.layout?.xaxis;
        const range = dateRange(axis);
        if (!g || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const pixel = clientX - g.rect.left - g.size.l;
        const ratio = Math.max(0, Math.min(1, pixel / Math.max(1, g.size.w)));
        const anchor = start + (end - start) * ratio;
        const bounded = Math.max(0.82, Math.min(1.22, factor));
        window.Plotly.relayout(graph, {
            'xaxis.range': [
                new Date(anchor + (start - anchor) * bounded).toISOString(),
                new Date(anchor + (end - anchor) * bounded).toISOString(),
            ],
            'xaxis.autorange': false,
        });
    }

    function panX(graph, dx) {
        const g = geometry(graph);
        const range = dateRange(g?.layout?.xaxis);
        if (!g || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const shift = (dx / Math.max(1, g.size.w)) * (end - start);
        window.Plotly.relayout(graph, {
            'xaxis.range': [new Date(start + shift).toISOString(), new Date(end + shift).toISOString()],
            'xaxis.autorange': false,
        });
    }

    function scaleY(graph, target, clientY, factor) {
        const g = geometry(graph);
        const chosen = target || priceAxis(graph);
        const range = numericRange(chosen?.axis);
        if (!g || !chosen || !range || !window.Plotly?.relayout) return;
        const [start, end] = range;
        const pixel = clientY - g.rect.top - g.size.t;
        const ratioFromBottom = 1 - Math.max(0, Math.min(1, pixel / Math.max(1, g.size.h)));
        const anchor = start + (end - start) * ratioFromBottom;
        const bounded = Math.max(0.82, Math.min(1.22, factor));
        window.Plotly.relayout(graph, {
            [`${chosen.key}.range`]: [
                anchor + (start - anchor) * bounded,
                anchor + (end - anchor) * bounded,
            ],
            [`${chosen.key}.autorange`]: false,
        });
    }

    function hideOverlay(graph) {
        const canvas = graph?.querySelector?.('canvas[id^="pg-live-candle-"]');
        if (canvas) canvas.style.opacity = '0';
    }

    function showOverlay(graph) {
        const canvas = graph?.querySelector?.('canvas[id^="pg-live-candle-"]');
        if (canvas) canvas.style.opacity = '1';
    }

    function flushWheel() {
        wheelFrame = null;
        const gesture = wheelGesture;
        wheelGesture = null;
        if (!gesture) return;
        const { graph, dx, dy, ctrl, clientX, clientY, axisTarget } = gesture;
        if (ctrl) zoomX(graph, clientX, Math.exp(dy * 0.0018));
        else if (axisTarget) scaleY(graph, axisTarget, clientY, Math.exp(dy * 0.0018));
        else if (Math.abs(dx) > Math.abs(dy)) panX(graph, dx);
        else scaleY(graph, priceAxis(graph), clientY, Math.exp(dy * 0.0018));
    }

    function onWheel(event) {
        const graph = liveGraphAt(event.clientX, event.clientY);
        if (!graph) return;
        const axisTarget = axisAt(graph, event.clientX, event.clientY);
        if (!axisTarget && !insidePlot(graph, event.clientX, event.clientY)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        const current = wheelGesture && wheelGesture.graph === graph ? wheelGesture : {
            graph, dx: 0, dy: 0, ctrl: false, clientX: event.clientX, clientY: event.clientY, axisTarget,
        };
        current.dx += Number(event.deltaX || 0);
        current.dy += Number(event.deltaY || 0);
        current.ctrl = current.ctrl || Boolean(event.ctrlKey || event.metaKey);
        current.clientX = event.clientX;
        current.clientY = event.clientY;
        current.axisTarget = axisTarget || current.axisTarget;
        wheelGesture = current;
        if (!wheelFrame) wheelFrame = window.requestAnimationFrame(flushWheel);
    }

    function flushAxisDrag() {
        axisFrame = null;
        const gesture = axisGesture;
        axisGesture = null;
        if (!gesture) return;
        scaleY(gesture.graph, gesture.axisTarget, gesture.clientY, Math.exp(gesture.dy * 0.004));
    }

    function onPointerDown(event) {
        const graph = liveGraphAt(event.clientX, event.clientY);
        if (!graph) return;
        const target = axisAt(graph, event.clientX, event.clientY);
        if (target && event.pointerType !== 'touch') {
            axisDrag = { graph, pointerId: event.pointerId, axisTarget: target, lastY: event.clientY };
            hideOverlay(graph);
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        if (event.pointerType === 'touch' && insidePlot(graph, event.clientX, event.clientY)) {
            touchPoints.set(event.pointerId, { graph, x: event.clientX, y: event.clientY });
            if (touchPoints.size >= 2) {
                const points = Array.from(touchPoints.values()).filter((item) => item.graph === graph).slice(0, 2);
                if (points.length === 2) {
                    const dx = points[1].x - points[0].x;
                    const dy = points[1].y - points[0].y;
                    pinch = {
                        graph,
                        distance: Math.max(8, Math.hypot(dx, dy)),
                        midpointX: (points[0].x + points[1].x) / 2,
                        midpointY: (points[0].y + points[1].y) / 2,
                    };
                    hideOverlay(graph);
                    event.preventDefault();
                    event.stopImmediatePropagation();
                }
            }
        }
    }

    function onPointerMove(event) {
        if (axisDrag?.pointerId === event.pointerId) {
            const dy = event.clientY - axisDrag.lastY;
            axisDrag.lastY = event.clientY;
            const current = axisGesture && axisGesture.graph === axisDrag.graph ? axisGesture : {
                graph: axisDrag.graph, axisTarget: axisDrag.axisTarget, dy: 0, clientY: event.clientY,
            };
            current.dy += dy;
            current.clientY = event.clientY;
            axisGesture = current;
            if (!axisFrame) axisFrame = window.requestAnimationFrame(flushAxisDrag);
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        if (event.pointerType !== 'touch' || !touchPoints.has(event.pointerId)) return;
        const existing = touchPoints.get(event.pointerId);
        touchPoints.set(event.pointerId, { ...existing, x: event.clientX, y: event.clientY });
        const graph = existing.graph;
        const points = Array.from(touchPoints.values()).filter((item) => item.graph === graph).slice(0, 2);
        if (points.length < 2) return;
        const dx = points[1].x - points[0].x;
        const dy = points[1].y - points[0].y;
        const distance = Math.max(8, Math.hypot(dx, dy));
        const midpointX = (points[0].x + points[1].x) / 2;
        const midpointY = (points[0].y + points[1].y) / 2;
        if (!pinch || pinch.graph !== graph) {
            pinch = { graph, distance, midpointX, midpointY };
            return;
        }
        const previous = pinch;
        const distanceDelta = Math.abs(distance - previous.distance);
        const moveX = midpointX - previous.midpointX;
        const moveY = midpointY - previous.midpointY;
        if (distanceDelta >= 1.5) zoomX(graph, midpointX, previous.distance / distance);
        else if (Math.abs(moveX) > Math.abs(moveY) && Math.abs(moveX) >= 0.8) panX(graph, -moveX);
        else if (Math.abs(moveY) >= 0.8) scaleY(graph, priceAxis(graph), midpointY, Math.exp(moveY * 0.003));
        pinch = { graph, distance, midpointX, midpointY };
        event.preventDefault();
        event.stopImmediatePropagation();
    }

    function onPointerUp(event) {
        if (axisDrag?.pointerId === event.pointerId) {
            const graph = axisDrag.graph;
            axisDrag = null;
            window.requestAnimationFrame(() => window.requestAnimationFrame(() => showOverlay(graph)));
        }
        const point = touchPoints.get(event.pointerId);
        touchPoints.delete(event.pointerId);
        if (touchPoints.size < 2) {
            if (point?.graph) window.requestAnimationFrame(() => window.requestAnimationFrame(() => showOverlay(point.graph)));
            pinch = null;
        }
    }

    function enhance(graph) {
        if (!graph || states.has(graph) || !isLiveGraph(graph)) return;
        const state = {};
        state.onRelayouting = () => hideOverlay(graph);
        state.onRelayout = () => window.requestAnimationFrame(() => window.requestAnimationFrame(() => showOverlay(graph)));
        graph.on?.('plotly_relayouting', state.onRelayouting);
        graph.on?.('plotly_relayout', state.onRelayout);
        states.set(graph, state);
    }

    function cleanup(graph, state) {
        graph.removeListener?.('plotly_relayouting', state.onRelayouting);
        graph.removeListener?.('plotly_relayout', state.onRelayout);
        showOverlay(graph);
    }

    function scan() {
        for (const graph of Array.from(document.querySelectorAll('.js-plotly-plot'))) enhance(graph);
        for (const [graph, state] of Array.from(states.entries())) {
            if (!document.body.contains(graph) || !isLiveGraph(graph)) {
                cleanup(graph, state);
                states.delete(graph);
            }
        }
    }

    window.addEventListener('wheel', onWheel, { capture: true, passive: false });
    window.addEventListener('pointerdown', onPointerDown, { capture: true, passive: false });
    window.addEventListener('pointermove', onPointerMove, { capture: true, passive: false });
    window.addEventListener('pointerup', onPointerUp, { capture: true, passive: false });
    window.addEventListener('pointercancel', onPointerUp, { capture: true, passive: false });

    scan();
    observer = new MutationObserver(scan);
    observer.observe(document.body, { childList: true, subtree: true });

    parentElement.style.display = 'none';
    return () => {
        observer?.disconnect();
        window.removeEventListener('wheel', onWheel, true);
        window.removeEventListener('pointerdown', onPointerDown, true);
        window.removeEventListener('pointermove', onPointerMove, true);
        window.removeEventListener('pointerup', onPointerUp, true);
        window.removeEventListener('pointercancel', onPointerUp, true);
        if (wheelFrame) window.cancelAnimationFrame(wheelFrame);
        if (axisFrame) window.cancelAnimationFrame(axisFrame);
        for (const [graph, state] of states.entries()) cleanup(graph, state);
        states.clear();
    };
}
"""


_interaction_capture_component = st.components.v2.component(
    "pricegauger_tradingdesk_interaction_capture_v2",
    js=_INTERACTION_CAPTURE_JS,
    isolate_styles=False,
)


def render_tradingdesk_interaction_capture_v2() -> None:
    """Install low-jank TradingDesk gesture routing ahead of Plotly native handlers."""

    _interaction_capture_component(
        key="pg-tradingdesk-interaction-capture-v2",
        data={},
        height=0,
    )


__all__ = ["render_tradingdesk_interaction_capture_v2"]
