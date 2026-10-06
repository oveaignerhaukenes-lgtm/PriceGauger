from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import autotrader_v3_multi_account_ui_v1 as ui


class _Rerun(Exception):
    pass


class _SessionState(dict):
    def __init__(self):
        super().__init__()
        self.locked = set()

    def __setitem__(self, key, value):
        if key in self.locked:
            raise AssertionError(f"late widget state mutation: {key}")
        super().__setitem__(key, value)


class _FakeStreamlit:
    def __init__(self, *, click_create=True):
        self.session_state = _SessionState()
        self.click_create = click_create

    def radio(self, _label, options, *, key, **_kwargs):
        if key not in self.session_state:
            self.session_state[key] = options[0]
        self.session_state.locked.add(key)
        return self.session_state[key]

    def popover(self, _label):
        return nullcontext()

    def expander(self, _label, **_kwargs):
        return nullcontext()

    def selectbox(self, _label, options, **_kwargs):
        return options[0]

    def button(self, _label, **_kwargs):
        return self.click_create

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def caption(self, *_args, **_kwargs):
        pass

    def success(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def rerun(self):
        raise _Rerun


def _instance(instance_id, account_id):
    return SimpleNamespace(
        instance_id=instance_id,
        account_id=account_id,
        market_name="US Tech 100 NAS",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=1,
        instrument_id=1,
        enabled=True,
    )




def _binding():
    return SimpleNamespace(
        key="1:1:4912:CfdOnIndex",
        label="US Tech 100 NAS · NAS · UIC 4912 · CfdOnIndex",
        market_name="US Tech 100 NAS",
        market_id=1,
        instrument_id=1,
        uic=4912,
        asset_type="CfdOnIndex",
    )

def test_create_defers_tab_selection_until_rerun(monkeypatch):
    old = _instance("old-id", "OLD")
    created = _instance("new-id", "NEW")
    fake = _FakeStreamlit(click_create=True)

    monkeypatch.setattr(ui, "st", fake)
    monkeypatch.setattr(ui, "bootstrap_v3_instances_from_enrollments_v1", lambda: (old,))
    monkeypatch.setattr(
        ui,
        "configured_live_pilot_client_v3",
        lambda: SimpleNamespace(accounts=lambda: ({"AccountId": "NEW", "AccountName": "Ny"},)),
    )
    monkeypatch.setattr(ui, "load_account_owner_v1", lambda _account_id: None)
    monkeypatch.setattr(ui, "load_available_v3_instrument_bindings_v1", lambda: (_binding(),))
    monkeypatch.setattr(ui, "same_v3_binding_v1", lambda instance, target: True)
    monkeypatch.setattr(ui, "create_v3_instance_v1", lambda **_kwargs: created)

    with pytest.raises(_Rerun):
        ui.render_v3_instance_selector_v1(key_prefix="test")

    assert fake.session_state["test:tabs"] == "old-id"
    assert fake.session_state["test:pending-tab"] == "new-id"


def test_pending_tab_is_applied_before_radio_widget_is_instantiated(monkeypatch):
    old = _instance("old-id", "OLD")
    created = _instance("new-id", "NEW")
    fake = _FakeStreamlit(click_create=False)
    fake.session_state["test:pending-tab"] = "new-id"

    monkeypatch.setattr(ui, "st", fake)
    monkeypatch.setattr(ui, "bootstrap_v3_instances_from_enrollments_v1", lambda: (old, created))
    monkeypatch.setattr(
        ui,
        "configured_live_pilot_client_v3",
        lambda: SimpleNamespace(accounts=lambda: ({"AccountId": "OLD"}, {"AccountId": "NEW"})),
    )
    monkeypatch.setattr(ui, "load_account_owner_v1", lambda _account_id: None)
    monkeypatch.setattr(ui, "load_available_v3_instrument_bindings_v1", lambda: (_binding(),))
    monkeypatch.setattr(ui, "same_v3_binding_v1", lambda instance, target: True)

    selected = ui.render_v3_instance_selector_v1(key_prefix="test")

    assert selected.instance_id == "new-id"
    assert fake.session_state["test:tabs"] == "new-id"
    assert "test:pending-tab" not in fake.session_state
