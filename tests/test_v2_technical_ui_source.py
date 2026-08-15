from pathlib import Path


def test_v2_technical_page_is_read_only_projection():
    source = Path("pages/9_V2_Technical.py").read_text(encoding="utf-8")

    assert "load_v2_overview_snapshots" in source
    assert "load_runtime_health_v2" in source
    assert "technical_interpreter_runtime_v2" not in source
    assert "openai" not in source.lower()
    assert "saxo_" not in source.lower()
    assert "persist_" not in source
    assert "execute" not in source.lower()
