"""Guard AEn replay UI against local import shadowing (UnboundLocalError)."""
from __future__ import annotations

import ast
from pathlib import Path
import symtable


def test_aen_ui_replay_feature_preparation_is_global_not_local():
    path = Path("aen_lab_ui_v1.py")
    source = path.read_text(encoding="utf-8")
    symbols = symtable.symtable(source, str(path), "exec")

    render = next(
        block for block in symbols.get_children()
        if block.get_name() == "render_aen_core_lab_v1"
    )
    prepared = render.lookup("prepare_replay_inputs")
    assert prepared.is_global()
    assert not prepared.is_local()

    parsed = ast.parse(source)
    imports = [
        node for node in parsed.body
        if isinstance(node, ast.ImportFrom) and node.module == "aen_replay_v1"
    ]
    assert any(
        alias.name == "prepare_replay_inputs"
        for statement in imports for alias in statement.names
    )


def test_aen_ui_all_comparison_paths_reuse_module_level_import():
    source = Path("aen_lab_ui_v1.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    func = next(node for node in parsed.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "render_aen_core_lab_v1")
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "aen_replay_v1"
        and any(alias.name == "prepare_replay_inputs" for alias in node.names)
        for node in ast.walk(func)
    )
    calls = [node for node in ast.walk(func)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "prepare_replay_inputs"]
    assert len(calls) == 1
