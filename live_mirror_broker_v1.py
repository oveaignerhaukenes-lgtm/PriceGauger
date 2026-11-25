"""Independent quote-driven virtual broker primitives; no Saxo client or I/O.

Money is NOK, price is instrument points, quantity is signed broker lots.
Calibration terms are explicit scenario inputs, never inferred as verified
Saxo terms. No opposite-side flip in one fill (same FLAT boundary as LIVE).
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from autotrader_v3_domain import centilots_v3, lots_v3


@dataclass(frozen=True)
class MirrorTerms:
    nok_per_point_per_lot: float
    margin_fraction: float
    fee_nok_per_lot_per_side: float
    latency_seconds: float
    adverse_slippage_points: float
    minimum_lots: float
    capital_cap_nok: float
    max_quote_wait_seconds: float = 10.0

    def __post_init__(self):
        values = tuple(vars(self).values())
        if not all(isfinite(v) for v in values):
            raise ValueError("finite calibration terms required")
        if (self.nok_per_point_per_lot <= 0 or not 0 < self.margin_fraction <= 1
            or min(self.fee_nok_per_lot_per_side, self.latency_seconds,
                   self.adverse_slippage_points) < 0
            or min(self.minimum_lots, self.capital_cap_nok, self.max_quote_wait_seconds) <= 0
            or self.max_quote_wait_seconds < self.latency_seconds
            or abs(float(lots_v3(centilots_v3(self.minimum_lots)))-self.minimum_lots)>1e-9):
            raise ValueError("invalid calibration terms")


@dataclass(frozen=True)
class MirrorAccount:
    cash_nok: float
    inventory: float = 0.0
    entry_price: float = 0.0
    fees_nok: float = 0.0
    realized_nok: float = 0.0

    def __post_init__(self):
        if not all(isfinite(v) for v in vars(self).values()):
            raise ValueError("finite account values required")
        if abs(float(lots_v3(centilots_v3(self.inventory)))-self.inventory)>1e-9:
            raise ValueError("inventory precision")
        if self.inventory and self.entry_price <= 0:
            raise ValueError("entry basis required for nonflat account")

    def equity(self, bid, ask, terms):
        mark = bid if self.inventory > 0 else ask
        return self.cash_nok + self.inventory*(mark-self.entry_price)*terms.nok_per_point_per_lot


@dataclass(frozen=True)
class MirrorQuote:
    at: datetime
    received_at: datetime
    bid: float
    ask: float

    def __post_init__(self):
        if self.at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("timezone-aware quote required")
        if not (isfinite(self.bid) and isfinite(self.ask) and 0 < self.bid <= self.ask):
            raise ValueError("invalid BBO")


@dataclass(frozen=True)
class MirrorFill:
    status: str
    account: MirrorAccount
    price: float | None = None
    received_at: datetime | None = None
    delta: float = 0.0


def execute_target(account, target, *, decided_at, quotes, now, terms):
    """One virtual execution from independent target and observable BBO.

    No fills before the decision + latency, no future quotes, no retry of
    stale intents. Missing quote is explicit. Spread is paid via bid/ask,
    not a second synthetic spread deduction. Closing is not margin-gated.
    """
    if decided_at.tzinfo is None or now.tzinfo is None or now < decided_at:
        raise ValueError("invalid decision clock")
    current = centilots_v3(account.inventory)
    wanted = centilots_v3(target)
    if current == wanted:
        return MirrorFill("NO_CHANGE", account)
    if current*wanted < 0:
        wanted = 0
    delta_units = wanted-current
    delta = float(lots_v3(delta_units))
    minimum = centilots_v3(terms.minimum_lots)
    opening = abs(wanted) > abs(current)
    if opening and (abs(delta_units) < minimum or abs(delta_units)%minimum):
        return MirrorFill("LOT_REJECTED", account)
    eligible = decided_at + timedelta(seconds=terms.latency_seconds)
    deadline = decided_at + timedelta(seconds=terms.max_quote_wait_seconds)
    # received_at is the actual availability clock; source time must also
    # be after the decision. Never backdate a stale buffered quote.
    candidates = [q for q in quotes if eligible <= q.received_at <= min(now, deadline)
                  and decided_at <= q.at <= q.received_at
                  and (q.received_at-q.at).total_seconds() <= 5]
    if not candidates:
        return MirrorFill("QUOTE_EXPIRED" if now >= deadline else "WAIT_QUOTE", account)
    q = min(candidates, key=lambda v: (v.received_at, v.at))
    price = q.ask+terms.adverse_slippage_points if delta > 0 else q.bid-terms.adverse_slippage_points
    if price <= 0:
        return MirrorFill("INVALID_PRICE", account)
    new_inventory = float(lots_v3(wanted))
    fee = abs(delta)*terms.fee_nok_per_lot_per_side
    multiplier = terms.nok_per_point_per_lot
    if opening:
        basis = (abs(account.inventory)*account.entry_price+abs(delta)*price)/abs(new_inventory)
        updated = replace(account, cash_nok=account.cash_nok-fee, inventory=new_inventory,
                          entry_price=basis, fees_nok=account.fees_nok+fee)
        required = abs(new_inventory)*price*multiplier*terms.margin_fraction
        if required > min(terms.capital_cap_nok, updated.equity(q.bid,q.ask,terms)):
            return MirrorFill("MARGIN_REJECTED", account)
    else:
        closed = min(abs(delta),abs(account.inventory))
        gross = closed*(price-account.entry_price)*(1 if current>0 else -1)*multiplier
        updated = replace(account, cash_nok=account.cash_nok+gross-fee,
                          inventory=new_inventory, entry_price=account.entry_price if wanted else 0.0,
                          fees_nok=account.fees_nok+fee, realized_nok=account.realized_nok+gross)
    return MirrorFill("FILLED", updated, price, q.received_at, delta)
