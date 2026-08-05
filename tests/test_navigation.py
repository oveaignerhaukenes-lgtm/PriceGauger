from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_uses_explicit_grouped_navigation():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    navigation_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "navigation"
    ]

    assert len(navigation_calls) == 1
    assert '"PriceGauger": [overview, saxo]' in source
    assert '"System": system_pages' in source
    assert '"Analyseverksted": analysis_pages' in source
    assert '"Referansearkiv": reference_pages' in source
    assert 'title="Oversikt"' in source
    assert "default=True" in source


def test_every_streamlit_page_is_registered_explicitly():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    registered = {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "Page"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    actual = {
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (ROOT / "pages").glob("*.py")
    }

    assert registered == actual
