from __future__ import annotations

import json

from saxo_provider import configured_client, discover_instruments, instrument_is_unexpired


DEFAULT_PRICE_MULTIPLIERS = {
    "Silver": 0.01,
}


def main() -> None:
    client = configured_client()
    if client is None:
        raise SystemExit("SAXO_ACCESS_TOKEN mangler")

    discovered = discover_instruments(client)
    selected: dict[str, dict[str, object]] = {}

    for asset, instruments in discovered.items():
        print(f"\n[{asset}]")
        valid = [item for item in instruments if instrument_is_unexpired(item)]
        for item in valid[:20]:
            print(
                f"{item.symbol:12} | {item.description:45} | "
                f"UIC={item.uic} | {item.asset_type} | expiry={item.expiry or '-'}"
            )
        if valid:
            first = valid[0]
            selected[asset] = {
                "uic": first.uic,
                "asset_type": first.asset_type,
                "symbol": first.symbol,
                "description": first.description,
                "expiry": first.expiry,
                "price_multiplier": DEFAULT_PRICE_MULTIPLIERS.get(asset, 1.0),
            }

    print("\nFørste gyldige kandidat per marked (kontroller før bruk):")
    print(json.dumps(selected, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
