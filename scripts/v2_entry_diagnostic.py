from __future__ import annotations

import os

from autotrader_entry_policy_v2 import load_pilot_margin_config_v2
from autotrader_open_sizing_v2 import preflight_minimum_entry_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_enrollment_v2 import load_strategy_enrollment_v2
from saxo_provider import LIVE_BASE_URL, SaxoInstrument, configured_client


PILOT_KEY = os.getenv("PRICEGAUGER_V2_DIAGNOSTIC_PILOT", "072df764-35e0-5058-bcba-afa83730d395")


def main() -> None:
    enrollment = load_strategy_enrollment_v2(PILOT_KEY)
    if enrollment is None:
        raise SystemExit(f"V2_DIAG pilot={PILOT_KEY} enrollment=missing")
    client = configured_client(base_url=LIVE_BASE_URL)
    accounts = client._get("port/v1/accounts/me").get("Data") or []
    account = next((row for row in accounts if str(row.get("AccountId") or "") == str(enrollment.account_id)), None)
    if account is None:
        raise SystemExit(f"V2_DIAG pilot={PILOT_KEY} account=missing")
    account_key = str(account.get("AccountKey") or "")
    currency = str(account.get("Currency") or "").upper()
    equity = load_pilot_equity_v2(pilot_key=PILOT_KEY)
    config = load_pilot_margin_config_v2(PILOT_KEY)
    instrument = SaxoInstrument(asset=enrollment.market_name, uic=enrollment.uic, asset_type=enrollment.asset_type)
    print(
        "V2_DIAG_CONFIG"
        f" pilot={PILOT_KEY} account={enrollment.account_id} currency={currency}"
        f" allocated={float(equity.allocated_capital):.6f} entry_budget={float(equity.entry_budget):.6f}"
        f" envelope_enabled={None if config is None else config.enabled}"
        f" envelope_max_leverage={None if config is None else float(config.max_effective_leverage):.6f}"
        f" envelope_free_buffer={None if config is None else float(config.minimum_free_capital):.6f}"
    )
    for direction in ("LONG", "SHORT"):
        rules, precheck = preflight_minimum_entry_v2(
            client,
            account_key=account_key,
            account_currency=currency,
            instrument=instrument,
            direction=direction,
            external_reference=f"pg-v2-diag-{direction.lower()}",
        )
        budget = float(equity.entry_budget)
        required_leverage = float("inf") if budget <= 0 else float(precheck.notional_account) / budget
        print(
            "V2_DIAG_MINIMUM"
            f" direction={direction} amount={float(precheck.amount):.6f}"
            f" notional={float(precheck.notional_account):.6f}"
            f" initial_margin={float(precheck.initial_margin_account):.6f}"
            f" free_after={float(precheck.available_margin_after_account):.6f}"
            f" precheck={precheck.precheck_result} disclaimers={precheck.disclaimers_present}"
            f" required_leverage={required_leverage:.6f}"
            f" amount_decimals={rules.amount_decimals} increment={float(rules.increment_size):.6f}"
        )


if __name__ == "__main__":
    main()
