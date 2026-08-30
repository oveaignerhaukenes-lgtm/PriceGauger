from __future__ import annotations

import ast
from pathlib import Path

from navigation_config import PAGE_GROUPS


ROOT = Path(__file__).resolve().parents[1]

# These modules belong to the retired Information/Decision/Recommendation and
# pre-v2 forecast/market-state stack. They may remain temporarily in the tree
# while deletion is staged, but no active production entrypoint may reach them.
RETIRED_V1_MODULES = {
    "ai_market_assessment",
    "decision_engine",
    "decision_engine_components",
    "decision_trace",
    "forecast_contracts",
    "forecast_store",
    "historical_engine",
    "historical_engine_ui",
    "historical_signal_store",
    "holistic_composer_v1",
    "market_state",
    "market_state_service",
    "market_state_store",
    "market_state_ui",
    "overview_ai_summary",
    "overview_recommendation_display",
    "overview_service",
    "overview_summary_contract",
    "overview_summary_store",
    "signal_aggregator",
    "signal_outcomes",
    "signal_persistence",
    "signal_store",
    "state_contracts",
    "state_runtime_pipeline",
    "state_runtime_service",
    "state_runtime_store",
}

RUNTIME_ENTRYPOINTS = {
    "app.py",
    "runtime_entrypoint.py",
    "worker.py",
    "realtime_worker.py",
}


def _active_entrypoints() -> set[str]:
    pages = {
        page["page"]
        for group in PAGE_GROUPS.values()
        for page in group
    }
    return RUNTIME_ENTRYPOINTS | pages


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _local_module_path(module_name: str) -> Path | None:
    parts = module_name.split(".")
    module_file = ROOT.joinpath(*parts).with_suffix(".py")
    if module_file.is_file():
        return module_file
    package_init = ROOT.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init
    return None


def _reachable_local_imports(entrypoints: set[str]) -> tuple[set[str], dict[str, str]]:
    queue = [ROOT / path for path in sorted(entrypoints)]
    visited: set[Path] = set()
    reached_modules: set[str] = set()
    parents: dict[str, str] = {}

    while queue:
        path = queue.pop()
        if path in visited:
            continue
        assert path.is_file(), f"active entrypoint missing: {path.relative_to(ROOT)}"
        visited.add(path)
        importer = str(path.relative_to(ROOT))
        for imported in _imports(path):
            root_name = imported.split(".", 1)[0]
            reached_modules.add(root_name)
            parents.setdefault(root_name, importer)
            local_path = _local_module_path(imported)
            if local_path is not None and local_path not in visited:
                queue.append(local_path)
    return reached_modules, parents


def test_active_runtime_import_graph_cannot_reach_retired_v1_semantic_stack() -> None:
    reached, parents = _reachable_local_imports(_active_entrypoints())
    violations = sorted(RETIRED_V1_MODULES & reached)
    detail = ", ".join(f"{name} via {parents.get(name, '?')}" for name in violations)
    assert not violations, f"active production graph reaches retired v1 modules: {detail}"


def test_active_navigation_contains_no_retired_v1_page_paths() -> None:
    active_pages = {
        page["page"]
        for group in PAGE_GROUPS.values()
        for page in group
    }
    retired_pages = {
        "pages/1_Kjerneflyt.py",
        "pages/2_Direct_Technical.py",
        "pages/5_AI_Market_Assessment.py",
        "pages/2_Signalaggregat.py",
        "pages/Market_State.py",
        "pages/Signal_History.py",
        "pages/7_Forecast_Learning.py",
        "pages/1_Historical_Event_Lab.py",
    }
    assert retired_pages.isdisjoint(active_pages)
