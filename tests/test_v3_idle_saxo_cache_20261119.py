"""Idle GET reduction must never turn a cached observation into POST authority."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from threading import Lock

import pytest

from autotrader_v3_idle_saxo_cache_v1 import (
    IDLE_SAXO_POLL_SECONDS_V1, V3IdleSaxoCacheV1,
)
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import LIVE_BASE_URL


class SharedTruth:
    def __init__(self):
        self.account_calls = 0
        self.position_calls = 0
        self.amount = 0.01
        self.account_key = 'original-key'
        self.fail_accounts = False
        self.fail_position = False
        self.lock = Lock()


class StubLive(SaxoLivePilotClientV3):
    def __init__(self, truth):
        self.client = SimpleNamespace(base_url=LIVE_BASE_URL)
        self._account_identity_rows = None
        self.truth = truth

    def accounts(self):
        with self.truth.lock:
            self.truth.account_calls += 1
        if self.truth.fail_accounts:
            raise ConnectionError('Saxo accounts unavailable')
        self._account_identity_rows = (('A', self.truth.account_key, 'client'),)
        return ({'AccountId': 'A', 'AccountKey': self.truth.account_key,
                 'ClientKey': 'client'},)

    def signed_inventory_exact(self, *, account_id, uic, asset_type):
        assert self._account_identity_rows is not None
        assert account_id == 'A' and int(uic) in (4912, 4913)
        with self.truth.lock:
            self.truth.position_calls += 1
        if self.truth.fail_position:
            raise ConnectionError('Saxo position unavailable')
        return self.truth.amount

    def place_order(self, *args, **kwargs):
        raise AssertionError('a cache must never send Saxo POST')


class OtherAdapter:
    def __init__(self):
        self.calls = 0

    def accounts(self):
        self.calls += 1
        return ({'AccountId': 'test'},)

    def signed_inventory_exact(self, **kwargs):
        self.calls += 1
        return 0.01


def env(uic=4912):
    return SimpleNamespace(account_id='A', uic=uic, asset_type='CfdOnIndex')


def test_idle_reads_share_60_seconds_across_new_live_broker_sessions():
    now = [200.0]
    cache = V3IdleSaxoCacheV1(clock=lambda: now[0])
    truth = SharedTruth()
    first, second = StubLive(truth), StubLive(truth)
    assert cache.accounts(first)[0]['AccountKey'] == 'original-key'
    assert cache.position(env(), first) == .01
    assert cache.accounts(second)[0]['AccountKey'] == 'original-key'
    assert second._account_identity_rows == first._account_identity_rows
    assert cache.position(env(), second) == .01
    assert (truth.account_calls, truth.position_calls) == (1, 1)

    now[0] += IDLE_SAXO_POLL_SECONDS_V1 - .001
    cache.accounts(second)
    cache.position(env(), second)
    assert (truth.account_calls, truth.position_calls) == (1, 1)
    now[0] += .002
    cache.accounts(second)
    cache.position(env(), second)
    assert (truth.account_calls, truth.position_calls) == (2, 2)


def test_position_keys_are_exact_and_invalidation_is_immediate():
    now = [0.0]
    cache = V3IdleSaxoCacheV1(clock=lambda: now[0])
    truth = SharedTruth()
    broker = StubLive(truth)
    cache.accounts(broker)
    cache.position(env(), broker)
    cache.position(env(4913), broker)
    assert truth.position_calls == 2
    cache.invalidate_position(env(), broker)
    cache.position(env(), broker)
    cache.position(env(4913), broker)
    assert truth.position_calls == 3


def test_fresh_pre_submit_refuses_manual_inventory_or_identity_changes():
    cache = V3IdleSaxoCacheV1(clock=lambda: 100.)
    truth = SharedTruth()
    broker = StubLive(truth)
    cache.accounts(broker)
    assert cache.position(env(), broker) == .01
    assert cache.verified_pre_submit(env(), broker,
        account_key='original-key', observed_amount=.01) == (True, .01)
    truth.amount = 0.
    assert cache.verified_pre_submit(env(), broker,
        account_key='original-key', observed_amount=.01) == (False, 0.)
    truth.amount = .01
    truth.account_key = 'changed-key'
    assert cache.verified_pre_submit(env(), broker,
        account_key='original-key', observed_amount=.01) == (False, .01)
    assert truth.account_calls == truth.position_calls == 4


def test_failed_required_fresh_get_never_silently_uses_old_idle_truth():
    cache = V3IdleSaxoCacheV1(clock=lambda: 100.)
    truth = SharedTruth()
    broker = StubLive(truth)
    cache.accounts(broker)
    cache.position(env(), broker)
    truth.fail_position = True
    with pytest.raises(ConnectionError):
        cache.verified_pre_submit(env(), broker,
            account_key='original-key', observed_amount=.01)
    truth.fail_position = False
    truth.fail_accounts = True
    with pytest.raises(ConnectionError):
        cache.verified_pre_submit(env(), broker,
            account_key='original-key', observed_amount=.01)


def test_concurrent_sessions_use_single_flight_for_idle_gets():
    cache = V3IdleSaxoCacheV1(clock=lambda: 100.)
    truth = SharedTruth()

    def do_read(_):
        broker = StubLive(truth)
        cache.accounts(broker)
        return cache.position(env(), broker)

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert list(pool.map(do_read, range(24))) == [.01] * 24
    assert (truth.account_calls, truth.position_calls) == (1, 1)


def test_non_live_fake_adapter_keeps_exact_uncached_semantics():
    cache = V3IdleSaxoCacheV1(clock=lambda: 10.)
    other = OtherAdapter()
    assert cache.accounts(other) == cache.accounts(other)
    assert cache.position(env(), other) == cache.position(env(), other)
    assert other.calls == 4


def test_runtime_requires_fresh_broker_truth_after_reservation_before_order():
    source = (Path(__file__).resolve().parent.parent /
              'autotrader_v3_live_runtime_v1.py').read_text()
    after_claim = source.index('if not claim_reserved_for_submission_v3(')
    verify = source.index('IDLE_SAXO_CACHE_V1.verified_pre_submit(', after_claim)
    recheck = source.index('current_owner=load_account_owner_v1(', after_claim)
    post = source.index('result=broker.place_order(', after_claim)
    assert after_claim < verify < recheck < post
    assert "mark_order_v3(request_key=request_key,state='REJECTED'" in source[verify:recheck]
    pending = source.index('if pending:')
    assert source.index('IDLE_SAXO_CACHE_V1.invalidate_position(e,broker)', pending) < source.index(
        'fresh_actual=_actual(e,broker)', pending)
