from __future__ import annotations

from typing import Any, Mapping

import streamlit as st


_LIGHTWEIGHT_CHARTS_URL = (
    "https://unpkg.com/lightweight-charts@5.2.1/dist/"
    "lightweight-charts.standalone.production.js"
)


_DIRECT_LIVE_JS = rf"""
const LIB_URL = {_LIGHTWEIGHT_CHARTS_URL!r};

export default function(component) {{
    const {{ data, parentElement }} = component;
    const payload = data.payload || {{}};
    const chartId = String(payload.chart_id || 'TradingDeskLightweight:unknown');
    const registry = window.__pricegaugerLightweightCharts ||= new Map();

    function loadLibrary() {{
        if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
        if (window.__pricegaugerLightweightChartsPromise) return window.__pricegaugerLightweightChartsPromise;
        window.__pricegaugerLightweightChartsPromise = new Promise((resolve, reject) => {{
            const existing = document.querySelector('script[data-pg-lightweight-charts]');
            if (existing) {{
                existing.addEventListener('load', () => resolve(window.LightweightCharts), {{ once: true }});
                existing.addEventListener('error', reject, {{ once: true }});
                return;
            }}
            const script = document.createElement('script');
            script.src = LIB_URL;
            script.async = true;
            script.dataset.pgLightweightCharts = '5.2.1';
            script.onload = () => window.LightweightCharts
                ? resolve(window.LightweightCharts)
                : reject(new Error('LightweightCharts global missing'));
            script.onerror = () => reject(new Error('Lightweight Charts CDN load failed'));
            document.head.appendChild(script);
        }});
        return window.__pricegaugerLightweightChartsPromise;
    }}

    function theme() {{
        const dark = window.matchMedia?.('(prefers-color-scheme: dark)')?.matches;
        return dark ? {{
            background: '#0e1117', text: '#d5d9e0', grid: 'rgba(148,163,184,.12)',
            border: 'rgba(148,163,184,.30)', inspector: 'rgba(14,17,23,.90)',
        }} : {{
            background: '#ffffff', text: '#374151', grid: 'rgba(15,23,42,.10)',
            border: 'rgba(15,23,42,.24)', inspector: 'rgba(255,255,255,.94)',
        }};
    }}

    const ROLE_STYLE = {{
        bollinger_upper: {{ color: '#94a3b8', lineWidth: 1 }},
        bollinger_middle: {{ color: '#64748b', lineWidth: 1 }},
        bollinger_lower: {{ color: '#94a3b8', lineWidth: 1 }},
        vwap: {{ color: '#f59e0b', lineWidth: 2 }},
        ema20: {{ color: '#2563eb', lineWidth: 1 }},
        ema50: {{ color: '#7c3aed', lineWidth: 1 }},
        sma50: {{ color: '#0891b2', lineWidth: 1 }},
        macd: {{ color: '#2563eb', lineWidth: 2 }},
        macd_signal: {{ color: '#dc2626', lineWidth: 1 }},
        rsi: {{ color: '#7c3aed', lineWidth: 2 }},
        stochastic_k: {{ color: '#2563eb', lineWidth: 1 }},
        stochastic_d: {{ color: '#f59e0b', lineWidth: 1 }},
        atr: {{ color: '#0f766e', lineWidth: 2 }},
    }};

    function roleStyle(item, index) {{
        if (ROLE_STYLE[item.role]) return ROLE_STYLE[item.role];
        if (String(item.role || '').startsWith('overlay:')) {{
            const colors = ['#2563eb', '#7c3aed', '#0891b2', '#ea580c', '#16a34a'];
            return {{ color: colors[index % colors.length], lineWidth: 2 }};
        }}
        return {{ color: '#64748b', lineWidth: 1 }};
    }}

    function paneIndex(name) {{
        const order = Array.from(payload.pane_order || ['price']);
        const index = order.indexOf(name);
        return index < 0 ? 0 : index;
    }}

    function createRoot(colors) {{
        parentElement.replaceChildren();
        parentElement.style.width = '100%';
        parentElement.style.height = `${{Math.max(320, Number(payload.height || 780))}}px`;
        parentElement.style.minWidth = '0';
        parentElement.style.position = 'relative';
        parentElement.style.overflow = 'hidden';

        const root = document.createElement('div');
        root.className = 'pg-lightweight-direct-live';
        Object.assign(root.style, {{ width: '100%', height: 'calc(100% - 34px)', position: 'relative', minWidth: '0', marginTop: '34px', overflow: 'visible' }});
        parentElement.appendChild(root);

        const inspector = document.createElement('div');
        inspector.className = 'pg-lightweight-direct-inspector';
        Object.assign(inspector.style, {{
            position: 'absolute', left: '8px', top: '-30px', zIndex: '8',
            maxWidth: 'calc(100% - 16px)', padding: '3px 6px', borderRadius: '5px',
            background: colors.inspector, color: colors.text, border: `1px solid ${{colors.border}}`,
            font: '500 10px/1.35 system-ui,-apple-system,sans-serif', pointerEvents: 'none',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity: '0',
            transition: 'opacity 90ms ease',
        }});
        root.appendChild(inspector);

        const countdown = document.createElement('div');
        countdown.className = 'pg-lightweight-candle-countdown';
        Object.assign(countdown.style, {{
            position: 'absolute', right: '66px', top: '-30px', zIndex: '9',
            padding: '3px 7px', borderRadius: '5px',
            background: colors.inspector, color: colors.text, border: `1px solid ${{colors.border}}`,
            font: '600 11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace',
            pointerEvents: 'none', fontVariantNumeric: 'tabular-nums',
        }});
        countdown.textContent = '--:--';
        root.appendChild(countdown);
        return {{ root, inspector, countdown }};
    }}

    function formatValue(value) {{
        const number = Number(value);
        if (!Number.isFinite(number)) return '—';
        const abs = Math.abs(number);
        const digits = abs >= 1000 ? 1 : abs >= 100 ? 2 : abs >= 1 ? 3 : 4;
        return number.toLocaleString('nb-NO', {{ maximumFractionDigits: digits }});
    }}

    function buildChart(LWC, previousVisibleRange = null) {{
        const colors = theme();
        const {{ root, inspector, countdown }} = createRoot(colors);
        // Lightweight Charts' native pinch scaling is deliberately disabled below.
        // A touch-only gesture controller applies a much stronger horizontal scale delta
        // while preserving the midpoint under the user's fingers.
        let pinchState = null;
        root.addEventListener('touchstart', (event) => {{
            if (event.touches.length !== 2) return;
            const [a, b] = event.touches;
            pinchState = {{
                distance: Math.max(1, Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY)),
            }};
        }}, {{ passive: true }});

        const chart = LWC.createChart(root, {{
            autoSize: true,
            layout: {{
                background: {{ type: LWC.ColorType.Solid, color: colors.background }},
                textColor: colors.text,
                attributionLogo: true,
                panes: {{
                    separatorColor: colors.border,
                    separatorHoverColor: 'rgba(59,130,246,.55)',
                    enableResize: true,
                }},
            }},
            grid: {{ vertLines: {{ color: colors.grid }}, horzLines: {{ color: colors.grid }} }},
            leftPriceScale: {{ visible: false, borderColor: colors.border }},
            rightPriceScale: {{
                visible: true, borderColor: colors.border,
                scaleMargins: {{ top: .08, bottom: .08 }}, minimumWidth: 58,
            }},
            timeScale: {{
                borderColor: colors.border, timeVisible: true, secondsVisible: false,
                rightOffset: 3, barSpacing: 11, minBarSpacing: 2.5,
                fixLeftEdge: false, fixRightEdge: false,
            }},
            crosshair: {{ mode: LWC.CrosshairMode.Normal }},
            handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
            handleScale: {{
                mouseWheel: true, pinch: false,
                axisPressedMouseMove: {{ time: true, price: true }},
                axisDoubleClickReset: {{ time: true, price: true }},
            }},
            kineticScroll: {{ mouse: true, touch: true }},
            hoveredSeriesOnTop: true,
        }});

        root.addEventListener('touchmove', (event) => {{
            if (!pinchState || event.touches.length !== 2) return;
            const [a, b] = event.touches;
            const distance = Math.max(1, Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY));
            const ratio = distance / pinchState.distance;
            if (!Number.isFinite(ratio) || Math.abs(ratio - 1) < 0.001) return;
            const range = chart.timeScale().getVisibleLogicalRange();
            if (!range) return;
            const center = (range.from + range.to) / 2;
            const span = Math.max(2, range.to - range.from);
            // 10x gesture gain: a small finger-distance change produces a clearly
            // visible zoom while clamping extreme jumps.
            const boosted = Math.pow(ratio, 10);
            const nextSpan = Math.max(2, Math.min(10000, span / boosted));
            try {{
                chart.timeScale().setVisibleLogicalRange({{
                    from: center - nextSpan / 2,
                    to: center + nextSpan / 2,
                }});
            }} catch (_) {{}}
            pinchState.distance = distance;
            event.preventDefault();
        }}, {{ passive: false }});
        const endPinch = () => {{ pinchState = null; }};
        root.addEventListener('touchend', endPinch, {{ passive: true }});
        root.addEventListener('touchcancel', endPinch, {{ passive: true }});

        const candles = chart.addSeries(LWC.CandlestickSeries, {{
            title: '', upColor: '#16a34a', downColor: '#dc2626',
            borderUpColor: '#16a34a', borderDownColor: '#dc2626',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c',
            priceLineVisible: true, lastValueVisible: true,
        }}, 0);
        const candleData = Array.from(payload.candles || []);
        if (!candleData.length) {{
            throw new Error('PriceGauger live chart: canonical candle payload is empty');
        }}
        candles.setData(candleData);

        const baseCandles = new Map(candleData.map((item) => [Number(item.time), {{ ...item }}]));
        const formingCandles = new Map();
        const series = new Map([['candles', candles]]);
        const labels = new Map([[candles, String(payload.market || 'Pris')]]);

        const volumeData = Array.from(payload.volume || []).map((point) => ({{
            time: point.time, value: point.value,
            color: point.direction === 'up' ? 'rgba(22,163,74,.28)' : 'rgba(220,38,38,.28)',
        }}));
        if (volumeData.length) {{
            const volume = chart.addSeries(LWC.HistogramSeries, {{
                title: '', priceScaleId: 'volume', priceFormat: {{ type: 'volume' }},
                priceLineVisible: false, lastValueVisible: false,
            }}, 0);
            volume.priceScale().applyOptions({{ scaleMargins: {{ top: .78, bottom: 0 }} }});
            volume.setData(volumeData);
            series.set('volume', volume);
            labels.set(volume, 'Volum');
        }}

        Array.from(payload.lines || []).forEach((item, index) => {{
            const style = roleStyle(item, index);
            const options = {{
                color: style.color, lineWidth: style.lineWidth,
                title: '', priceLineVisible: false, lastValueVisible: false,
                crosshairMarkerVisible: true,
            }};
            if (item.price_scale) options.priceScaleId = String(item.price_scale);
            const line = chart.addSeries(LWC.LineSeries, options, paneIndex(item.pane));
            line.setData(Array.from(item.data || []));
            series.set(String(item.role), line);
            labels.set(line, String(item.label || item.role || 'Serie'));
        }});

        Array.from(payload.histograms || []).forEach((item) => {{
            const histogram = chart.addSeries(LWC.HistogramSeries, {{
                title: '', color: 'rgba(124,58,237,.32)',
                priceLineVisible: false, lastValueVisible: false,
            }}, paneIndex(item.pane));
            histogram.setData(Array.from(item.data || []).map((point) => ({{
                time: point.time, value: point.value,
                color: Number(point.value) >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            }})));
            series.set(String(item.role), histogram);
            labels.set(histogram, String(item.label || item.role || 'Serie'));
        }});

        const rsi = series.get('rsi');
        if (rsi) {{
            for (const threshold of Array.from(payload.thresholds?.rsi || [])) {{
                rsi.createPriceLine({{
                    price: Number(threshold), color: 'rgba(100,116,139,.55)', lineWidth: 1,
                    lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false, title: '',
                }});
            }}
        }}
        const stochastic = series.get('stochastic_k');
        if (stochastic) {{
            for (const threshold of Array.from(payload.thresholds?.stochastic || [])) {{
                stochastic.createPriceLine({{
                    price: Number(threshold), color: 'rgba(100,116,139,.55)', lineWidth: 1,
                    lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false, title: '',
                }});
            }}
        }}

        for (const band of Array.from(payload.swing_bands || [])) {{
            const low = String(band.kind || '').toUpperCase() === 'LOW';
            candles.createPriceLine({{
                price: Number(band.pivot_price),
                color: low ? 'rgba(22,163,74,.42)' : 'rgba(220,38,38,.40)',
                lineWidth: 1, lineStyle: LWC.LineStyle.Dashed,
                axisLabelVisible: false, title: '',
            }});
        }}

        let markers = null;
        if (LWC.createSeriesMarkers) {{
            markers = LWC.createSeriesMarkers(candles, Array.from(payload.markers || []), {{ autoScale: false, zOrder: 'top' }});
        }}

        const panes = chart.panes();
        const priceShare = Math.max(.35, Math.min(.75, Number(payload.price_panel_share || .5)));
        if (panes.length === 1) {{
            panes[0]?.setStretchFactor?.(1);
        }} else {{
            panes[0]?.setStretchFactor?.(priceShare);
            const remainder = (1 - priceShare) / Math.max(1, panes.length - 1);
            for (let index = 1; index < panes.length; index += 1) panes[index]?.setStretchFactor?.(remainder);
        }}

        chart.subscribeCrosshairMove((param) => {{
            if (!param?.time || !param.seriesData) {{
                inspector.style.opacity = '0';
                return;
            }}
            const parts = [];
            const candle = param.seriesData.get(candles);
            if (candle && Number.isFinite(Number(candle.close))) {{
                parts.push(`O ${{formatValue(candle.open)}} H ${{formatValue(candle.high)}} L ${{formatValue(candle.low)}} C ${{formatValue(candle.close)}}`);
            }}
            for (const [api, value] of param.seriesData.entries()) {{
                if (api === candles || parts.length >= 6) continue;
                const numeric = Number(value?.value ?? value?.close);
                if (!Number.isFinite(numeric)) continue;
                const label = labels.get(api);
                if (label) parts.push(`${{label}} ${{formatValue(numeric)}}`);
            }}
            inspector.textContent = parts.join(' · ');
            inspector.style.opacity = parts.length ? '1' : '0';
        }});
        root.addEventListener('pointerleave', () => {{ inspector.style.opacity = '0'; }}, {{ passive: true }});
        // Make body-drag unambiguously horizontal. Price-scale dragging remains on
        // the right axis; the chart body must not consume vertical page movement.
        // Do not constrain the chart body to one gesture axis. Lightweight Charts
        // owns drag/pan inside the plot; page scrolling remains available outside it.
        root.style.touchAction = 'none';

        let savedVisibleTimeRange = null;
        try {{ savedVisibleTimeRange = JSON.parse(window.localStorage.getItem(viewKey) || 'null'); }} catch (_) {{}}
        const firstCandleTime = Number(candleData[0]?.time);
        const lastCandleTime = Number(candleData[candleData.length - 1]?.time);
        const overlapsCurrentData = (range) => {{
            const from = Number(range?.from);
            const to = Number(range?.to);
            return Number.isFinite(from) && Number.isFinite(to) &&
                Number.isFinite(firstCandleTime) && Number.isFinite(lastCandleTime) &&
                to >= firstCandleTime && from <= lastCandleTime;
        }};
        if (overlapsCurrentData(savedVisibleTimeRange)) {{
            try {{ chart.timeScale().setVisibleRange(savedVisibleTimeRange); }}
            catch (_) {{ savedVisibleTimeRange = null; }}
        }} else {{
            // A persisted range from an older rolling window is stale. Clear it
            // explicitly; otherwise the non-null object suppresses the latest-bars fallback.
            savedVisibleTimeRange = null;
            try {{ window.localStorage.removeItem(viewKey); }} catch (_) {{}}
        }}
        if (!savedVisibleTimeRange) {{
            // Logical indices are safe only within the current dataset. Persisting them
            // across a rolling history window can restore an empty time region while
            // indicator panes still render, so first/recovered open follows latest bars.
            const lastLogical = Math.max(0, candleData.length - 1);
            const firstLogical = Math.max(0, lastLogical - 69);
            try {{ chart.timeScale().setVisibleLogicalRange({{ from: firstLogical, to: lastLogical + 3 }}); }}
            catch (_) {{ chart.timeScale().fitContent(); }}
        }}
        chart.timeScale().subscribeVisibleTimeRangeChange((range) => {{
            if (!range) return;
            try {{ window.localStorage.setItem(viewKey, JSON.stringify(range)); }} catch (_) {{}}
        }});

        const entry = {{
            parent: parentElement, root, inspector, countdown, chart, candles, series, labels, markers,
            baseCandles, formingCandles, signature: String(payload.signature || ''), countdownTimer: null,
        }};
        applyFormingPayload(entry);
        const timeframeSeconds = Math.max(60, Number(payload.timeframe_seconds || 60));
        const renderCountdown = () => {{
            const nowSeconds = Date.now() / 1000;
            let remaining = Math.ceil(timeframeSeconds - (nowSeconds % timeframeSeconds));
            if (remaining <= 0 || remaining > timeframeSeconds) remaining = timeframeSeconds;
            const minutes = Math.floor(remaining / 60);
            const seconds = remaining % 60;
            entry.countdown.textContent = `${{String(minutes).padStart(2, '0')}}:${{String(seconds).padStart(2, '0')}}`;
        }};
        renderCountdown();
        entry.countdownTimer = window.setInterval(renderCountdown, 250);
        return entry;
    }}

    function mergedForming(entry, item) {{
        const time = Number(item.time);
        const base = entry.baseCandles.get(time) || null;
        return {{
            time,
            open: base ? Number(base.open) : Number(item.open),
            high: Math.max(Number(item.high), base ? Number(base.high) : Number(item.high)),
            low: Math.min(Number(item.low), base ? Number(base.low) : Number(item.low)),
            close: Number(item.close),
        }};
    }}

    function applyFormingPayload(entry) {{
        if (!(entry?.formingCandles instanceof Map)) entry.formingCandles = new Map();
        entry.formingCandles.clear();
        const item = payload.forming_candle || null;
        if (!item) return;
        const time = Number(item.time);
        const open = Number(item.open);
        const high = Number(item.high);
        const low = Number(item.low);
        const close = Number(item.close);
        if (![time, open, high, low, close].every(Number.isFinite)) return;
        const merged = mergedForming(entry, {{ time, open, high, low, close }});
        entry.formingCandles.set(time, merged);
        try {{ entry.candles.update(merged); }} catch (_) {{}}
    }}

    function updateEntry(entry) {{
        entry.parent.style.height = `${{Math.max(320, Number(payload.height || 780))}}px`;
        const candleData = Array.from(payload.candles || []);
        entry.baseCandles = new Map(candleData.map((item) => [Number(item.time), {{ ...item }}]));
        // Never erase a visible price series because one refresh produced an empty
        // canonical slice. Indicators may have warm-up history even when the selected
        // primary window transiently fails, which otherwise leaves an indicators-only chart.
        if (candleData.length) {{
            entry.candles.setData(candleData);
            applyFormingPayload(entry);
        }}
        for (const item of Array.from(payload.lines || [])) {{
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []));
        }}
        for (const item of Array.from(payload.histograms || [])) {{
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []).map((point) => ({{
                time: point.time, value: point.value,
                color: Number(point.value) >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            }})));
        }}
        const volume = entry.series.get('volume');
        if (volume) {{
            volume.setData(Array.from(payload.volume || []).map((point) => ({{
                time: point.time, value: point.value,
                color: point.direction === 'up' ? 'rgba(22,163,74,.28)' : 'rgba(220,38,38,.28)',
            }})));
        }}
        entry.markers?.setMarkers?.(Array.from(payload.markers || []));
    }}

    if (!registry.get(chartId) && !parentElement.querySelector('.pg-lightweight-loading')) {{
        const loading = document.createElement('div');
        loading.className = 'pg-lightweight-loading';
        loading.textContent = 'Laster Lightweight Charts…';
        Object.assign(loading.style, {{
            padding: '.75rem', color: '#64748b', font: '500 12px system-ui',
        }});
        parentElement.appendChild(loading);
    }}

    loadLibrary().then((LWC) => {{
        let entry = registry.get(chartId) || null;
        const sameParent = entry && entry.parent === parentElement && document.body.contains(entry.root);
        const sameSignature = entry && entry.signature === String(payload.signature || '');
        if (entry && (!sameParent || !sameSignature)) {{
            // Do not carry dataset-relative logical indices across a rebuild.
            // The persisted timestamp range below is stable as the rolling history moves.
            if (entry.countdownTimer) window.clearInterval(entry.countdownTimer);
            try {{ entry.chart.remove(); }} catch (_) {{}}
            registry.delete(chartId);
            // Signature changes (indicator set, period/window, etc.) rebuild series,
            // but the user's viewport remains authoritative.
            entry = buildChart(LWC, null);
            registry.set(chartId, entry);
            return;
        }}
        if (!entry) {{
            entry = buildChart(LWC, null);
            registry.set(chartId, entry);
            return;
        }}
        updateEntry(entry);
    }}).catch((error) => {{
        parentElement.replaceChildren();
        const message = document.createElement('div');
        Object.assign(message.style, {{
            padding: '12px', border: '1px solid rgba(220,38,38,.35)', borderRadius: '6px',
            color: '#b91c1c', font: '500 12px/1.4 system-ui',
        }});
        message.textContent = `Lightweight Charts kunne ikke lastes: ${{error?.message || error}}`;
        parentElement.appendChild(message);
    }});

    return () => {{}};
}}
"""


_direct_live_component = st.components.v2.component(
    "pricegauger_tradingdesk_lightweight_direct_live_v1",
    js=_DIRECT_LIVE_JS,
    isolate_styles=False,
)


def render_lightweight_direct_live_v1(
    payload: Mapping[str, Any],
    *,
    key: str,
) -> None:
    """Render the canonical LIVE contract directly; Plotly is not involved."""

    height = max(320, int(payload.get("height", 780)))
    _direct_live_component(
        key=str(key),
        data={"payload": dict(payload)},
        height=height,
    )


__all__ = ["render_lightweight_direct_live_v1"]
