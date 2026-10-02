from __future__ import annotations

from dataclasses import dataclass

from database import connect

ENGINE_V2 = "V2"
ENGINE_V3 = "V3"
_VALID_ENGINES = {ENGINE_V2, ENGINE_V3}


@dataclass(frozen=True, slots=True)
class EngineAccountOwnershipV1:
    account_id: str
    engine_id: str
    owner_key: str


def ensure_engine_account_ownership_schema_v1(*, db_path: str = "pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS autotrader_engine_account_ownership (
                account_id TEXT PRIMARY KEY,
                engine_id TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (engine_id IN ('V2','V3'))
            )
        """)


def load_account_owner_v1(account_id: str, *, db_path: str = "pricegauger.db") -> EngineAccountOwnershipV1 | None:
    ensure_engine_account_ownership_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        row = db.execute(
            "SELECT account_id,engine_id,owner_key FROM autotrader_engine_account_ownership WHERE account_id=?",
            (str(account_id),),
        ).fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return EngineAccountOwnershipV1(str(row["account_id"]), str(row["engine_id"]), str(row["owner_key"]))
    return EngineAccountOwnershipV1(str(row[0]), str(row[1]), str(row[2]))


def claim_account_v1(account_id: str, engine_id: str, owner_key: str, *, db_path: str = "pricegauger.db") -> EngineAccountOwnershipV1:
    engine = str(engine_id).strip().upper()
    if engine not in _VALID_ENGINES:
        raise ValueError(f"unsupported engine_id: {engine_id}")
    account = str(account_id).strip()
    owner = str(owner_key).strip()
    if not account or not owner:
        raise ValueError("account_id and owner_key are required")
    ensure_engine_account_ownership_schema_v1(db_path=db_path)
    with connect(db_path) as db:
        current = db.execute(
            "SELECT engine_id,owner_key FROM autotrader_engine_account_ownership WHERE account_id=?",
            (account,),
        ).fetchone()
        if current is not None:
            current_engine = str(current["engine_id"] if isinstance(current, dict) else current[0])
            current_owner = str(current["owner_key"] if isinstance(current, dict) else current[1])
            if current_engine != engine:
                raise RuntimeError(
                    f"Saxo account {account} is owned by ENGINE {current_engine}; ENGINE {engine} cannot acquire dual authority"
                )
            if current_owner != owner:
                raise RuntimeError(
                    f"Saxo account {account} already has ENGINE {engine} owner {current_owner}; explicit release is required"
                )
            return EngineAccountOwnershipV1(account, engine, owner)
        db.execute(
            "INSERT INTO autotrader_engine_account_ownership(account_id,engine_id,owner_key,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
            (account, engine, owner),
        )
    return EngineAccountOwnershipV1(account, engine, owner)


def release_account_v1(account_id: str, engine_id: str, owner_key: str, *, db_path: str = "pricegauger.db") -> bool:
    engine = str(engine_id).strip().upper()
    with connect(db_path) as db:
        row = db.execute(
            "SELECT engine_id,owner_key FROM autotrader_engine_account_ownership WHERE account_id=?",
            (str(account_id),),
        ).fetchone()
        if row is None:
            return False
        current_engine = str(row["engine_id"] if isinstance(row, dict) else row[0])
        current_owner = str(row["owner_key"] if isinstance(row, dict) else row[1])
        if current_engine != engine or current_owner != str(owner_key):
            raise RuntimeError("only the current engine/account owner may release authority")
        db.execute("DELETE FROM autotrader_engine_account_ownership WHERE account_id=?", (str(account_id),))
    return True
