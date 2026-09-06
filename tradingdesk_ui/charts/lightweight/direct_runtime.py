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
        Object.assign(root.style, {{ width: '100%', height: '100%', position: 'relative', minWidth: '0' }});
        parentElement.appendChild(root);

        const inspector = document.createElement('div');
        inspector.className = 'pg-lightweight-direct-inspector';
        Object.assign(inspector.style, {{
            position: 'absolute', left: '8px', top: '6px', zIndex: '8',
            maxWidth: 'calc(100% - 16px)', padding: '3px 6px', borderRadius: '5px',
            background: colors.inspector, color: colors.text, border: `1px solid ${{colors.border}}`,
            font: '500 10px/1.35 system-ui,-apple-system,sans-serif', pointerEvents: 'none',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity: '0',
            transition: 'opacity 90ms ease',
        }});
        root.appendChild(inspector);
        return {{ root, inspector }};
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
        const {{ root, inspector }} = createRoot(colors);
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
                rightOffset: 2, barSpacing: 8, minBarSpacing: .7,
                fixLeftEdge: false, fixRightEdge: false,
            }},
            crosshair: {{ mode: LWC.CrosshairMode.Normal }},
            handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
            handleScale: {{
                mouseWheel: true, pinch: true,
                axisPressedMouseMove: {{ time: true, price: true }},
                axisDoubleClickReset: {{ time: true, price: true }},
            }},
            kineticScroll: {{ mouse: true, touch: true }},
            hoveredSeriesOnTop: true,
        }});

        const candles = chart.addSeries(LWC.CandlestickSeries, {{
            title: '', upColor: '#16a34a', downColor: '#dc2626',
            borderUpColor: '#16a34a', borderDownColor: '#dc2626',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c',
            priceLineVisible: true, lastValueVisible: true,
        }}, 0);
        const candleData = Array.from(payload.candles || []);
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

        if (previousVisibleRange) {{
            try {{ chart.timeScale().setVisibleLogicalRange(previousVisibleRange); }} catch (_) {{ chart.timeScale().fitContent(); }}
        }} else {{
            chart.timeScale().fitContent();
        }}

        return {{
            parent: parentElement, root, inspector, chart, candles, series, labels, markers,
            baseCandles, formingCandles, signature: String(payload.signature || ''),
        }};
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

    function updateEntry(entry) {{
        entry.parent.style.height = `${{Math.max(320, Number(payload.height || 780))}}px`;
        const candleData = Array.from(payload.candles || []);
        entry.baseCandles = new Map(candleData.map((item) => [Number(item.time), {{ ...item }}]));
        entry.candles.setData(candleData);
        for (const item of entry.formingCandles.values()) {{
            try {{ entry.candles.update(mergedForming(entry, item)); }} catch (_) {{}}
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

    parentElement.innerHTML = '<div style="padding:.75rem;color:#64748b;font:500 12px system-ui">Laster Lightweight Charts…</div>';

    loadLibrary().then((LWC) => {{
        let entry = registry.get(chartId) || null;
        const sameParent = entry && entry.parent === parentElement && document.body.contains(entry.root);
        const sameSignature = entry && entry.signature === String(payload.signature || '');
        if (entry && (!sameParent || !sameSignature)) {{
            let visible = null;
            try {{ visible = entry.chart.timeScale().getVisibleLogicalRange(); }} catch (_) {{}}
            try {{ entry.chart.remove(); }} catch (_) {{}}
            registry.delete(chartId);
            entry = buildChart(LWC, sameSignature ? visible : null);
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


def render_lightweight_direct_live_v1(payload: Mapping[str, Any], *, key: str) -> None:
    """Render the canonical LIVE contract directly; Plotly is not involved."""

    height = max(320, int(payload.get("height", 780)))
    _direct_live_component(
        key=str(key),
        data={"payload": dict(payload)},
        height=height,
    )


__all__ = ["render_lightweight_direct_live_v1"]
