from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autotrader_margin_envelope_v2 import AutoTraderMarginEnvelopeV2
from autotrader_product_universe_v2 import (
    AutoTraderProductUniverseEntryV2,
    require_product_eligible_v2,
)
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from database import connect
from saxo_provider import SaxoInstrument
from trading_desk_products import LeveragedProduct


DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"
MARGIN_ASSET_TYPES = {
    "CfdOnIndex",
    "CfdOnStock",
    "CfdOnFutures",
    "CfdOnEtf",
    "CfdOnEtn",
    "CfdOnEtc",
    "FxSpot",
    "FxForwards",
}


@dataclass(frozen=True, slots=True)
class ProductAdmissionV2:
    account_id: str
    uic: int
    asset_type: str
    market_id: int
    instrument_id: int
    market_name: str
    direction: str
    enabled: bool
    transaction_costs_verified: bool
    margin_product_allowed: bool
    negative_balance_protection_verified: bool
    limited_loss_verified: bool
    no_margin_obligation_verified: bool
    preflight_amount: float | None
    preflight_cost_account: float | None
    preflight_initial_margin_account: float | None

    @property
    def universe_entry(self) -> AutoTraderProductUniverseEntryV2:
        return AutoTraderProductUniverseEntryV2(
            uic=self.uic,
            asset_type=self.asset_type,
            market=self.market_name,
            direction="Long" if self.direction == DIRECTION_LONG else "Short",
            enabled=self.enabled,
            limited_loss_verified=self.limited_loss_verified,
            no_margin_obligation_verified=self.no_margin_obligation_verified,
            transaction_costs_verified=self.transaction_costs_verified,
            margin_product_allowed=self.margin_product_allowed,
            negative_balance_protection_verified=self.negative_balance_protection_verified,
            notes="DB-backed explicit AutoManage admission",
        )


@dataclass(frozen=True, slots=True)
class PilotMarginConfigV2:
    pilot_key: str
    enabled: bool
    max_effective_leverage: float
    minimum_free_capital: float

    def __post_init__(self) -> None:
        if float(self.max_effective_leverage) <= 0:
            raise ValueError("max_effective_leverage must be positive")
        if float(self.minimum_free_capital) < 0:
            raise ValueError("minimum_free_capital cannot be negative")

    def envelope(self, *, currency: str, controlled_capital: float) -> AutoTraderMarginEnvelopeV2:
        capital = float(controlled_capital)
        if capital <= 0:
            raise ValueError("controlled_capital must be positive")
        if float(self.minimum_free_capital) >= capital:
            raise ValueError("minimum_free_capital must be smaller than current pilot capital")
        return AutoTraderMarginEnvelopeV2(
            currency=currency,
            capital_control_limit=capital,
            max_initial_margin=capital,
            max_notional_exposure=capital * float(self.max_effective_leverage),
            max_effective_leverage=float(self.max_effective_leverage),
            minimum_free_capital=float(self.minimum_free_capital),
            enabled=bool(self.enabled),
        )


def _normalize_direction(direction: str) -> str:
    value = str(direction).strip().upper()
    if value not in {DIRECTION_LONG, DIRECTION_SHORT}:
        raise ValueError("entry direction must be LONG or SHORT")
    return value


def is_margin_product_v2(asset_type: str) -> bool:
    return str(asset_type).strip() in MARGIN_ASSET_TYPES


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def save_product_admission_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    direction: str,
    transaction_costs_verified: bool,
    margin_product_allowed: bool,
    negative_balance_protection_verified: bool = False,
    limited_loss_verified: bool = False,
    no_margin_obligation_verified: bool = False,
    preflight_amount: float | None = None,
    preflight_cost_account: float | None = None,
    preflight_initial_margin_account: float | None = None,
    enabled: bool = True,
) -> ProductAdmissionV2:
    """Persist explicit account/product/direction admission after runtime preflight.

    No flag is inferred from an asset-type label. In particular, negative balance
    protection remains an explicit user-verified fact for margin products.
    """
    ensure_autotrader_schema_v2()
    normalized = _normalize_direction(direction)
    margin_expected = is_margin_product_v2(enrollment.asset_type)
    if bool(margin_product_allowed) != margin_expected:
        raise ValueError("margin_product_allowed must match the supported asset-class policy")
    if not transaction_costs_verified:
        raise ValueError("product admission requires a successful runtime cost preflight")
    if margin_expected and not negative_balance_protection_verified:
        raise ValueError("margin-product admission requires explicit negative-balance-protection verification")
    if not margin_expected and not (limited_loss_verified and no_margin_obligation_verified):
        raise ValueError("non-margin leveraged admission requires limited-loss and no-margin-obligation verification")

    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_product_admissions(
                account_id, uic, asset_type, market_id, instrument_id, market_name,
                direction, enabled, transaction_costs_verified,
                margin_product_allowed, negative_balance_protection_verified,
                limited_loss_verified, no_margin_obligation_verified,
                preflight_amount, preflight_cost_account,
                preflight_initial_margin_account, verified_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), now())
            ON CONFLICT (account_id, uic, asset_type, direction) DO UPDATE SET
                market_id=EXCLUDED.market_id,
                instrument_id=EXCLUDED.instrument_id,
                market_name=EXCLUDED.market_name,
                enabled=EXCLUDED.enabled,
                transaction_costs_verified=EXCLUDED.transaction_costs_verified,
                margin_product_allowed=EXCLUDED.margin_product_allowed,
                negative_balance_protection_verified=EXCLUDED.negative_balance_protection_verified,
                limited_loss_verified=EXCLUDED.limited_loss_verified,
                no_margin_obligation_verified=EXCLUDED.no_margin_obligation_verified,
                preflight_amount=EXCLUDED.preflight_amount,
                preflight_cost_account=EXCLUDED.preflight_cost_account,
                preflight_initial_margin_account=EXCLUDED.preflight_initial_margin_account,
                verified_at=now(),
                updated_at=now()
            """,
            (
                enrollment.account_id,
                enrollment.uic,
                enrollment.asset_type,
                enrollment.market_id,
                enrollment.instrument_id,
                enrollment.market_name,
                normalized,
                bool(enabled),
                bool(transaction_costs_verified),
                bool(margin_product_allowed),
                bool(negative_balance_protection_verified),
                bool(limited_loss_verified),
                bool(no_margin_obligation_verified),
                None if preflight_amount is None else float(preflight_amount),
                None if preflight_cost_account is None else float(preflight_cost_account),
                None if preflight_initial_margin_account is None else float(preflight_initial_margin_account),
            ),
        )
    admission = load_product_admission_v2(
        account_id=enrollment.account_id,
        uic=enrollment.uic,
        asset_type=enrollment.asset_type,
        direction=normalized,
    )
    if admission is None:
        raise RuntimeError("product admission was not persisted")
    return admission


def load_product_admission_v2(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    direction: str,
) -> ProductAdmissionV2 | None:
    ensure_autotrader_schema_v2()
    normalized = _normalize_direction(direction)
    with connect() as db:
        row = db.execute(
            """
            SELECT account_id, uic, asset_type, market_id, instrument_id,
                   market_name, direction, enabled, transaction_costs_verified,
                   margin_product_allowed, negative_balance_protection_verified,
                   limited_loss_verified, no_margin_obligation_verified,
                   preflight_amount, preflight_cost_account,
                   preflight_initial_margin_account
            FROM pg_v2_autotrader_product_admissions
            WHERE account_id = ? AND uic = ? AND asset_type = ? AND direction = ?
            """,
            (str(account_id), int(uic), str(asset_type), normalized),
        ).fetchone()
    item = _row_dict(row)
    if item is None:
        return None
    return ProductAdmissionV2(
        account_id=str(item["account_id"]),
        uic=int(item["uic"]),
        asset_type=str(item["asset_type"]),
        market_id=int(item["market_id"]),
        instrument_id=int(item["instrument_id"]),
        market_name=str(item["market_name"]),
        direction=str(item["direction"]),
        enabled=bool(item["enabled"]),
        transaction_costs_verified=bool(item["transaction_costs_verified"]),
        margin_product_allowed=bool(item["margin_product_allowed"]),
        negative_balance_protection_verified=bool(item["negative_balance_protection_verified"]),
        limited_loss_verified=bool(item["limited_loss_verified"]),
        no_margin_obligation_verified=bool(item["no_margin_obligation_verified"]),
        preflight_amount=None if item["preflight_amount"] is None else float(item["preflight_amount"]),
        preflight_cost_account=None if item["preflight_cost_account"] is None else float(item["preflight_cost_account"]),
        preflight_initial_margin_account=None if item["preflight_initial_margin_account"] is None else float(item["preflight_initial_margin_account"]),
    )


def save_pilot_margin_config_v2(
    *,
    pilot_key: str,
    max_effective_leverage: float,
    minimum_free_capital: float = 0.0,
    enabled: bool = True,
) -> PilotMarginConfigV2:
    ensure_autotrader_schema_v2()
    config = PilotMarginConfigV2(
        pilot_key=str(pilot_key),
        enabled=bool(enabled),
        max_effective_leverage=float(max_effective_leverage),
        minimum_free_capital=float(minimum_free_capital),
    )
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_margin_configs(
                pilot_key, enabled, max_effective_leverage,
                minimum_free_capital, updated_at
            ) VALUES (?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                enabled=EXCLUDED.enabled,
                max_effective_leverage=EXCLUDED.max_effective_leverage,
                minimum_free_capital=EXCLUDED.minimum_free_capital,
                updated_at=now()
            """,
            (
                config.pilot_key,
                config.enabled,
                config.max_effective_leverage,
                config.minimum_free_capital,
            ),
        )
    return config


def load_pilot_margin_config_v2(pilot_key: str) -> PilotMarginConfigV2 | None:
    ensure_autotrader_schema_v2()
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, enabled, max_effective_leverage, minimum_free_capital
            FROM pg_v2_autotrader_margin_configs
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    item = _row_dict(row)
    if item is None:
        return None
    return PilotMarginConfigV2(
        pilot_key=str(item["pilot_key"]),
        enabled=bool(item["enabled"]),
        max_effective_leverage=float(item["max_effective_leverage"]),
        minimum_free_capital=float(item["minimum_free_capital"]),
    )


def require_entry_policy_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    direction: str,
    currency: str,
    controlled_capital: float,
) -> tuple[ProductAdmissionV2, PilotMarginConfigV2, AutoTraderMarginEnvelopeV2]:
    normalized = _normalize_direction(direction)
    admission = load_product_admission_v2(
        account_id=enrollment.account_id,
        uic=enrollment.uic,
        asset_type=enrollment.asset_type,
        direction=normalized,
    )
    if admission is None:
        raise ValueError("NOT_IN_PG_PRODUCT_UNIVERSE")
    if (
        admission.market_id != enrollment.market_id
        or admission.instrument_id != enrollment.instrument_id
        or admission.market_name != enrollment.market_name
    ):
        raise ValueError("PRODUCT_ADMISSION_CANONICAL_IDENTITY_MISMATCH")

    margin_config = load_pilot_margin_config_v2(enrollment.pilot_key)
    if margin_config is None or not margin_config.enabled:
        raise ValueError("MARGIN_ENVELOPE_NOT_ACTIVE")
    envelope = margin_config.envelope(currency=currency, controlled_capital=controlled_capital)

    product = LeveragedProduct(
        instrument=SaxoInstrument(
            asset=enrollment.market_name,
            uic=enrollment.uic,
            asset_type=enrollment.asset_type,
        ),
        direction="Long" if normalized == DIRECTION_LONG else "Short",
    )
    require_product_eligible_v2(
        market=enrollment.market_name,
        product=product,
        universe=(admission.universe_entry,),
        margin_envelope_active=True,
    )
    return admission, margin_config, envelope


__all__ = [
    "DIRECTION_LONG",
    "DIRECTION_SHORT",
    "MARGIN_ASSET_TYPES",
    "PilotMarginConfigV2",
    "ProductAdmissionV2",
    "is_margin_product_v2",
    "load_pilot_margin_config_v2",
    "load_product_admission_v2",
    "require_entry_policy_v2",
    "save_pilot_margin_config_v2",
    "save_product_admission_v2",
]
