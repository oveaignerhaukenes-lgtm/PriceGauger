"""Discoverable V3 AI LIVE presets; never introduce fictional strategy keys.

The canonical V3 strategy remains deterministic. Selecting a preset fills its
base strategy, timeframe and 'ai-loss-manager' modifier in the UI draft only.
Only the usual 'Bruk på denne instansen' action persists those values.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AILivePresetV3:
    selector_key: str
    strategy_key: str
    timeframe: str
    label: str


AI_LIVE_PRESETS_V3: tuple[AILivePresetV3, ...] = (
    AILivePresetV3(
        "ai-live:macd-flip:2m", "macd-flip", "2m",
        "AI-oppsett · MACD Flip 2m + AI Loss Manager",
    ),
    AILivePresetV3(
        "ai-live:macd-histogram:2m", "macd-histogram", "2m",
        "AI-oppsett · MACD Histogram 2m + AI Loss Manager",
    ),
)
PRESETS_BY_KEY_V3={item.selector_key:item for item in AI_LIVE_PRESETS_V3}


def initial_selector_key_v3(*, strategy_key: str, timeframe: str,
                            modifiers: tuple[str, ...]) -> str:
    """Read existing saved LIVE config without adding/modifying any option."""
    if "ai-loss-manager" in modifiers:
        for item in AI_LIVE_PRESETS_V3:
            if item.strategy_key == strategy_key and item.timeframe == timeframe:
                return item.selector_key
    return strategy_key


def resolve_selector_draft_v3(*, selector_key: str, timeframe: str,
                              modifiers: tuple[str, ...]) -> tuple[str, str, tuple[str, ...]]:
    """Translate display-only choices into the existing canonical V3 config."""
    preset=PRESETS_BY_KEY_V3.get(selector_key)
    if preset is None:
        return selector_key,timeframe,modifiers
    return (preset.strategy_key,preset.timeframe,
            tuple(dict.fromkeys((*modifiers,"ai-loss-manager"))))


def ai_preset_selected_v3(selector_key: str) -> bool:
    return selector_key in PRESETS_BY_KEY_V3


__all__=[
    "AILivePresetV3","AI_LIVE_PRESETS_V3","PRESETS_BY_KEY_V3",
    "initial_selector_key_v3","resolve_selector_draft_v3",
    "ai_preset_selected_v3",
]
