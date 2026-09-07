from __future__ import annotations

from contextlib import AbstractContextManager

import autotrader_strategy_activation_schema_v1 as schema


class _Db:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, parameters=()):
        del parameters
        self.statements.append(" ".join(str(sql).split()))
        return self


class _Ctx(AbstractContextManager):
    def __init__(self, db: _Db) -> None:
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_activation_cohort_schema_retires_only_historical_strategy_uniqueness(monkeypatch) -> None:
    db = _Db()
    monkeypatch.setattr(schema, "using_postgres", lambda: True)
    monkeypatch.setattr(schema, "connect", lambda: _Ctx(db))
    monkeypatch.setattr(schema, "_SCHEMA_READY", False)

    schema.ensure_strategy_activation_cohort_schema_v1()

    joined = "\n".join(db.statements)
    assert "DROP CONSTRAINT IF EXISTS pg_v2_autotrader_strategy_enr_account_id_uic_asset_type_str_key" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS pg_v2_autotrader_one_live_strategy_per_product_idx" in joined
    assert "WHERE enabled = TRUE AND execution_mode = 'LIVE_MANAGE'" in joined
    assert schema._SCHEMA_READY is True


def test_strategy_switch_provenance_prepares_activation_schema() -> None:
    source = open("autotrader_strategy_switch_provenance_v2.py", encoding="utf-8").read()
    assert "ensure_strategy_activation_cohort_schema_v1" in source
    assert "ensure_autotrader_schema_v2()\n        ensure_strategy_activation_cohort_schema_v1()" in source
