from __future__ import annotations

import hashlib
import json
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
    const layoutKey = 'pg:tradingdesk:chart-layout:v1:' + chartId;
    function readLayout() {{
        try {{
            const stored = JSON.parse(window.localStorage.getItem(layoutKey) || '{{}}');
            return stored && typeof stored === 'object' ? stored : {{}};
        }} catch (_) {{ return {{}}; }}
    }}
    function saveLayout(patch) {{
        try {{
            window.localStorage.setItem(layoutKey, JSON.stringify({{ ...readLayout(), ...patch }}));
        }} catch (_) {{ /* Resizing still works without storage. */ }}
    }}
    function boundedHeight(value, fallback) {{
        const number = Number(value);
        return Number.isFinite(number) ? Math.max(260, Math.min(900, Math.round(number))) : fallback;
    }}

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

    function markerPayload() {{
        return Array.from(payload.markers || []).map((marker) => {{
            // V3 execution markers already encode the broker BUY/SELL side.
            // Never overwrite them with the resulting inventory direction.
            if (String(marker.source || '') === 'AUTOTRADER_V3') return marker;
            const direction = String(marker.direction || '').toUpperCase();
            if (!['LONG', 'SHORT', 'FLAT'].includes(direction)) return marker;
            const isFlat = direction === 'FLAT';
            return {{
                ...marker,
                position: isFlat ? 'aboveBar' : (direction === 'LONG' ? 'belowBar' : 'aboveBar'),
                shape: isFlat ? 'square' : (direction === 'LONG' ? 'arrowUp' : 'arrowDown'),
                color: isFlat ? '#64748b' : marker.color,
            }};
        }});
    }}

    function build(LWC) {{
        const theme = colors();
        parentElement.replaceChildren();
        parentElement.style.width = '100%';
        const savedLayout = readLayout();
        parentElement.style.height = `${{boundedHeight(savedLayout.height, Math.max(260, Number(payload.height || 260)))}}px`;
        parentElement.style.boxSizing = 'border-box';
        parentElement.style.border = '1px solid ' + theme.border;
        parentElement.style.borderRadius = '8px';
        parentElement.style.resize = 'vertical';
        parentElement.style.overflow = 'hidden';
        parentElement.style.minHeight = '260px';
        parentElement.style.maxHeight = '900px';
        parentElement.style.minWidth = '0';

        const root = document.createElement('div');
        Object.assign(root.style, {{ width: '100%', height: '100%', minWidth: '0', position: 'relative', touchAction: 'none' }});
        parentElement.appendChild(root);

        const selection = document.createElement('div');
        selection.textContent = 'Trykk på en indikatorlinje for navn';
        Object.assign(selection.style, {{
            position: 'absolute', left: '10px', top: '8px', zIndex: '20',
            padding: '4px 8px', borderRadius: '6px', pointerEvents: 'none',
            font: '600 12px system-ui', color: theme.text,
            background: theme.background, border: '1px solid ' + theme.border,
            opacity: '.88',
        }});
        root.appendChild(selection);

        const markerLegend = document.createElement('div');
        Object.assign(markerLegend.style, {{
            position: 'absolute', right: '72px', top: '8px', zIndex: '20',
            display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap',
            maxWidth: '58%', padding: '3px 6px', borderRadius: '6px',
            font: '600 10px/1.2 system-ui', color: theme.text,
            background: theme.background, border: '1px solid ' + theme.border,
            opacity: '.90', pointerEvents: 'none',
        }});
        const markerAccounts = Array.from(payload.marker_accounts || []);
        for (const account of markerAccounts) {{
            const item = document.createElement('span');
            item.style.whiteSpace = 'nowrap';
            const label = document.createElement('span');
            label.textContent = String(account.label || account.account_id || 'konto');
            const up = document.createElement('span');
            up.textContent = ' ▲';
            up.style.color = String(account.light || '#c084fc');
            up.style.fontSize = '12px';
            const down = document.createElement('span');
            down.textContent = '▼';
            down.style.color = String(account.dark || '#7e22ce');
            down.style.fontSize = '12px';
            item.append(label, up, down);
            markerLegend.appendChild(item);
        }}
        if (markerAccounts.length) {{
            const hint = document.createElement('span');
            hint.textContent = 'stor=flip · normal=øk/åpne · liten=reduser/lukke';
            hint.style.fontWeight = '500';
            hint.style.opacity = '.72';
            markerLegend.appendChild(hint);
            root.appendChild(markerLegend);
        }}

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
            handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }},
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
            line.__pgLabel = String(item.label || item.role || 'indikator');
            line.__pgRole = String(item.role || '');
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
            histogram.__pgLabel = String(item.label || item.role || 'indikator');
            histogram.__pgRole = String(item.role || '');
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

        let markers = null;
        if (LWC.createSeriesMarkers) {{
            markers = LWC.createSeriesMarkers(candles, markerPayload(), {{
                autoScale: false, zOrder: 'top',
            }});
        }}

        const panes = chart.panes();
        const savedPaneShares = Array.isArray(savedLayout.panes) ? savedLayout.panes : null;
        const priceShare = Math.max(.4, Math.min(.7, Number(payload.price_panel_share || .5)));
        if (savedPaneShares?.length === panes.length && savedPaneShares.every(x => Number.isFinite(Number(x)) && Number(x) > 0)) {{
            panes.forEach((pane, index) => pane?.setStretchFactor?.(Number(savedPaneShares[index])));
        }} else if (panes.length === 1) {{
            panes[pricePane]?.setStretchFactor?.(1);
        }} else {{
            const remainder = (1 - priceShare) / Math.max(1, panes.length - 1);
            panes.forEach((pane, index) => pane?.setStretchFactor?.(index === pricePane ? priceShare : remainder));
        }}

        // LWC owns the draggable separators between indicator panes.
        let lastFrameHeight = parentElement.getBoundingClientRect().height;
        const resizeObserver = new ResizeObserver(() => {{
            const height = Math.round(parentElement.getBoundingClientRect().height);
            if (height !== Math.round(lastFrameHeight) && height >= 260) {{
                lastFrameHeight = height;
                saveLayout({{ height }});
                chart.resize(parentElement.clientWidth, parentElement.clientHeight);
            }}
        }});
        resizeObserver.observe(parentElement);
        const savePaneSizes = () => {{
            const active = chart.panes();
            if (active.length > 1) {{
                const heights = active.map(pane => Number(pane.getHeight?.() || 0));
                if (heights.every(height => height > 0)) saveLayout({{ panes: heights }});
            }}
        }};
        root.addEventListener('pointerup', savePaneSizes);
        root.addEventListener('touchend', savePaneSizes, {{ passive: true }});
        chart.subscribeClick?.((param) => {{
            let picked = null;
            if (param?.seriesData) {{
                for (const [candidate, point] of param.seriesData.entries()) {{
                    if (candidate === candles || point == null || !candidate?.__pgLabel) continue;
                    picked = candidate;
                    break;
                }}
            }}
            if (!picked) {{
                selection.textContent = 'Trykk på en indikatorlinje for navn';
                for (const candidate of series.values()) {{
                    if (candidate === candles) continue;
                    try {{ candidate.applyOptions({{ lineWidth: roleStyle(candidate.__pgRole)[1] || 1 }}); }} catch (_) {{}}
                }}
                return;
            }}
            selection.textContent = picked.__pgLabel;
            for (const candidate of series.values()) {{
                if (candidate === candles) continue;
                try {{ candidate.applyOptions({{ lineWidth: candidate === picked ? 4 : 1 }}); }} catch (_) {{}}
            }}
        }});

        if (candleData.length) chart.timeScale().fitContent();

        return {{
            parent: parentElement, root, chart, candles, series, markers, selection, resizeObserver,
            signature: String(payload.signature || ''),
            closedRevision: JSON.stringify(candleData), formingTime: null,
            lastRevision: Number(payload.update_revision || 0),
        }};
    }}

    function update(entry) {{
        // Data refresh must not reset user-resized frame.
        const incomingRevision = Number(payload.update_revision || 0);
        if (incomingRevision < Number(entry.lastRevision || 0)) return;
        entry.lastRevision = incomingRevision;
        const candles = Array.from(payload.candles || []);
        const forming = payload.forming_candle || null;
        const revision = JSON.stringify(candles);
        if (revision !== entry.closedRevision || (!forming && entry.formingTime !== null)) {{
            entry.candles.setData(candles);
            entry.closedRevision = revision;
        }}
        if (forming && Number.isFinite(Number(forming.time))) {{
            entry.candles.update({{
                time: Number(forming.time),
                open: Number(forming.open), high: Number(forming.high),
                low: Number(forming.low), close: Number(forming.close),
            }});
        }}
        entry.formingTime = forming ? Number(forming.time) : null;
        // A fast candle-only refresh must not erase studies from the slower refresh.
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
        entry.markers?.setMarkers?.(markerPayload());
    }}

    const mounted = registry.get(chartId);
    if (!mounted || mounted.parent !== parentElement || !document.body.contains(mounted.root)) {{
        parentElement.innerHTML = '<div style="padding:.75rem;color:#64748b;font:500 12px system-ui">Laster chart…</div>';
    }}
    loadLibrary().then((LWC) => {{
        let entry = registry.get(chartId) || null;
        const valid = entry && entry.parent === parentElement && document.body.contains(entry.root);
        const sameSignature = valid && entry.signature === String(payload.signature || '');
        if (!valid || !sameSignature) {{
            if (entry) {{
                try {{ entry.resizeObserver?.disconnect(); }} catch (_) {{}}
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


_SIMPLE_LIVE_REFRESH_JS = r"""
export default function(component) {
    const { data, parentElement } = component;
    const payload = data.payload || {};
    const chartId = String(payload.chart_id || 'TradingDeskSimple:unknown');
    let timer = null;

    function apply() {
        const entry = window.__pricegaugerSimpleLiveCharts?.get(chartId);
        if (!entry || !document.body.contains(entry.root) ||
            entry.signature !== String(payload.signature || '')) return false;

        const incomingRevision = Number(payload.update_revision || 0);
        if (incomingRevision < Number(entry.lastRevision || 0)) return true;
        entry.lastRevision = incomingRevision;
        const candles = Array.from(payload.candles || []);
        const revision = JSON.stringify(candles);
        const forming = payload.forming_candle;
        if (revision !== entry.closedRevision || (!forming && entry.formingTime !== null)) {
            entry.candles.setData(candles);
            entry.closedRevision = revision;
        }
        if (forming && Number.isFinite(Number(forming.time))) {
            entry.candles.update({
                time: Number(forming.time), open: Number(forming.open),
                high: Number(forming.high), low: Number(forming.low), close: Number(forming.close),
            });
        }
        entry.formingTime = forming ? Number(forming.time) : null;
        for (const item of Array.from(payload.lines || [])) {
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []));
        }
        for (const item of Array.from(payload.histograms || [])) {
            entry.series.get(String(item.role))?.setData?.(Array.from(item.data || []).map(point => ({
                time: point.time, value: point.value,
                color: Number(point.value) >= 0 ? 'rgba(22,163,74,.34)' : 'rgba(220,38,38,.34)',
            })));
        }
        entry.markers?.setMarkers?.(Array.from(payload.markers || []).map(marker => {
            // Keep V3 broker execution-side arrows intact on 1s fragment refreshes.
            if (String(marker.source || '') === 'AUTOTRADER_V3') return marker;
            const direction = String(marker.direction || '').toUpperCase();
            if (!['LONG', 'SHORT', 'FLAT'].includes(direction)) return marker;
            const isFlat = direction === 'FLAT';
            return {
                ...marker,
                position: isFlat ? 'aboveBar' : (direction === 'LONG' ? 'belowBar' : 'aboveBar'),
                shape: isFlat ? 'square' : (direction === 'LONG' ? 'arrowUp' : 'arrowDown'),
                color: isFlat ? '#64748b' : marker.color,
            };
        }));
        return true;
    }

    if (!apply()) {
        let attempts = 0;
        timer = window.setInterval(() => {
            if (apply() || ++attempts >= 40) {
                window.clearInterval(timer);
                timer = null;
            }
        }, 100);
    }
    parentElement.style.display = 'none';
    return () => { if (timer) window.clearInterval(timer); };
}
"""


_simple_live_refresh_component = st.components.v2.component(
    "pricegauger_tradingdesk_simple_live_refresh_v2",
    js=_SIMPLE_LIVE_REFRESH_JS,
    isolate_styles=False,
)


def _payload_key(prefix: str, payload: Mapping[str, Any]) -> str:
    """A changed data revision mounts a fresh updater without remounting the chart."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}-{hashlib.blake2s(encoded, digest_size=16).hexdigest()}"


def render_lightweight_simple_live_v2(
    payload: Mapping[str, Any],
    *,
    key: str,
    refresh_only: bool = False,
) -> None:
    """Keep the visible chart mounted while a fragment delivers new chart data."""

    if not refresh_only:
        height = max(260, int(payload.get("height", 260)))
        chart_key = _payload_key(
            "pg-simple-chart", {"key": key, "signature": payload.get("signature")},
        )
        _simple_live_component(
            key=chart_key,
            data={"payload": dict(payload)},
            height=height,
        )
    else:
        _simple_live_refresh_component(
            key=_payload_key("pg-simple-refresh", {"key": key, "payload": payload}),
            data={"payload": dict(payload)},
            height=0,
        )


__all__ = ["render_lightweight_simple_live_v2"]
