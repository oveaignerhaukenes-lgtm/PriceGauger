from __future__ import annotations

import inspect

import context_source_policy_v2
from context_source_policy_v2 import (
    ContextSourceKeyV2,
    ContextSourcePolicyStoreV2,
    ContextSourcePolicyV2,
)


def test_default_policy_is_conservative_for_unknown_source():
    source = ContextSourceKeyV2(source_kind="TELEGRAM", source_id="new-channel")
    policy = ContextSourcePolicyV2(source=source)

    assert policy.exposure_enabled is True
    assert policy.composition_enabled is False
    assert policy.identity_enabled is False
    assert policy.learning_enabled is False


def test_policy_axes_are_independent():
    source = ContextSourceKeyV2(source_kind="TELEGRAM", source_id="trial")
    policy = ContextSourcePolicyV2(
        source=source,
        exposure_enabled=False,
        composition_enabled=True,
        identity_enabled=False,
        learning_enabled=True,
    )

    assert policy.exposure_enabled is False
    assert policy.composition_enabled is True
    assert policy.identity_enabled is False
    assert policy.learning_enabled is True


def test_user_scoped_source_identity_is_separate_per_user():
    a = ContextSourceKeyV2(
        source_kind="TELEGRAM",
        source_id="channel-42",
        source_scope="USER_SCOPED",
        user_scope_id="user-a",
    )
    b = ContextSourceKeyV2(
        source_kind="TELEGRAM",
        source_id="channel-42",
        source_scope="USER_SCOPED",
        user_scope_id="user-b",
    )

    assert a.source_key != b.source_key


def test_store_round_trip_and_partial_policy_change(tmp_path):
    store = ContextSourcePolicyStoreV2(tmp_path / "policy.db")
    source = ContextSourceKeyV2(source_kind="GDELT", source_id="global-feed")

    default = store.load(source)
    changed = default.with_changes(composition_enabled=True, learning_enabled=True)
    store.save(changed)
    loaded = store.load(source)

    assert loaded.source == source
    assert loaded.exposure_enabled is True
    assert loaded.composition_enabled is True
    assert loaded.identity_enabled is False
    assert loaded.learning_enabled is True
    assert loaded.updated_at


def test_list_all_preserves_global_and_user_scoped_policies(tmp_path):
    store = ContextSourcePolicyStoreV2(tmp_path / "policy.db")
    global_source = ContextSourceKeyV2(source_kind="GDELT", source_id="global")
    personal_source = ContextSourceKeyV2(
        source_kind="TELEGRAM",
        source_id="my-channel",
        source_scope="USER_SCOPED",
        user_scope_id="user-1",
    )
    store.save(ContextSourcePolicyV2(source=global_source).with_changes(composition_enabled=True))
    store.save(ContextSourcePolicyV2(source=personal_source).with_changes(identity_enabled=True))

    policies = store.list_all()
    assert {item.source.source_key for item in policies} == {
        global_source.source_key,
        personal_source.source_key,
    }


def test_policy_module_has_no_runtime_learning_composer_or_execution_authority():
    source = inspect.getsource(context_source_policy_v2)
    forbidden = (
        "compose_holistic_forecast",
        "context_adapter_v2",
        "state_runtime_pipeline",
        "openai",
        "place_order",
        "AutoTrader",
        "fit(",
        "train(",
    )
    for token in forbidden:
        assert token not in source
