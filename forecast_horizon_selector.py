from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import urlencode

from forecast_contracts import DEFAULT_FORECAST_HORIZON_HOURS, FORECAST_HORIZONS_HOURS


@dataclass(frozen=True, slots=True)
class ForecastHorizonOption:
    token: str
    label: str
    hours: float


FORECAST_HORIZON_OPTIONS = (
    ForecastHorizonOption("5m", "5m", 5.0 / 60.0),
    ForecastHorizonOption("15m", "15m", 15.0 / 60.0),
    ForecastHorizonOption("30m", "30m", 30.0 / 60.0),
    ForecastHorizonOption("1h", "1t", 1.0),
    ForecastHorizonOption("4h", "4t", 4.0),
    ForecastHorizonOption("12h", "12t", 12.0),
    ForecastHorizonOption("24h", "24t", 24.0),
    ForecastHorizonOption("7d", "7d", 168.0),
)

_HORIZON_BY_TOKEN = {item.token: item.hours for item in FORECAST_HORIZON_OPTIONS}
_SESSION_PREFIX = "overview_forecast_horizon:"


def _same_horizon(left: float | None, right: float, *, tolerance: float = 1e-6) -> bool:
    return left is not None and abs(float(left) - float(right)) <= tolerance


def horizon_from_token(token: str | None) -> float | None:
    return _HORIZON_BY_TOKEN.get(str(token or "").strip().lower())


def supported_horizon(value: float | None) -> bool:
    return value is not None and any(_same_horizon(value, item.hours) for item in FORECAST_HORIZON_OPTIONS)


def horizon_session_key(market: str) -> str:
    return f"{_SESSION_PREFIX}{str(market)}"


def selected_horizons_from_session(session_state) -> dict[str, float]:
    selected: dict[str, float] = {}
    for key, value in session_state.items():
        key_text = str(key)
        if not key_text.startswith(_SESSION_PREFIX):
            continue
        market = key_text[len(_SESSION_PREFIX) :].strip()
        try:
            hours = float(value)
        except (TypeError, ValueError):
            continue
        if market and supported_horizon(hours):
            selected[market] = hours
    return selected


def selected_horizon_for_market(session_state, market: str) -> float:
    value = session_state.get(horizon_session_key(market), DEFAULT_FORECAST_HORIZON_HOURS)
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return DEFAULT_FORECAST_HORIZON_HOURS
    return hours if supported_horizon(hours) else DEFAULT_FORECAST_HORIZON_HOURS


def apply_horizon_query(session_state, *, market: str | None, token: str | None) -> bool:
    market_name = str(market or "").strip()
    hours = horizon_from_token(token)
    if not market_name or hours is None:
        return False
    session_state[horizon_session_key(market_name)] = hours
    return True


def render_horizon_selector_html(market: str, selected_hours: float | None) -> str:
    """Render compact navigation controls for the forecast chart's right rail."""
    active = (
        float(selected_hours)
        if selected_hours is not None and supported_horizon(float(selected_hours))
        else DEFAULT_FORECAST_HORIZON_HOURS
    )
    buttons: list[str] = []
    for option in FORECAST_HORIZON_OPTIONS:
        query = urlencode({"forecast_market": market, "forecast_horizon": option.token})
        active_class = " is-active" if _same_horizon(active, option.hours) else ""
        current = ' aria-current="true"' if active_class else ""
        buttons.append(
            f'<a class="pg-horizon-btn{active_class}" href="?{html.escape(query, quote=True)}" '
            f'target="_self" title="Vis {html.escape(option.label)} prognose"{current}>'
            f'{html.escape(option.label)}</a>'
        )
    return (
        '<nav class="pg-horizon-selector" aria-label="Velg prognosehorisont">'
        + "".join(buttons)
        + "</nav>"
    )


assert tuple(item.hours for item in FORECAST_HORIZON_OPTIONS) == FORECAST_HORIZONS_HOURS
