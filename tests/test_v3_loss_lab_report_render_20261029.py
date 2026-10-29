"""Regression: filled Saxo accounts must render their 03:00 baseline offset.

The live data-based result path previously crashed with KeyError due to
writing 'Avvik fra 03 (min)' but reading 'Forsinkelse etter 03 (min)'.
Pure CI passed because it tested calculations, not the result view.
"""
from pathlib import Path
import ast


def test_loss_lab_baseline_render_key_matches_account_report():
    source=Path("pages/0_AutoTrader_Loss_Lab.py").read_text()
    ast.parse(source)
    assert '"Avvik fra 03 (min)":result.baseline_delay_minutes' in source
    assert 'if row["Avvik fra 03 (min)"] is not None' in source
    assert 'row[\'Avvik fra 03 (min)\']' in source
    assert '"Forsinkelse etter 03 (min)"' not in source
    assert 'st.subheader("1 · Faktiske Saxo-snapshot siden 03:00")' in source
