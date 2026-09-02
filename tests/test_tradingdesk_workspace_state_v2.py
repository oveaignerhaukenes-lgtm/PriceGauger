from __future__ import annotations

from types import SimpleNamespace

import tradingdesk_workspace_state_v2 as workspace
from ui_workspace_state_v2 import UiWorkspaceStateV2


class _FakeStreamlit:
    def __init__(self, *, session_state=None, query_params=None):
        self.session_state = dict(session_state or {})
        self.query_params = dict(query_params or {})


def _persisted(**state):
    return UiWorkspaceStateV2(
        page_key=workspace.PAGE_KEY,
        schema_version=workspace.SCHEMA_VERSION,
        state=dict(state),
    )


def test_persisted_market_and_safe_view_state_restore_after_new_session(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setattr(workspace, "st", fake)
    monkeypatch.setattr(workspace, "_has_streamlit_run_context", lambda: True)
    monkeypatch.setattr(
        workspace,
        "load_ui_workspace_state_v2",
        lambda *args, **kwargs: _persisted(
            selected_market="US Tech 100 NAS · Saxo 4912",
            timeframe="10m",
            macd_timeframe="30m",
            auto_refresh=False,
            controls_width_pct=36,
        ),
    )
    saved = []
    monkeypatch.setattr(workspace, "save_ui_workspace_state_v2", lambda *args, **kwargs: saved.append((args, kwargs)))

    selected = workspace.sync_tradingdesk_workspace_state_v2(
        ["Brent", "US Tech 100 NAS · Saxo 4912"]
    )

    assert selected == "US Tech 100 NAS · Saxo 4912"
    assert fake.session_state[workspace.MARKET_SESSION_KEY] == selected
    assert fake.session_state[workspace.TIMEFRAME_SESSION_KEY] == "10m"
    assert fake.session_state[workspace.MACD_TIMEFRAME_SESSION_KEY] == "30m"
    assert fake.session_state[workspace.AUTO_REFRESH_SESSION_KEY] is False
    assert fake.session_state[workspace.CONTROLS_WIDTH_SESSION_KEY] == 36
    assert saved == []


def test_explicit_market_query_wins_and_updates_durable_state(monkeypatch):
    fake = _FakeStreamlit(query_params={"market": "US Tech 100 NAS · Saxo 4912"})
    monkeypatch.setattr(workspace, "st", fake)
    monkeypatch.setattr(workspace, "_has_streamlit_run_context", lambda: True)
    monkeypatch.setattr(
        workspace,
        "load_ui_workspace_state_v2",
        lambda *args, **kwargs: _persisted(selected_market="Brent"),
    )
    saved = []

    def _save(page_key, state, **kwargs):
        saved.append((page_key, dict(state), kwargs))
        return _persisted(**state)

    monkeypatch.setattr(workspace, "save_ui_workspace_state_v2", _save)

    selected = workspace.sync_tradingdesk_workspace_state_v2(
        ["Brent", "US Tech 100 NAS · Saxo 4912"]
    )

    assert selected == "US Tech 100 NAS · Saxo 4912"
    assert saved[-1][1] == {"selected_market": "US Tech 100 NAS · Saxo 4912"}


def test_current_session_selection_is_persisted(monkeypatch):
    fake = _FakeStreamlit(
        session_state={workspace.MARKET_SESSION_KEY: "US Tech 100 NAS · Saxo 4912"}
    )
    monkeypatch.setattr(workspace, "st", fake)
    monkeypatch.setattr(workspace, "_has_streamlit_run_context", lambda: True)
    monkeypatch.setattr(
        workspace,
        "load_ui_workspace_state_v2",
        lambda *args, **kwargs: _persisted(selected_market="Brent"),
    )
    saved = []
    monkeypatch.setattr(
        workspace,
        "save_ui_workspace_state_v2",
        lambda page_key, state, **kwargs: saved.append(dict(state)),
    )

    workspace.sync_tradingdesk_workspace_state_v2(
        ["Brent", "US Tech 100 NAS · Saxo 4912"]
    )

    assert saved[-1]["selected_market"] == "US Tech 100 NAS · Saxo 4912"


def test_stale_saved_market_fails_softly_to_page_default(monkeypatch):
    fake = _FakeStreamlit()
    monkeypatch.setattr(workspace, "st", fake)
    monkeypatch.setattr(workspace, "_has_streamlit_run_context", lambda: True)
    monkeypatch.setattr(
        workspace,
        "load_ui_workspace_state_v2",
        lambda *args, **kwargs: _persisted(selected_market="Delisted market"),
    )
    saved = []
    monkeypatch.setattr(workspace, "save_ui_workspace_state_v2", lambda *args, **kwargs: saved.append(True))

    selected = workspace.sync_tradingdesk_workspace_state_v2(["Brent", "Gold"])

    assert selected is None
    assert workspace.MARKET_SESSION_KEY not in fake.session_state
    assert saved == []


def test_workspace_restore_allowlist_cannot_persist_execution_authority(monkeypatch):
    fake = _FakeStreamlit(
        session_state={
            workspace.MARKET_SESSION_KEY: "Gold",
            "live_open_armed": True,
            "entry_mode": "AUTO",
            "approval_request_id": "must-not-persist",
        }
    )
    monkeypatch.setattr(workspace, "st", fake)
    monkeypatch.setattr(workspace, "_has_streamlit_run_context", lambda: True)
    monkeypatch.setattr(workspace, "load_ui_workspace_state_v2", lambda *args, **kwargs: None)
    saved = []
    monkeypatch.setattr(
        workspace,
        "save_ui_workspace_state_v2",
        lambda page_key, state, **kwargs: saved.append(dict(state)),
    )

    workspace.sync_tradingdesk_workspace_state_v2(["Gold"])

    assert saved == [{"selected_market": "Gold"}]
    assert set(workspace._SAFE_SESSION_KEYS) == {
        "selected_market",
        "timeframe",
        "macd_timeframe",
        "auto_refresh",
        "controls_width_pct",
    }
