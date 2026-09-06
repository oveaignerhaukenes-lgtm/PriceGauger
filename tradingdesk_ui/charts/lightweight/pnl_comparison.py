from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st

from autotrader_macd_timeframe_controls_v1 import (
    MACD_CONTROL_STRATEGY_KEYS_V1,
    macd_control_strategy_label_v1,
)
from autotrader_pnl_comparison_v2 import (
    PAPER_SCALE_PILOT_EQUIVALENT,
    AutoManagerPnlComparisonV2,
)
from autotrader_shadow_leverage_v2 import (
    apply_schedule_to_series_v2,
    load_live_leverage_schedule_v2,
)
from autotrader_strategy_catalog_v2 import strategy_display_label_v2
from autotrader_strong_cocktail_shadow_v2 import (
    MACD_1M_CONTROL_STRATEGY_KEY,
    STRONG_COCKTAIL_STRATEGY_KEY,
)
from spring_trade_engine.persistence import load_spring_observations_v1


_LIGHTWEIGHT_CHARTS_URL = (
    "https://unpkg.com/lightweight-charts@5.2.1/dist/"
    "lightweight-charts.standalone.production.js"
)

_PAPER_COLORS = (
    "#2563eb",
    "#7c3aed",
    "#059669",
    "#d97706",
    "#0891b2",
    "#be123c",
    "#4f46e5",
    "#0f766e",
    "#a16207",
    "#9333ea",
    "#0369a1",
    "#b91c1c",
)
_MACD_CONTROL_MINUTES_BY_KEY = {
    key: minutes for minutes, key in MACD_CONTROL_STRATEGY_KEYS_V1.items()
}


def _utc_epoch(value: datetime) -> int:
    parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _strategy_label(strategy_key: str) -> str:
    key = str(strategy_key)
    if key == STRONG_COCKTAIL_STRATEGY_KEY:
        return "Strong Cocktail · 1m event + MTF context"
    if key == MACD_1M_CONTROL_STRATEGY_KEY:
        return "1m MACD flip · control"
    minutes = _MACD_CONTROL_MINUTES_BY_KEY.get(key)
    if minutes is not None:
        return macd_control_strategy_label_v1(minutes)
    return strategy_display_label_v2(key)


def _leverage_schedule(comparison: AutoManagerPnlComparisonV2):
    account_id, raw_uic, asset_type, _instrument_id = comparison.product_key.split(":", 3)
    return load_live_leverage_schedule_v2(
        pilot_key=comparison.pilot_key,
        account_id=account_id,
        uic=int(raw_uic),
        asset_type=asset_type,
    )


def _models_for_chart(comparison: AutoManagerPnlComparisonV2):
    if comparison.paper_scale == PAPER_SCALE_PILOT_EQUIVALENT:
        try:
            return comparison.paper_series, _leverage_schedule(comparison), True
        except Exception:
            return comparison.paper_series, None, True
    try:
        schedule = _leverage_schedule(comparison)
        return apply_schedule_to_series_v2(comparison.paper_series, schedule=schedule), schedule, False
    except Exception:
        return comparison.paper_series, None, False


def _spring_points(comparison: AutoManagerPnlComparisonV2):
    try:
        _account_id, _raw_uic, _asset_type, raw_instrument_id = comparison.product_key.split(":", 3)
        return load_spring_observations_v1(
            instrument_id=int(raw_instrument_id),
            start=comparison.started_at,
            end=comparison.as_of,
            limit=10000,
        )
    except Exception:
        return ()


def build_lightweight_pnl_payload_v1(comparison: AutoManagerPnlComparisonV2) -> dict[str, Any]:
    model_series, leverage_schedule, persisted_pilot_scale = _models_for_chart(comparison)
    if leverage_schedule is None:
        model_title = "Modeller · pilot-ekvivalent" if persisted_pilot_scale else "Modeller · 1×"
    else:
        model_title = f"Modeller · ca. {leverage_schedule.representative_leverage:.1f}×"

    models = []
    for index, series in enumerate(model_series):
        mode = str(series.execution_mode).upper()
        is_adaptive = mode == "SHADOW_ADAPTIVE"
        is_control = mode == "SHADOW_CONTROL"
        prefix = "Shadow" if is_adaptive else ("Control" if is_control else "Paper")
        models.append(
            {
                "id": f"model:{series.strategy_key}",
                "label": f"{prefix} · {_strategy_label(series.strategy_key)}",
                "color": _PAPER_COLORS[index % len(_PAPER_COLORS)],
                "dash": "solid" if is_adaptive else ("dash" if is_control else "dot"),
                "data": [
                    {
                        "time": _utc_epoch(point.closed_at),
                        "value": ((float(point.equity) / float(series.seed_equity)) - 1.0) * 100.0,
                        "state": str(point.position_state),
                    }
                    for point in series.points
                ],
            }
        )

    spring = _spring_points(comparison)
    turning = [
        point
        for point in spring
        if str(point.turning_state) in {"TURN_UP", "TURN_DOWN"}
    ]

    return {
        "version": 1,
        "chart_id": f"AutoManagerPnlLightweight:{comparison.product_key}:{comparison.started_at.isoformat()}",
        "height": 820,
        "as_of": _utc_epoch(comparison.as_of),
        "currency": str(comparison.currency),
        "titles": {
            "live": "LIVE · realisert P/L",
            "models": model_title,
            "spring": "Spring · blind observasjon",
        },
        "live": {
            "id": "live",
            "label": "LIVE · realisert Saxo",
            "color": "#dc2626",
            "data": [
                {
                    "time": _utc_epoch(point.occurred_at),
                    "value": float(point.return_pct),
                    "pnl": float(point.cumulative_pnl),
                    "strategy": _strategy_label(point.strategy_key),
                }
                for point in comparison.live_realized
            ],
        },
        "models": models,
        "spring": {
            "displacement": [
                {
                    "time": _utc_epoch(point.observed_at),
                    "value": float(point.displacement_pct),
                    "turning": str(point.turning_state),
                    "shock": float(point.shock_score),
                    "energy": float(point.energy_proxy),
                    "velocity": float(point.velocity_pct_per_min),
                }
                for point in spring
            ],
            "shock": [
                {"time": _utc_epoch(point.observed_at), "value": float(point.shock_score)}
                for point in spring
            ],
            "energy": [
                {"time": _utc_epoch(point.observed_at), "value": float(point.energy_proxy)}
                for point in spring
            ],
            "turns": [
                {
                    "time": _utc_epoch(point.observed_at),
                    "position": "aboveBar" if str(point.turning_state) == "TURN_DOWN" else "belowBar",
                    "shape": "arrowDown" if str(point.turning_state) == "TURN_DOWN" else "arrowUp",
                    "color": "#64748b",
                    "text": str(point.turning_state),
                }
                for point in turning
            ],
        },
    }


_PNL_JS = rf"""
const LIB_URL = {_LIGHTWEIGHT_CHARTS_URL!r};

export default function(component) {{
    const {{ data, parentElement }} = component;
    const payload = data.payload || {{}};

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

        const toolbar = document.createElement('div');
        Object.assign(toolbar.style, {{
            display: 'flex', gap: '5px', alignItems: 'center', overflowX: 'auto',
            padding: '2px 0 7px 0', scrollbarWidth: 'thin',
        }});
        shell.appendChild(toolbar);

        const root = document.createElement('div');
        Object.assign(root.style, {{
            width: '100%', height: `${{Math.max(420, Number(payload.height || 820))}}px`,
            position: 'relative', minWidth: '0', overflow: 'hidden',
        }});
        shell.appendChild(root);

        const inspector = document.createElement('div');
        Object.assign(inspector.style, {{
            position: 'absolute', top: '6px', left: '8px', zIndex: '8',
            maxWidth: 'calc(100% - 16px)', padding: '3px 6px', borderRadius: '5px',
            border: `1px solid ${{colors.border}}`, background: colors.card, color: colors.text,
            font: '500 10px/1.35 system-ui,-apple-system,sans-serif', opacity: '0',
            pointerEvents: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }});
        root.appendChild(inspector);

        const legend = document.createElement('div');
        Object.assign(legend.style, {{
            display: 'flex', gap: '12px', alignItems: 'center', overflowX: 'auto',
            whiteSpace: 'nowrap', padding: '8px 0 2px 0', color: colors.text,
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

        const registry = [];
        const labels = new Map();
        const visible = new Map();

        function lineStyle(name) {{
            if (name === 'dash') return LWC.LineStyle.Dashed;
            if (name === 'dot') return LWC.LineStyle.Dotted;
            return LWC.LineStyle.Solid;
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

        const live = chart.addSeries(LWC.LineSeries, {{
            title: '', color: String(payload.live?.color || '#dc2626'), lineWidth: 2,
            lineType: LWC.LineType?.WithSteps ?? 1,
            priceLineVisible: false, lastValueVisible: false,
        }}, 0);
        live.setData(Array.from(payload.live?.data || []));
        registry.push(live);
        labels.set(live, String(payload.live?.label || 'LIVE'));
        addLegend(live, String(payload.live?.label || 'LIVE'), String(payload.live?.color || '#dc2626'));

        for (const model of Array.from(payload.models || [])) {{
            const api = chart.addSeries(LWC.LineSeries, {{
                title: '', color: String(model.color || '#2563eb'), lineWidth: 2,
                lineStyle: lineStyle(String(model.dash || 'solid')),
                priceLineVisible: false, lastValueVisible: false,
            }}, 1);
            api.setData(Array.from(model.data || []));
            registry.push(api);
            labels.set(api, String(model.label || 'Model'));
            addLegend(api, String(model.label || 'Model'), String(model.color || '#2563eb'));
        }}

        const springDisplacementData = Array.from(payload.spring?.displacement || []);
        let springDisplacement = null;
        if (springDisplacementData.length) {{
            springDisplacement = chart.addSeries(LWC.LineSeries, {{
                title: '', color: '#94a3b8', lineWidth: 2,
                priceLineVisible: false, lastValueVisible: false,
            }}, 2);
            springDisplacement.setData(springDisplacementData);
            registry.push(springDisplacement);
            labels.set(springDisplacement, 'Spring · displacement');
            addLegend(springDisplacement, 'Spring · displacement', '#94a3b8');

            if (LWC.createSeriesMarkers) {{
                try {{ LWC.createSeriesMarkers(springDisplacement, Array.from(payload.spring?.turns || []), {{ autoScale: false }}); }} catch (_) {{}}
            }}

            const shock = chart.addSeries(LWC.LineSeries, {{
                title: '', color: '#64748b', lineWidth: 1, lineStyle: LWC.LineStyle.Dotted,
                priceScaleId: 'springAux', priceLineVisible: false, lastValueVisible: false,
            }}, 2);
            shock.setData(Array.from(payload.spring?.shock || []));
            registry.push(shock);
            labels.set(shock, 'Spring · shock z');
            addLegend(shock, 'Spring · shock z', '#64748b');

            const energy = chart.addSeries(LWC.LineSeries, {{
                title: '', color: '#475569', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed,
                priceScaleId: 'springAux', priceLineVisible: false, lastValueVisible: false,
                visible: false,
            }}, 2);
            energy.setData(Array.from(payload.spring?.energy || []));
            registry.push(energy);
            labels.set(energy, 'Spring · energy proxy');
            addLegend(energy, 'Spring · energy proxy', '#475569', false);
        }}

        const panes = chart.panes();
        if (panes.length >= 3) {{
            panes[0]?.setStretchFactor?.(.24);
            panes[1]?.setStretchFactor?.(.48);
            panes[2]?.setStretchFactor?.(.28);
        }}

        const allTimes = [];
        for (const point of Array.from(payload.live?.data || [])) allTimes.push(Number(point.time));
        for (const model of Array.from(payload.models || [])) {{
            for (const point of Array.from(model.data || [])) allTimes.push(Number(point.time));
        }}
        for (const point of springDisplacementData) allTimes.push(Number(point.time));
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
                if (label) parts.push(`${{label}} ${{numeric >= 0 ? '+' : ''}}${{numeric.toFixed(2)}}%`);
                if (parts.length >= 5) break;
            }}
            inspector.textContent = parts.join(' · ');
            inspector.style.opacity = parts.length ? '1' : '0';
        }});
        root.addEventListener('pointerleave', () => {{ inspector.style.opacity = '0'; }}, {{ passive: true }});

        chart.timeScale().fitContent();
    }}

    loadLibrary().then(build).catch((error) => {{
        parentElement.textContent = `P/L chart kunne ikke lastes: ${{error?.message || error}}`;
    }});
}}
"""


_pnl_component = st.components.v2.component(
    "pricegauger_lightweight_pnl_comparison_v1",
    js=_PNL_JS,
    isolate_styles=False,
)


def render_lightweight_pnl_comparison_v1(
    comparison: AutoManagerPnlComparisonV2,
    *,
    key: str,
) -> None:
    """Render persisted LIVE/model/Spring comparison in one Lightweight chart."""

    _pnl_component(
        key=key,
        data={"payload": build_lightweight_pnl_payload_v1(comparison)},
        height=900,
    )


__all__ = ["build_lightweight_pnl_payload_v1", "render_lightweight_pnl_comparison_v1"]
