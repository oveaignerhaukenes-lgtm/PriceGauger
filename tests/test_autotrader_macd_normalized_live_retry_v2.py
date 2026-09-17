from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import autotrader_macd_normalized_live_v2 as retry
from autotrader_fast_live_runtime_v2 import FastLiveCycleV2, FastLiveStateV2


def test_pending_retry_rearms_exact_terminal_request(monkeypatch) -> None:
    enrollment = SimpleNamespace(pilot_key="pilot", strategy_key="macd-norm-manager-v1")
    state = FastLiveStateV2(
        pilot_key="pilot",
        strategy_key="macd-norm-manager-v1",
        desired_direction="SHORT",
        pending_target_direction="SHORT",
        intent_signal_at=datetime(2026, 9, 17, 5, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(retry, "load_fast_live_state_v2", lambda _enrollment: state)
    monkeypatch.setattr(retry, "_exact_product_observation", lambda _enrollment, _observations: None)
    monkeypatch.setattr(retry, "_observed_direction", lambda _observation: "FLAT")
    monkeypatch.setattr(retry, "_matching_intent_request_exists_v1", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(retry, "_rearm_retryable_terminal_request_v1", lambda *_args, **_kwargs: True)

    existed, rearmed = retry._prepare_pending_retry_v2(enrollment, observations=())

    assert existed is True
    assert rearmed is True


def test_existing_nonterminal_request_is_not_reported_as_fresh_retry(monkeypatch) -> None:
    enrollment = SimpleNamespace(pilot_key="pilot", strategy_key="macd-norm-manager-v1")
    at = datetime(2026, 9, 17, 6, 44, tzinfo=timezone.utc)
    monkeypatch.setattr(retry, "_prepare_pending_retry_v2", lambda *_args, **_kwargs: (True, False))
    monkeypatch.setattr(
        retry,
        "_run_macd_normalized_live_once_v1",
        lambda *_args, **_kwargs: FastLiveCycleV2(
            "pilot",
            "macd-norm-manager-v1",
            "SHORT",
            "FLAT",
            "SHORT",
            at,
            False,
            True,
            False,
            "PENDING_TRANSITION_RETRY_READY",
        ),
    )

    cycle = retry.run_macd_normalized_live_once_v2(enrollment, observations=())

    assert cycle.request_created is False
    assert cycle.reason == "PENDING_TRANSITION_CONTINUED"


def test_rearmed_terminal_request_is_reported_as_real_retry(monkeypatch) -> None:
    enrollment = SimpleNamespace(pilot_key="pilot", strategy_key="macd-norm-manager-v1")
    at = datetime(2026, 9, 17, 6, 44, tzinfo=timezone.utc)
    monkeypatch.setattr(retry, "_prepare_pending_retry_v2", lambda *_args, **_kwargs: (True, True))
    monkeypatch.setattr(
        retry,
        "_run_macd_normalized_live_once_v1",
        lambda *_args, **_kwargs: FastLiveCycleV2(
            "pilot",
            "macd-norm-manager-v1",
            "SHORT",
            "FLAT",
            "SHORT",
            at,
            False,
            True,
            False,
            "PENDING_TRANSITION_RETRY_READY",
        ),
    )

    cycle = retry.run_macd_normalized_live_once_v2(enrollment, observations=())

    assert cycle.request_created is True
    assert cycle.reason == "PENDING_TRANSITION_RETRY_READY"


def test_dispatch_uses_retry_facade_without_new_broker_authority() -> None:
    dispatch = Path("autotrader_automanage_dispatch_v2.py").read_text(encoding="utf-8")
    facade = Path("autotrader_macd_normalized_live_v2.py").read_text(encoding="utf-8").lower()

    assert "from autotrader_macd_normalized_live_v2 import" in dispatch
    assert "_rearm_retryable_terminal_request_v1" in facade
    assert "status = 'pending'" not in facade
    for forbidden in ("trade/v2/orders", "client.post(", "requests.post(", "place_order("):
        assert forbidden not in facade
