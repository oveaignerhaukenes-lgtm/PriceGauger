from __future__ import annotations

from pathlib import Path

import context_overview_read_model_v2
from context_snapshot_v2 import (
    CONTEXT_CONTRACT_VERSION,
    FRESH,
    SCOPE_GLOBAL,
    ContextEvidenceRefV2,
    ContextSnapshotV2,
    ContextTargetStateV2,
)


def _snapshot() -> ContextSnapshotV2:
    return ContextSnapshotV2(
        snapshot_id="ctx-overview-1",
        as_of="2026-08-18T12:00:00+00:00",
        contract_version=CONTEXT_CONTRACT_VERSION,
        engine_version="context-test-v2",
        scope_key="global",
        freshness_status=FRESH,
        coverage_start="2026-08-18T11:00:00+00:00",
        coverage_end="2026-08-18T12:00:00+00:00",
        evidence=(
            ContextEvidenceRefV2(
                evidence_id="telegram:42",
                source_kind="TELEGRAM",
                source_scope=SCOPE_GLOBAL,
                source_id="Middle_East_Spectator:42",
                observed_at="2026-08-18T11:59:00+00:00",
                published_at="2026-08-18T11:58:00+00:00",
                tags=("geopolitics", "oil"),
            ),
        ),
        targets=(
            ContextTargetStateV2(
                target_key="BRENT",
                directional_bias=0.4,
                confidence=0.7,
                novelty=0.8,
                event_risk=0.6,
                summary="Geopolitical context tilts positive for oil.",
            ),
        ),
        regime_label="geopolitical-risk",
        summary="Context snapshot summary.",
    )


def test_context_overview_projects_only_canonical_context_contract(monkeypatch):
    snapshot = _snapshot()

    class FakeStore:
        def __init__(self, _path):
            pass

        def load_latest(self, *, scope_key):
            assert scope_key == "global"
            return snapshot

    monkeypatch.setattr(context_overview_read_model_v2, "ContextSnapshotStoreV2", FakeStore)
    view = context_overview_read_model_v2.load_context_overview_v2("unused.db")

    assert view is not None
    assert view.snapshot_id == snapshot.snapshot_id
    assert view.regime_label == "geopolitical-risk"
    assert view.targets[0].target_key == "BRENT"
    assert view.targets[0].direction_label == "BULLISH"
    assert view.evidence[0].source_kind == "TELEGRAM"
    assert view.evidence[0].tags == ("geopolitics", "oil")


def test_overview_page_has_no_legacy_semantic_or_decision_read_path():
    source = Path("pages/0_Oversikt.py").read_text(encoding="utf-8")
    assert "load_context_overview_v2" in source
    assert "render_v2_overview_market_cards" in source
    forbidden = (
        "overview_service",
        "load_overview(",
        "build_overview_summary",
        "StateRuntimeStore",
        "DecisionStateSnapshot",
        "ForecastStore",
        "information_state",
        "latest_alert",
        "process_flow_snapshot",
    )
    for token in forbidden:
        assert token not in source


def test_context_overview_read_model_does_not_import_raw_or_legacy_engines():
    source = Path("context_overview_read_model_v2.py").read_text(encoding="utf-8")
    assert "ContextSnapshotStoreV2" in source
    forbidden = (
        "TelegramFlowStore",
        "NewsContextStore",
        "StateRuntimeStore",
        "ForecastStore",
        "DecisionState",
        "Recommendation",
        "process_flow_snapshot",
        "openai",
    )
    for token in forbidden:
        assert token not in source


def test_overview_migration_marker_is_v2():
    source = Path("build_info.py").read_text(encoding="utf-8")
    start = source.index('"0_Oversikt.py"')
    marker = source[start : start + 320]
    assert '"V2"' in marker
    assert "ContextSnapshotV2" in marker
