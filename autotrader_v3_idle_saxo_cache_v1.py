"""60s read sharing for idle V3 cycles; never an order or broker truth source.

The LIVE runtime MUST force fresh inventory and account identity before every
broker POST. Unresolved orders bypass this cache and remain fail-closed.
This is process-local, monotonic and scoped to exact Saxo account/product.
"""
from __future__ import annotations

from math import isfinite
from threading import Lock
import time

from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3


IDLE_SAXO_POLL_SECONDS_V1 = 60.0


class V3IdleSaxoCacheV1:
    def __init__(self, *, clock=None):
        self._clock = clock or time.monotonic
        self._accounts_lock = Lock()
        self._accounts = None
        self._accounts_at = None
        self._accounts_scope = None
        self._positions_lock = Lock()
        self._positions = {}
        self._position_locks = {}

    @staticmethod
    def applies_to(broker) -> bool:
        return isinstance(broker, SaxoLivePilotClientV3)

    @staticmethod
    def _scope(broker) -> str:
        return str(broker.client.base_url).rstrip('/').lower()

    def accounts(self, broker, *, force=False):
        if not self.applies_to(broker):
            return broker.accounts()
        scope = self._scope(broker)
        with self._accounts_lock:
            now = self._clock()
            if (not force and self._accounts_scope == scope
                and self._accounts is not None and self._accounts_at is not None
                and 0 <= now-self._accounts_at < IDLE_SAXO_POLL_SECONDS_V1):
                rows, identities = self._accounts
                # Every new adapter must receive the exact same validated
                # account identity set before it can scope a Saxo query.
                broker._account_identity_rows = identities
                return rows
            rows = tuple(broker.accounts())
            identities = broker._account_identity_rows
            if rows and identities:
                self._accounts = (rows, identities)
                self._accounts_at = self._clock()
                self._accounts_scope = scope
            else:
                self._accounts = None
                self._accounts_at = None
                self._accounts_scope = None
            return rows

    def _position_key(self, e, broker):
        return (self._scope(broker), str(e.account_id), int(e.uic), str(e.asset_type))

    def _position_lock(self, key):
        with self._positions_lock:
            return self._position_locks.setdefault(key, Lock())

    def position(self, e, broker, *, force=False) -> float:
        if not self.applies_to(broker):
            return float(broker.signed_inventory_exact(
                account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type))
        key = self._position_key(e, broker)
        with self._position_lock(key):
            now = self._clock()
            previous = self._positions.get(key)
            if (not force and previous is not None
                and 0 <= now-previous[0] < IDLE_SAXO_POLL_SECONDS_V1):
                return previous[1]
            # A failed Saxo GET never falls back to a potentially stale value.
            amount = float(broker.signed_inventory_exact(
                account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type))
            if not isfinite(amount):
                raise ValueError('Saxo inventory is not finite')
            self._positions[key] = (self._clock(), amount)
            return amount

    def invalidate_position(self, e, broker):
        if not self.applies_to(broker):
            return
        key = self._position_key(e, broker)
        with self._position_lock(key):
            self._positions.pop(key, None)

    def verified_pre_submit(self, e, broker, *, account_key: str,
                            observed_amount: float) -> tuple[bool,float]:
        """Fresh Saxo GETs are mandatory for every real LIVE mutating POST.

        Never allow an order based on a 60s-old position or an old account
        mapping. A mismatch requires a brand-new strategy decision.
        """
        rows = self.accounts(broker,force=True)
        keys = [str(row.get('AccountKey') or '').strip()
                for row in rows if isinstance(row,dict)
                and str(row.get('AccountId') or '').strip()==str(e.account_id)]
        fresh = self.position(e,broker,force=True)
        okay=(len(keys)==1 and bool(keys[0]) and keys[0]==str(account_key)
              and abs(fresh-float(observed_amount))<=1e-8)
        return okay,fresh


IDLE_SAXO_CACHE_V1 = V3IdleSaxoCacheV1()
