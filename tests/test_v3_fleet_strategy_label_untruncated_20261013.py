"""Fleet must present the complete strategy; metric values visually elide text."""
from pathlib import Path

from autotrader_v3_registry_v1 import strategy_display_label_v3


def test_fleet_renders_strategy_in_full_width_text_not_metric():
    source=Path("autotrader_v3_fleet_ui_v1.py").read_text(encoding="utf-8")
    assert "st.markdown(f'**Strategi:** {active_label}')" in source
    assert ".metric('Strategi',active_label)" not in source
    assert "c=st.columns([2,1,1,1])" in source


def test_regime_and_signal_periods_are_visible_in_strategy_label():
    # Full label can be long: it must not be clipped by metric cell CSS.
    label=strategy_display_label_v3("aen21-sticky-fast-exit","10m","30m")
    assert "R30m/S10m" in label
    assert "Fast Exit" in label
    label2=strategy_display_label_v3("macd-regime-histogram","5m","15m")
    assert "R15mS5m" in label2
