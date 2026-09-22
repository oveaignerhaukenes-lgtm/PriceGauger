from __future__ import annotations

from typing import Any, Mapping

import streamlit as st


_LIGHTWEIGHT_CHARTS_URL = (
    "https://unpkg.com/lightweight-charts@5.2.1/dist/"
    "lightweight-charts.standalone.production.js"
)


_SIMPLE_LIVE_JS = rf"""
const LIB_URL = {_LIGHTWEIGHT_CHARTS_URL!r};

export default function(component) {{
    const {{ data, parentElement }} = component;
    const payload = data.payload || {{}};
    const chartId = String(payload.chart_id || 'TradingDeskSimple:unknown');
    const registry = window.__pricegaugerSimpleLiveCharts ||= new Map();

    function loadLibrary() {{
        if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
        if (window.__pricegaugerLightweightChartsPromise) return window.__pricegaugerLightweightChartsPromise;
        window.__pricegaugerLightweightChartsPromise = new Promise((resolve, reject) => {{
            const existing = document.querySelector('script[data-pg-lightweight-charts]');
            if (existing) {{
                if (window.LightweightCharts) return resolve(window.LightweightCharts);
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

    function colors() {{
        const dark = window.matchMedia?.('(prefers-color-scheme: dark)')?.matches;
        return dark
            ? {{ background: '#0e1117', text: '#d5d9e0', grid: 'rgba(148,163,184,.12)', border: 'rgba(148,163,184,.30)' }}
            : {{ background: '#ffffff', text: '#374151', grid: 'rgba(15,23,42,.10)', border: 'rgba(15,23,42,.24)' }};
    }}

    function paneIndex(name) {{
        const order = Array.from(payload.pane_order || ['price']);
        const index = order.indexOf(String(name || 'price'));
        return index < 0 ? 0 : index;
    }}

    function roleStyle(role) {{
        return ({{
            bollinger_upper: ['#94a3b8', 1],
            bollinger_middle: ['#64748b', 1],
            bollinger_lower: ['#94a3b8', 1],
            vwap: ['#f59e0b', 2],
            ema20: ['#2563eb', 1],
            ema50: ['#7c3aed', 1],
            sma50: ['#0891b2', 1],
            macd: ['#2563eb', 2],
            macd_signal: ['#dc2626', 1],
            rsi: ['#7c3aed', 2],
            stochastic_k: ['#2563eb', 1],
            stochastic_d: ['#f59e0b', 1],
            atr: ['#0f766e', 2],
        }})[String(role || '')] || ['#64748b', 1];
    }}

    function build(LWC) {{
        const theme = colors();
        parentElement.replaceChildren();
        parentElement.style.width = '100%';
        parentElement.style.height = `${{Math.max(360, Number(payload.height || 780))}}px`;
        parentElement.style.minWidth = '0';

        const root = document.createElement('div');
        Object.assign(root.style, {{ width: '100%', height: '100%', minWidth: '0' }});
        parentElement.appendChild(root);

        const chart = LWC.createChart(root, {{
            autoSize: true,
            layout: {{
                background: {{ type: LWC.ColorType.Solid, color: theme.background }},
                textColor: theme.text,
                panes: {{
                    separatorColor: theme.border,
                    separatorHoverColor: 'rgba(59,130,246,.55)',
                    enableResize: true,
                }},
            }},
            grid: {{ vertLines: {{ color: theme.grid }}, horzLines: {{ color: theme.grid }} }},
            rightPriceScale: {{ visible: true, borderColor: theme.border, scaleMargins: {{ top: .08, bottom: .08 }} }},
            leftPriceScale: {{ visible: false }},
            timeScale: {{
                borderColor: theme.border,
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 3,
                barSpacing: 9,
                minBarSpacing: 2,
            }},
            crosshair: {{ mode: LWC.CrosshairMode.Normal }},
            handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
            handleScale: {{
                mouseWheel: true,
                pinch: true,
                axisPressedMouseMove: {{ time: true, price: true }},
                axisDoubleClickReset: {{ time: true, price: true }},
            }},
        }});

        const pricePane = paneIndex('price');
        const candles = chart.addSeries(LWC.CandlestickSeries, {{
            upColor: '#16a34a', downColor: '#dc2626',
            borderUpColor: '#16a34a', borderDownColor: '#dc2626',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c',
            priceLineVisible: true, lastValueVisible: true,
        }}, pricePane);
        const candleData = Array.from(payload.candles || []);
        candles.setData(candleData);

        const series = new Map([['candles', candles]]);
        Array.from(payload.lines || []).forEach((item) => {{
            const [color, lineWidth] = roleStyle(item.role);
            const options = {{
                color, lineWidth, title: '',
                priceLineVisible: false, lastValueVisible: false,
                crosshairMarkerVisible: true,
            }};
            if (item.price_scale) options.priceScaleId = String(item.price_scale);
            const line = chart.addSeries(LWC.LineSeries, options, paneIndex(item.pane));
            line.setData(Array.from(item.data || []));
            series.set(String(item.role), line);
        }});
        Array.from(payload.histograms || []).forEach((item) => {{
            const histogram = chart.addSeries(LWC.HistogramSeries, {{
                title: '', priceLineVisible: false, lastValueVisible: false,
            }}, paneIndex(item.pane));
            histogram.setData(Array.from(item.data || []).map((point) => ({{
                time: point.time,
                value: point.value,
                color: Number(point.value) >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            }})));
            series.set(String(item.role), histogram);
        }});

        const rsi = series.get('rsi');
        for (const threshold of Array.from(payload.thresholds?.rsi || [])) {{
            rsi?.createPriceLine?.({{
                price: Number(threshold), color: 'rgba(100,116,139,.55)', lineWidth: 1,
                lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false, title: '',
            }});
        }}
        const stochastic = series.get('stochastic_k');
        for (const threshold of Array.from(payload.thresholds?.stochastic || [])) {{
            stochastic?.createPriceLine?.({{
                price: Number(threshold), color: 'rgba(100,116,139,.55)', lineWidth: 1,
                lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false, title: '',
            }});
        }}

        function markerPayload() {{
            return Array.from(payload.markers || []).map((marker) => {{
                const direction = String(marker.direction || '').toUpperCase();
                const isFlat = direction === 'FLAT';
                return {{
                    ...marker,
                    position: isFlat ? 'atPriceMiddle' : (direction === 'LONG' ? 'belowBar' : 'aboveBar'),
                    shape: isFlat ? 'square' : (direction === 'LONG' ? 'arrowUp' : 'arrowDown'),
                    color: isFlat ? '#4b5563' : (direction === 'LONG' ? '#0ea5e9' : '#f59e0b'),
                }};
            }});
        }}

        let markers = null;
        if (LWC.createSeriesMarkers) {{
            markers = LWC.createSeriesMarkers(candles, markerPayload(), {{
                autoScale: false, zOrder: 'top',
            }});
        }}

        const panes = chart.panes();
        const priceShare = Math.max(.4, Math.min(.7, Number(payload.price_panel_share || .5)));
        if (panes.length === 1) {{
            panes[pricePane]?.setStretchFactor?.(1);
        }} else {{
            const remainder = (1 - priceShare) / Math.max(1, panes.length - 1);
            panes.forEach((pane, index) => pane?.setStretchFactor?.(index === pricePane ? priceShare : remainder));
        }}

        if (candleData.length) chart.timeScale().fitContent();

        return {{
            parent: parentElement, root, chart, candles, series, markers,
            signature: String(payload.signature || ''),
        }};
    }}

    function update(entry) {{
        entry.parent.style.height = `${{Math.max(360, Number(payload.height || 780))}}px`;
        const candles = Array.from(payload.candles || []);
        const forming = payload.forming_candle || null;
        entry.candles.setData(candles);
        if (forming && Number.isFinite(Number(forming.time))) {{
            entry.candles.update({{
                time: Number(forming.time),
                open: Number(forming.open), high: Number(forming.high),
                low: Number(forming.low), close: Number(forming.close),
            }});
        }}
        for (const item of Array.from(payload.lines || [])) {{
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []));
        }}
        for (const item of Array.from(payload.histograms || [])) {{
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []).map((point) => ({{
                time: point.time,
                value: point.value,
                color: Number(point.value) >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            }})));
        }}
        entry.markers?.setMarkers?.(Array.from(payload.markers || []).map((marker) => {\n            const direction = String(marker.direction || '').toUpperCase();\n            const isFlat = direction === 'FLAT';\n            return {\n                ...marker,\n                position: isFlat ? 'atPriceMiddle' : (direction === 'LONG' ? 'belowBar' : 'aboveBar'),\n                shape: isFlat ? 'square' : (direction === 'LONG' ? 'arrowUp' : 'arrowDown'),\n                color: isFlat ? '#4b5563' : (direction === 'LONG' ? '#0ea5e9' : '#f59e0b'),\n            };\n        }));
    }}

    parentElement.innerHTML = '<div style="padding:.75rem;color:#64748b;font:500 12px system-ui">Laster chart…</div>';
    loadLibrary().then((LWC) => {{
        let entry = registry.get(chartId) || null;
        const valid = entry && entry.parent === parentElement && document.body.contains(entry.root);
        const sameSignature = valid && entry.signature === String(payload.signature || '');
        if (!valid || !sameSignature) {{
            if (entry) {{
                try {{ entry.chart.remove(); }} catch (_) {{}}
                registry.delete(chartId);
            }}
            entry = build(LWC);
            registry.set(chartId, entry);
        }}
        update(entry);
    }}).catch((error) => {{
        parentElement.textContent = `Chart-feil: ${{error?.message || error}}`;
    }});

    return () => {{}};
}}
"""


_simple_live_component = st.components.v2.component(
    "pricegauger_tradingdesk_simple_live_v2",
    js=_SIMPLE_LIVE_JS,
    isolate_styles=False,
)


def render_lightweight_simple_live_v2(
    payload: Mapping[str, Any],
    *,
    key: str,
) -> None:
    """Minimal canonical LIVE renderer: candles, indicators and AutoTrader markers only."""

    height = max(360, int(payload.get("height", 780)))
    _simple_live_component(
        key=str(key),
        data={"payload": dict(payload)},
        height=height,
    )


__all__ = ["render_lightweight_simple_live_v2"]
