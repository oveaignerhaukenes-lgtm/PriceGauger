"""Explicit operator-only Saxo READ-ONLY evidence probe for Avoid Loss V1.

Example from an authenticated, trusted runtime (do not paste account IDs to chat):
  python saxo_avoid_loss_readonly_probe_v1.py --account-id "$SAXO_ACCOUNT_ID" \
      --uic 4912 --asset-type CfdOnIndex

Only GET /accounts/me, /netpositions and /positions. Never precheck/place orders.
Output is restricted to status codes and field-availability checks.
"""
from __future__ import annotations

import argparse
import json

from autotrader_v3_avoid_loss_readiness_v1 import inspect_saxo_avoid_loss_readonly_v1


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Saxo Avoid Loss V1 GET-only evidence")
    parser.add_argument("--account-id", required=True,
                        help="Exact Saxo AccountId; not included in output")
    parser.add_argument("--uic", type=int, required=True)
    parser.add_argument("--asset-type", required=True)
    args=parser.parse_args(argv)

    from autotrader_v3_live_saxo_v1 import configured_live_pilot_client_v3
    broker=configured_live_pilot_client_v3()
    report=inspect_saxo_avoid_loss_readonly_v1(
        broker=broker, account_id=args.account_id,
        uic=args.uic, asset_type=args.asset_type)
    print(json.dumps(report.public_dict(), sort_keys=True))
    return 0 if report.status in {"FLAT_OBSERVED", "POSITION_FIELDS_OBSERVED"} else 2


if __name__=="__main__":
    raise SystemExit(main())
