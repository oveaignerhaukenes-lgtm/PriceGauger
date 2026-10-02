from pathlib import Path


def test_v2_margin_controls_expose_existing_envelope_settings():
    source = Path("tradingdesk_v2_margin_controls_v1.py").read_text(encoding="utf-8")
    assert "load_pilot_margin_config_v2" in source
    assert "save_pilot_margin_config_v2" in source
    assert '"Maks effektiv gearing"' in source
    assert 'f"Fri-margin-buffer ({currency})"' in source
    assert '"Lagre Margin Envelope"' in source
    assert "Saxo-precheck" in source
