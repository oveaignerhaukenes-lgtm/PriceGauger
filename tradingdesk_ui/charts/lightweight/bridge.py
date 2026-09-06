from __future__ import annotations

import streamlit as st


_LIGHTWEIGHT_BRIDGE_JS = r"""
const LIB_URL = 'https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js';

export default function(component) {
    const { parentElement } = component;
    const registry = window.__pricegaugerLightweightPlotlyBridge ||= new Map();
    let observer = null;

    function loadLibrary() {
        if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
        if (window.__pricegaugerLightweightChartsPromise) return window.__pricegaugerLightweightChartsPromise;
        window.__pricegaugerLightweightChartsPromise = new Promise((resolve, reject) => {
            const existing = document.querySelector('script[data-pg-lightweight-charts]');
            if (existing) {
                existing.addEventListener('load', () => resolve(window.LightweightCharts), { once: true });
                existing.addEventListener('error', reject, { once: true });
                return;
            }
            const script = document.createElement('script');
            script.src = LIB_URL;
            script.async = true;
            script.dataset.pgLightweightCharts = '5.2.1';
            script.onload = () => window.LightweightCharts ? resolve(window.LightweightCharts) : reject(new Error('LightweightCharts global missing'));
            script.onerror = () => reject(new Error('Lightweight Charts CDN load failed'));
            document.head.appendChild(script);
        });
        return window.__pricegaugerLightweightChartsPromise;
    }

    function targetGraph(graph) {
        const key = String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
        return key.startsWith('TradingDesk:');
    }

    function chartKey(graph) {
        return String(graph?.layout?.uirevision || graph?._fullLayout?.uirevision || '');
    }

    function timeframeSeconds(graph) {
        const match = chartKey(graph).match(/^TradingDesk:(.*):(1m|2m|5m|10m|15m|20m|30m|1h):/);
        const value = match?.[2] || '1m';
        if (value === '1h') return 3600;
        const minutes = Number(String(value).replace('m', ''));
        return Number.isFinite(minutes) && minutes > 0 ? minutes * 60 : 60;
    }

    function epoch(value) {
        if (typeof value === 'number' && Number.isFinite(value)) {
            return value > 1e12 ? Math.floor(value / 1000) : Math.floor(value);
        }
        const parsed = new Date(String(value)).getTime();
        return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : null;
    }

    function cleanNumber(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    }

    function traceAxisKey(trace) {
        const ref = String(trace?.yaxis || 'y');
        return ref === 'y' ? 'yaxis' : `yaxis${ref.slice(1)}`;
    }

    function resolvedBaseAxis(layout, axisKey) {
        let key = axisKey;
        const seen = new Set();
        while (layout?.[key]?.overlaying && !seen.has(key)) {
            seen.add(key);
            const ref = String(layout[key].overlaying || 'y');
            key = ref === 'y' ? 'yaxis' : `yaxis${ref.slice(1)}`;
        }
        return key;
    }

    function paneMapping(graph) {
        const layout = graph?._fullLayout || {};
        const axes = Object.keys(layout)
            .filter((key) => /^yaxis\d*$/.test(key))
            .map((key) => ({ key, axis: layout[key] }))
            .filter(({ axis }) => Array.isArray(axis?.domain) && axis.domain.length === 2 && !axis.overlaying)
            .sort((a, b) => Number(b.axis.domain[1]) - Number(a.axis.domain[1]));
        const mapping = new Map();
        axes.forEach(({ key }, index) => mapping.set(key, index));
        for (const key of Object.keys(layout).filter((item) => /^yaxis\d*$/.test(item))) {
            const base = resolvedBaseAxis(layout, key);
            if (mapping.has(base)) mapping.set(key, mapping.get(base));
        }
        return { mapping, axes };
    }

    function theme() {
        const dark = window.matchMedia?.('(prefers-color-scheme: dark)')?.matches;
        return dark ? {
            background: '#0e1117', text: '#d5d9e0', grid: 'rgba(148,163,184,.12)',
            border: 'rgba(148,163,184,.30)', legend: 'rgba(14,17,23,.84)',
        } : {
            background: '#ffffff', text: '#374151', grid: 'rgba(15,23,42,.10)',
            border: 'rgba(15,23,42,.24)', legend: 'rgba(255,255,255,.90)',
        };
    }

    function lineColor(trace, fallbackIndex) {
        const direct = trace?.line?.color;
        if (typeof direct === 'string' && direct && !direct.startsWith('rgba(0, 0, 0, 0')) return direct;
        const colors = ['#2563eb', '#dc2626', '#7c3aed', '#f59e0b', '#0891b2', '#16a34a', '#64748b'];
        return colors[fallbackIndex % colors.length];
    }

    function lineData(trace) {
        const xs = Array.from(trace?.x || []);
        const ys = Array.from(trace?.y || []);
        const result = [];
        for (let i = 0; i < Math.min(xs.length, ys.length); i += 1) {
            const time = epoch(xs[i]);
            const value = cleanNumber(ys[i]);
            if (time == null || value == null) continue;
            result.push({ time, value });
        }
        return result;
    }

    function candleData(trace) {
        const xs = Array.from(trace?.x || []);
        const result = [];
        for (let i = 0; i < xs.length; i += 1) {
            const time = epoch(xs[i]);
            const open = cleanNumber(trace?.open?.[i]);
            const high = cleanNumber(trace?.high?.[i]);
            const low = cleanNumber(trace?.low?.[i]);
            const close = cleanNumber(trace?.close?.[i]);
            if (time == null || [open, high, low, close].some((value) => value == null)) continue;
            result.push({ time, open, high, low, close });
        }
        return result;
    }

    function histogramData(trace) {
        const xs = Array.from(trace?.x || []);
        const ys = Array.from(trace?.y || []);
        const result = [];
        for (let i = 0; i < Math.min(xs.length, ys.length); i += 1) {
            const time = epoch(xs[i]);
            const value = cleanNumber(ys[i]);
            if (time == null || value == null) continue;
            result.push({
                time,
                value,
                color: value >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            });
        }
        return result;
    }

    function overlayEntry(graph) {
        return window.__pricegaugerLiveCandleOverlays?.get?.(chartKey(graph)) || null;
    }

    function formingCandle(graph, canonicalCandles) {
        const overlay = overlayEntry(graph);
        const raw = Array.from(overlay?.candles?.values?.() || [])
            .map((item) => ({
                time: epoch(item?.bar_time),
                open: cleanNumber(item?.open),
                high: cleanNumber(item?.high),
                low: cleanNumber(item?.low),
                close: cleanNumber(item?.close),
            }))
            .filter((item) => item.time != null && [item.open, item.high, item.low, item.close].every((value) => value != null))
            .sort((a, b) => a.time - b.time);
        if (!raw.length) return null;

        const seconds = timeframeSeconds(graph);
        const latestTime = raw[raw.length - 1].time;
        const bucketTime = Math.floor(latestTime / seconds) * seconds;
        const bucket = raw.filter((item) => Math.floor(item.time / seconds) * seconds === bucketTime);
        if (!bucket.length) return null;

        const canonical = Array.from(canonicalCandles || []).find((item) => Number(item.time) === bucketTime) || null;
        const first = bucket[0];
        const last = bucket[bucket.length - 1];
        const highs = bucket.map((item) => Number(item.high));
        const lows = bucket.map((item) => Number(item.low));
        if (canonical) {
            highs.push(Number(canonical.high));
            lows.push(Number(canonical.low));
        }
        return {
            time: bucketTime,
            open: canonical ? Number(canonical.open) : Number(first.open),
            high: Math.max(...highs),
            low: Math.min(...lows),
            close: Number(last.close),
        };
    }

    function nearestTime(times, raw) {
        if (!times.length) return null;
        let best = times[0];
        let distance = Math.abs(best - raw);
        for (const value of times) {
            const next = Math.abs(value - raw);
            if (next < distance) { best = value; distance = next; }
        }
        return best;
    }

    function markerPayload(graph, candleTimes) {
        const overlay = overlayEntry(graph);
        const markers = Array.from(overlay?.tradeMarkers || []);
        return markers.flatMap((marker, index) => {
            const raw = epoch(marker.executed_at);
            const time = raw == null ? null : nearestTime(candleTimes, raw);
            const price = cleanNumber(marker.execution_price);
            if (time == null || price == null) return [];
            const direction = String(marker.direction || '').toUpperCase();
            return [{
                time,
                price,
                position: 'atPriceMiddle',
                shape: direction === 'LONG' ? 'arrowUp' : 'arrowDown',
                color: direction === 'LONG' ? '#16a34a' : '#dc2626',
                size: marker.active ? 1.0 : 0.72,
                id: `${raw}:${index}`,
            }];
        });
    }

    function rootFor(graph, colors) {
        let root = graph.querySelector(':scope > .pg-lightweight-bridge-root');
        if (!root) {
            root = document.createElement('div');
            root.className = 'pg-lightweight-bridge-root';
            Object.assign(root.style, {
                position: 'absolute', inset: '0', zIndex: '50',
                background: colors.background, overflow: 'hidden', touchAction: 'none',
            });
            graph.style.position = 'relative';
            graph.appendChild(root);
        }
        return root;
    }

    function createLegend(root, colors) {
        const legend = document.createElement('div');
        Object.assign(legend.style, {
            position: 'absolute', left: '8px', top: '6px', zIndex: '9',
            maxWidth: 'calc(100% - 90px)', padding: '4px 7px', borderRadius: '5px',
            background: colors.legend, color: colors.text,
            border: `1px solid ${colors.border}`,
            font: '500 11px/1.3 system-ui,-apple-system,sans-serif',
            pointerEvents: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        });
        root.appendChild(legend);
        return legend;
    }

    function createBridge(graph, LWC, visibleRange = null) {
        const colors = theme();
        const root = rootFor(graph, colors);
        root.replaceChildren();
        const legend = createLegend(root, colors);
        const key = chartKey(graph);
        legend.textContent = key.split(':').slice(1, 3).join(' · ');

        const chart = LWC.createChart(root, {
            autoSize: true,
            layout: {
                background: { type: LWC.ColorType.Solid, color: colors.background },
                textColor: colors.text,
                attributionLogo: true,
                panes: {
                    separatorColor: colors.border,
                    separatorHoverColor: 'rgba(59,130,246,.55)',
                    enableResize: true,
                },
            },
            grid: {
                vertLines: { color: colors.grid },
                horzLines: { color: colors.grid },
            },
            leftPriceScale: { visible: false, borderColor: colors.border },
            rightPriceScale: {
                visible: true,
                borderColor: colors.border,
                scaleMargins: { top: .08, bottom: .08 },
                minimumWidth: 58,
            },
            timeScale: {
                borderColor: colors.border,
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 2,
                barSpacing: 8,
                minBarSpacing: .7,
            },
            crosshair: { mode: LWC.CrosshairMode.Normal },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: false,
            },
            handleScale: {
                mouseWheel: true,
                pinch: true,
                axisPressedMouseMove: { time: true, price: true },
                axisDoubleClickReset: { time: true, price: true },
            },
            kineticScroll: { mouse: true, touch: true },
            hoveredSeriesOnTop: true,
        });

        const traces = Array.from(graph?.data || []);
        const candleTrace = traces.find((trace) => String(trace?.type || '') === 'candlestick');
        if (!candleTrace) {
            root.remove();
            return null;
        }
        const candlesData = candleData(candleTrace);
        const candles = chart.addSeries(LWC.CandlestickSeries, {
            title: String(candleTrace.name || 'Pris'),
            upColor: '#16a34a', downColor: '#dc2626',
            borderUpColor: '#16a34a', borderDownColor: '#dc2626',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c',
            priceLineVisible: true, lastValueVisible: true,
        }, 0);
        candles.setData(candlesData);
        const forming = formingCandle(graph, candlesData);
        if (forming) candles.update(forming);

        const { mapping, axes } = paneMapping(graph);
        const labels = new Map([[candles, String(candleTrace.name || 'Pris')]]);
        const apis = [];
        let lineIndex = 0;
        for (const trace of traces) {
            if (trace === candleTrace || trace?.visible === false || trace?.visible === 'legendonly') continue;
            const axisKey = traceAxisKey(trace);
            const pane = mapping.get(axisKey) ?? 0;
            const type = String(trace?.type || 'scatter');
            if (type === 'bar') {
                const data = histogramData(trace);
                if (!data.length) continue;
                const series = chart.addSeries(LWC.HistogramSeries, {
                    title: String(trace.name || ''),
                    priceLineVisible: false,
                    lastValueVisible: false,
                }, pane);
                series.setData(data);
                apis.push(series);
                labels.set(series, String(trace.name || 'Histogram'));
                continue;
            }
            if (type !== 'scatter' && type !== 'scattergl') continue;
            const data = lineData(trace);
            if (!data.length) continue;
            const axis = graph?._fullLayout?.[axisKey];
            const overlaying = Boolean(axis?.overlaying);
            const color = lineColor(trace, lineIndex++);
            const options = {
                title: String(trace.name || ''),
                color,
                lineWidth: Math.max(1, Math.min(3, Number(trace?.line?.width || 1.4))),
                priceLineVisible: false,
                lastValueVisible: !String(trace.name || '').toLowerCase().includes('bollinger'),
            };
            if (overlaying && pane === 0 && axisKey !== traceAxisKey(candleTrace)) {
                options.priceScaleId = `pg-${axisKey}`;
            }
            const series = chart.addSeries(LWC.LineSeries, options, pane);
            series.setData(data);
            apis.push(series);
            labels.set(series, String(trace.name || 'Serie'));
        }

        const markerTimes = candlesData.map((item) => item.time);
        if (forming && !markerTimes.includes(forming.time)) markerTimes.push(forming.time);
        markerTimes.sort((a, b) => a - b);
        const markers = LWC.createSeriesMarkers?.(
            candles,
            markerPayload(graph, markerTimes),
            { autoScale: false, zOrder: 'top' }
        ) || null;

        const panes = chart.panes();
        if (panes.length && axes.length) {
            const total = axes.reduce((sum, item) => sum + Math.max(.05, Number(item.axis.domain[1]) - Number(item.axis.domain[0])), 0);
            panes.forEach((pane, index) => {
                const axis = axes[index];
                const size = axis ? Math.max(.05, Number(axis.axis.domain[1]) - Number(axis.axis.domain[0])) : 1 / panes.length;
                pane.setStretchFactor?.(size / Math.max(.01, total));
            });
        }

        function fmt(value) {
            const number = Number(value);
            if (!Number.isFinite(number)) return '—';
            const abs = Math.abs(number);
            const digits = abs >= 1000 ? 1 : abs >= 100 ? 2 : abs >= 1 ? 3 : 4;
            return number.toLocaleString('nb-NO', { maximumFractionDigits: digits });
        }
        chart.subscribeCrosshairMove((param) => {
            if (!param?.time || !param.seriesData) return;
            const parts = [];
            const candle = param.seriesData.get(candles);
            if (candle) parts.push(`O ${fmt(candle.open)} H ${fmt(candle.high)} L ${fmt(candle.low)} C ${fmt(candle.close)}`);
            for (const [api, value] of param.seriesData.entries()) {
                if (api === candles || parts.length >= 6) continue;
                const numeric = Number(value?.value ?? value?.close);
                const label = labels.get(api);
                if (label && Number.isFinite(numeric)) parts.push(`${label} ${fmt(numeric)}`);
            }
            if (parts.length) legend.textContent = parts.join(' · ');
        });

        if (visibleRange) {
            try { chart.timeScale().setVisibleLogicalRange(visibleRange); } catch (_) { chart.timeScale().fitContent(); }
        } else {
            chart.timeScale().fitContent();
        }

        return { graph, root, chart, candles, apis, markers, fingerprint: traceFingerprint(graph) };
    }

    function edge(values) {
        const items = Array.from(values || []);
        if (!items.length) return ['', ''];
        return [String(items[0] ?? ''), String(items[items.length - 1] ?? '')];
    }

    function traceFingerprint(graph) {
        return Array.from(graph?.data || []).map((trace) => {
            const xs = Array.from(trace?.x || []);
            const values = Array.isArray(trace?.close) ? Array.from(trace.close) : Array.from(trace?.y || []);
            const [firstX, lastX] = edge(xs);
            const [firstValue, lastValue] = edge(values);
            return [
                String(trace?.type || ''), String(trace?.name || ''),
                xs.length, values.length, firstX, lastX, firstValue, lastValue,
                String(trace?.visible ?? true), String(trace?.yaxis || 'y'),
            ].join(':');
        }).join('|');
    }

    function refreshLiveBrowserData(entry, graph) {
        const candleTrace = Array.from(graph?.data || []).find((trace) => String(trace?.type || '') === 'candlestick');
        if (!candleTrace) return;
        const canonical = candleData(candleTrace);
        const forming = formingCandle(graph, canonical);
        if (forming) entry.candles.update(forming);
        const markerTimes = canonical.map((item) => item.time);
        if (forming && !markerTimes.includes(forming.time)) markerTimes.push(forming.time);
        markerTimes.sort((a, b) => a - b);
        entry.markers?.setMarkers?.(markerPayload(graph, markerTimes));
    }

    function refreshBridge(graph, LWC) {
        const key = chartKey(graph);
        const existing = registry.get(key);
        const fingerprint = traceFingerprint(graph);
        if (existing && existing.graph === graph && existing.fingerprint === fingerprint && document.body.contains(existing.root)) {
            refreshLiveBrowserData(existing, graph);
            return;
        }
        let visible = null;
        if (existing) {
            try { visible = existing.chart.timeScale().getVisibleLogicalRange(); } catch (_) {}
            try { existing.chart.remove(); } catch (_) {}
            existing.root?.remove?.();
            registry.delete(key);
        }
        const bridge = createBridge(graph, LWC, visible);
        if (bridge) registry.set(key, bridge);
    }

    function scan(LWC) {
        const liveGraphs = Array.from(document.querySelectorAll('.js-plotly-plot')).filter(targetGraph);
        for (const graph of liveGraphs) refreshBridge(graph, LWC);
        for (const [key, entry] of Array.from(registry.entries())) {
            if (!document.body.contains(entry.graph)) {
                try { entry.chart.remove(); } catch (_) {}
                registry.delete(key);
            }
        }
    }

    loadLibrary().then((LWC) => {
        scan(LWC);
        observer = new MutationObserver(() => scan(LWC));
        observer.observe(document.body, { childList: true, subtree: true });
        // The 250 ms poll only mirrors the UI-only forming candle/marker read-model.
        // Native chart navigation itself never crosses this timer or Streamlit.
        const timer = window.setInterval(() => scan(LWC), 250);
        parentElement.style.display = 'none';
        parentElement.dataset.pgLightweightBridgeTimer = String(timer);
    }).catch((error) => {
        console.error('PriceGauger Lightweight bridge failed', error);
        parentElement.style.display = 'none';
    });

    return () => {
        observer?.disconnect();
        const timer = Number(parentElement.dataset.pgLightweightBridgeTimer || 0);
        if (timer) window.clearInterval(timer);
    };
}
"""


_bridge_component = st.components.v2.component(
    "pricegauger_tradingdesk_lightweight_plotly_bridge_v1",
    js=_LIGHTWEIGHT_BRIDGE_JS,
    isolate_styles=False,
)


def render_lightweight_plotly_bridge_v1() -> None:
    """Transitional adapter: render the existing LIVE Plotly read-model with LWC.

    The hidden Plotly figure remains the temporary server-side serialization source while
    native browser interaction/rendering is evaluated. No trading authority is introduced.
    """

    _bridge_component(
        key="pg-tradingdesk-lightweight-plotly-bridge-v1",
        data={},
        height=0,
    )


__all__ = ["render_lightweight_plotly_bridge_v1"]
