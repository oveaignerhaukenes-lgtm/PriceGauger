from __future__ import annotations

from typing import Any

import streamlit as st

from autotrader_macd_timeframe_controls_v1 import MACD_CONTROL_STRATEGY_KEYS_V1
from autotrader_strong_cocktail_shadow_v2 import MACD_1M_CONTROL_STRATEGY_KEY
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from tradingdesk_ui.charts.lightweight.pnl_comparison import build_lightweight_pnl_payload_v1


_LIGHTWEIGHT_CHARTS_URL = (
    "https://unpkg.com/lightweight-charts@5.2.1/dist/"
    "lightweight-charts.standalone.production.js"
)

_CONTROL_KEYS = set(MACD_CONTROL_STRATEGY_KEYS_V1.values()) | {MACD_1M_CONTROL_STRATEGY_KEY}


def _market_reference(comparison) -> list[dict[str, float | int]]:
    try:
        _account_id, _raw_uic, _asset_type, raw_instrument_id = comparison.product_key.split(":", 3)
        bars = CanonicalMarketBarStoreV2().load_instrument_range(
            instrument_id=int(raw_instrument_id),
            start=comparison.started_at,
            end=comparison.as_of,
            limit=10000,
        )
    except Exception:
        return []
    if not bars:
        return []
    anchor = float(bars[0].close)
    if anchor == 0.0:
        return []
    points: list[dict[str, float | int]] = []
    for bar in bars:
        try:
            stamp = int(__import__("datetime").datetime.fromisoformat(str(bar.bar_time).replace("Z", "+00:00")).timestamp())
            value = ((float(bar.close) / anchor) - 1.0) * 100.0
        except Exception:
            continue
        points.append({"time": stamp, "value": value})
    return points


def build_strategy_lab_payload_v1(comparison) -> dict[str, Any]:
    base = build_lightweight_pnl_payload_v1(comparison)
    baseline_models = []
    advanced_models = []
    for model in base.get("models", []):
        strategy_key = str(model.get("id") or "").removeprefix("model:")
        label = str(model.get("label") or "")
        if strategy_key in _CONTROL_KEYS or label.startswith("Control ·"):
            baseline_models.append(model)
        else:
            advanced_models.append(model)

    return {
        "version": 1,
        "chart_id": str(base.get("chart_id") or "StrategyLab"),
        "as_of": int(base.get("as_of") or 0),
        "currency": str(base.get("currency") or ""),
        "market": {
            "label": "Marked · % fra start",
            "color": "#94a3b8",
            "data": _market_reference(comparison),
        },
        "live": base.get("live") or {},
        "baseline_models": baseline_models,
        "advanced_models": advanced_models,
        "spring": base.get("spring") or {},
    }


_STRATEGY_LAB_JS = rf"""
const LIB_URL = {_LIGHTWEIGHT_CHARTS_URL!r};

export default function(component) {{
    const {{ data, parentElement }} = component;
    const payload = data.payload || {{}};
    const mode = String(data.mode || 'baseline');

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
            bg: '#0e1117', text: '#e5e7eb', muted: '#9ca3af', grid: 'rgba(148,163,184,.12)',
            border: 'rgba(148,163,184,.28)', card: 'rgba(14,17,23,.92)',
        }} : {{
            bg: '#ffffff', text: '#111827', muted: '#6b7280', grid: 'rgba(15,23,42,.10)',
            border: 'rgba(15,23,42,.22)', card: 'rgba(255,255,255,.94)',
        }};
    }}

    function build(LWC) {{
        const colors = theme();
        parentElement.replaceChildren();
        parentElement.style.width = '100%';
        parentElement.style.minWidth = '0';

        const shell = document.createElement('div');
        Object.assign(shell.style, {{ width: '100%', minWidth: '0' }});
        parentElement.appendChild(shell);

        const heading = document.createElement('div');
        heading.textContent = mode === 'baseline' ? 'Benchmark · LIVE og kontroller' : 'Advanced · adaptive modeller og Spring';
        Object.assign(heading.style, {{
            color: colors.text, font: '700 14px/1.3 system-ui,-apple-system,sans-serif',
            padding: '2px 0 6px 0',
        }});
        shell.appendChild(heading);

        const toolbar = document.createElement('div');
        Object.assign(toolbar.style, {{
            display: 'flex', gap: '5px', alignItems: 'center', overflowX: 'auto',
            padding: '1px 0 7px 0', scrollbarWidth: 'thin',
        }});
        shell.appendChild(toolbar);

        const root = document.createElement('div');
        Object.assign(root.style, {{
            width: '100%', height: mode === 'baseline' ? '560px' : '620px',
            position: 'relative', minWidth: '0', overflow: 'hidden',
        }});
        shell.appendChild(root);

        const inspector = document.createElement('div');
        Object.assign(inspector.style, {{
            position: 'absolute', top: '5px', left: '7px', zIndex: '8',
            maxWidth: 'calc(100% - 14px)', padding: '3px 6px', borderRadius: '5px',
            border: `1px solid ${{colors.border}}`, background: colors.card, color: colors.text,
            font: '500 10px/1.35 system-ui,-apple-system,sans-serif', opacity: '0',
            pointerEvents: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }});
        root.appendChild(inspector);

        const legend = document.createElement('div');
        Object.assign(legend.style, {{
            display: 'flex', gap: '12px', alignItems: 'center', overflowX: 'auto',
            whiteSpace: 'nowrap', padding: '7px 0 10px 0', color: colors.text,
            font: '500 11px/1.3 system-ui,-apple-system,sans-serif', scrollbarWidth: 'thin',
        }});
        shell.appendChild(legend);

        const chart = LWC.createChart(root, {{
            autoSize: true,
            layout: {{
                background: {{ type: LWC.ColorType.Solid, color: colors.bg }},
                textColor: colors.text,
                attributionLogo: true,
                panes: {{
                    separatorColor: colors.border,
                    separatorHoverColor: 'rgba(59,130,246,.55)',
                    enableResize: true,
                }},
            }},
            grid: {{ vertLines: {{ color: colors.grid }}, horzLines: {{ color: colors.grid }} }},
            rightPriceScale: {{ visible: true, borderColor: colors.border, minimumWidth: 52 }},
            leftPriceScale: {{ visible: false }},
            timeScale: {{
                borderColor: colors.border, timeVisible: true, secondsVisible: false,
                rightOffset: 1, barSpacing: 7, minBarSpacing: .8,
            }},
            crosshair: {{ mode: LWC.CrosshairMode.Normal }},
            handleScroll: {{ mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
            handleScale: {{
                mouseWheel: true, pinch: true,
                axisPressedMouseMove: {{ time: true, price: true }},
                axisDoubleClickReset: {{ time: true, price: true }},
            }},
            kineticScroll: {{ mouse: true, touch: true }},
        }});

        const labels = new Map();
        const visible = new Map();
        const allTimes = [];

        function lineStyle(name) {{
            if (name === 'dash') return LWC.LineStyle.Dashed;
            if (name === 'dot') return LWC.LineStyle.Dotted;
            return LWC.LineStyle.Solid;
        }}

        function rememberTimes(points) {{
            for (const point of Array.from(points || [])) {{
                const stamp = Number(point.time);
                if (Number.isFinite(stamp)) allTimes.push(stamp);
            }}
        }}

        function addLegend(api, label, color, defaultVisible = true) {{
            visible.set(api, defaultVisible);
            const item = document.createElement('button');
            item.type = 'button';
            Object.assign(item.style, {{
                display: 'inline-flex', gap: '6px', alignItems: 'center', flex: '0 0 auto',
                border: '0', background: 'transparent', color: colors.text, padding: '1px 0',
                font: 'inherit', cursor: 'pointer', opacity: defaultVisible ? '1' : '.45',
            }});
            const swatch = document.createElement('span');
            Object.assign(swatch.style, {{ width: '18px', height: '3px', borderRadius: '99px', background: color }});
            const text = document.createElement('span');
            text.textContent = label;
            item.append(swatch, text);
            item.addEventListener('click', () => {{
                const next = !visible.get(api);
                visible.set(api, next);
                try {{ api.applyOptions({{ visible: next }}); }} catch (_) {{}}
                item.style.opacity = next ? '1' : '.45';
            }});
            legend.appendChild(item);
        }}

        const marketData = Array.from(payload.market?.data || []);
        if (marketData.length) {{
            const market = chart.addSeries(LWC.LineSeries, {{
                title: '', color: String(payload.market?.color || '#94a3b8'), lineWidth: 1,
                priceLineVisible: false, lastValueVisible: false,
            }}, 0);
            market.setData(marketData);
            labels.set(market, String(payload.market?.label || 'Marked'));
            addLegend(market, String(payload.market?.label || 'Marked'), String(payload.market?.color || '#94a3b8'));
            rememberTimes(marketData);
        }}

        if (mode === 'baseline') {{
            const liveData = Array.from(payload.live?.data || []);
            const live = chart.addSeries(LWC.LineSeries, {{
                title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,
                lineType: LWC.LineType?.WithSteps ?? 1,
                priceLineVisible: false, lastValueVisible: false,
            }}, 1);
            live.setData(liveData);
            labels.set(live, String(payload.live?.label || 'LIVE'));
            addLegend(live, String(payload.live?.label || 'LIVE'), String(payload.live?.color || '#dc2626'));
            rememberTimes(liveData);

            for (const model of Array.from(payload.baseline_models || [])) {{
                const api = chart.addSeries(LWC.LineSeries, {{
                    title: '', color: String(model.color || '#2563eb'), lineWidth: 2,
                    lineStyle: lineStyle(String(model.dash || 'dash')),
                    priceLineVisible: false, lastValueVisible: false,
                }}, 2);
                api.setData(Array.from(model.data || []));
                labels.set(api, String(model.label || 'Control'));
                addLegend(api, String(model.label || 'Control'), String(model.color || '#2563eb'));
                rememberTimes(model.data);
            }}
        }} else {{
            for (const model of Array.from(payload.advanced_models || [])) {{
                const api = chart.addSeries(LWC.LineSeries, {{
                    title: '', color: String(model.color || '#7c3aed'), lineWidth: 2,
                    lineStyle: lineStyle(String(model.dash || 'solid')),
                    priceLineVisible: false, lastValueVisible: false,
                }}, 1);
                api.setData(Array.from(model.data || []));
                labels.set(api, String(model.label || 'Advanced'));
                addLegend(api, String(model.label || 'Advanced'), String(model.color || '#7c3aed'));
                rememberTimes(model.data);
            }}

            const displacementData = Array.from(payload.spring?.displacement || []);
            if (displacementData.length) {{
                const displacement = chart.addSeries(LWC.LineSeries, {{
                    title: '', color: '#94a3b8', lineWidth: 2,
                    priceLineVisible: false, lastValueVisible: false,
                }}, 2);
                displacement.setData(displacementData);
                labels.set(displacement, 'Spring · displacement');
                addLegend(displacement, 'Spring · displacement', '#94a3b8');
                rememberTimes(displacementData);
                if (LWC.createSeriesMarkers) {{
                    try {{ LWC.createSeriesMarkers(displacement, Array.from(payload.spring?.turns || []), {{ autoScale: false }}); }} catch (_) {{}}
                }}

                const shock = chart.addSeries(LWC.LineSeries, {{
                    title: '', color: '#64748b', lineWidth: 1, lineStyle: LWC.LineStyle.Dotted,
                    priceScaleId: 'springAux', priceLineVisible: false, lastValueVisible: false,
                }}, 2);
                shock.setData(Array.from(payload.spring?.shock || []));
                labels.set(shock, 'Spring · shock z');
                addLegend(shock, 'Spring · shock z', '#64748b');
                rememberTimes(payload.spring?.shock);

                const energy = chart.addSeries(LWC.LineSeries, {{
                    title: '', color: '#f59e0b', lineWidth: 2, lineStyle: LWC.LineStyle.Solid,
                    priceScaleId: 'springAux', priceLineVisible: false, lastValueVisible: false,
                    visible: true,
                }}, 2);
                energy.setData(Array.from(payload.spring?.energy || []));
                labels.set(energy, 'Spring · energy proxy');
                addLegend(energy, 'Spring · energy proxy', '#f59e0b', true);
                rememberTimes(payload.spring?.energy);
            }}
        }}

        const panes = chart.panes();
        if (panes.length >= 3) {{
            if (mode === 'baseline') {{
                panes[0]?.setStretchFactor?.(.15);
                panes[1]?.setStretchFactor?.(.25);
                panes[2]?.setStretchFactor?.(.60);
            }} else {{
                panes[0]?.setStretchFactor?.(.15);
                panes[1]?.setStretchFactor?.(.52);
                panes[2]?.setStretchFactor?.(.33);
            }}
        }}

        const maxTime = allTimes.filter(Number.isFinite).reduce((max, value) => Math.max(max, value), Number(payload.as_of || 0));
        const ranges = [
            ['1t', 3600], ['4t', 4 * 3600], ['12t', 12 * 3600], ['1d', 86400], ['3d', 3 * 86400], ['Alt', null],
        ];
        for (const [label, seconds] of ranges) {{
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = label;
            Object.assign(button.style, {{
                flex: '0 0 auto', border: `1px solid ${{colors.border}}`, borderRadius: '7px',
                background: 'transparent', color: colors.text, padding: '3px 8px',
                font: '600 11px/1.25 system-ui,-apple-system,sans-serif', cursor: 'pointer',
            }});
            button.addEventListener('click', () => {{
                try {{
                    if (seconds == null) chart.timeScale().fitContent();
                    else chart.timeScale().setVisibleRange({{ from: maxTime - Number(seconds), to: maxTime }});
                }} catch (_) {{}}
            }});
            toolbar.appendChild(button);
        }}

        chart.subscribeCrosshairMove((param) => {{
            if (!param?.time || !param.seriesData) {{ inspector.style.opacity = '0'; return; }}
            const parts = [];
            for (const [api, value] of param.seriesData.entries()) {{
                const numeric = Number(value?.value ?? value?.close);
                if (!Number.isFinite(numeric)) continue;
                const label = labels.get(api);
                if (label) parts.push(`${{label}} ${{numeric >= 0 ? '+' : ''}}${{numeric.toFixed(2)}}`);
                if (parts.length >= 6) break;
            }}
            inspector.textContent = parts.join(' · ');
            inspector.style.opacity = parts.length ? '1' : '0';
        }});
        root.addEventListener('pointerleave', () => {{ inspector.style.opacity = '0'; }}, {{ passive: true }});

        chart.timeScale().fitContent();
    }}

    loadLibrary().then(build).catch((error) => {{
        parentElement.textContent = `Strategy Lab kunne ikke lastes: ${{error?.message || error}}`;
    }});
}}
"""


_strategy_lab_component = st.components.v2.component(
    "pricegauger_lightweight_strategy_lab_v1",
    js=_STRATEGY_LAB_JS,
    isolate_styles=False,
)


def render_strategy_lab_pnl_v1(comparison, *, key: str) -> None:
    payload = build_strategy_lab_payload_v1(comparison)
    _strategy_lab_component(
        key=f"{key}:baseline",
        data={"payload": payload, "mode": "baseline"},
        height=640,
    )
    _strategy_lab_component(
        key=f"{key}:advanced",
        data={"payload": payload, "mode": "advanced"},
        height=700,
    )


__all__ = ["build_strategy_lab_payload_v1", "render_strategy_lab_pnl_v1"]
