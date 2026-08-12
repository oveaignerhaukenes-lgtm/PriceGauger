from pathlib import Path


def test_tradingdesk_exposes_autotrader_mode_controls() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'st.header("AutoTrader")' in source
    assert '"Modus",' in source
    assert "AUTOTRADER_MODES" in source
    assert '"Steg per kryss"' in source
    assert 'selected_timeframe="30m"' in source
    assert "latest_macd_crossover_intent" in source
    assert "ingen ordre sendes" in source
