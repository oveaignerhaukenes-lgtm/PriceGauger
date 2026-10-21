"""Minimal PostgreSQL relation-size inventory for PriceGauger cost diagnostics.

Read-only pg_catalog statistics, no table payloads, account IDs or mutations.
"""
from __future__ import annotations

from database import connect, using_postgres


def largest_relations_v1(*,db_path="pricegauger.db",limit=12):
    if not using_postgres():
        return ()
    size=max(1,min(20,int(limit)))
    with connect(db_path) as db:
        rows=db.execute("""
            SELECT relname AS name, pg_total_relation_size(relid) AS bytes,
                   pg_indexes_size(relid) AS index_bytes,
                   n_live_tup AS estimated_live_rows,
                   n_dead_tup AS estimated_dead_rows
            FROM pg_stat_user_tables WHERE schemaname='public'
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT ?
        """,(size,)).fetchall()
    return tuple({
        "name":str(x["name"]),
        "bytes":int(x["bytes"]),
        "index_bytes":int(x["index_bytes"]),
        "live_estimate":int(x["estimated_live_rows"]),
        "dead_estimate":int(x["estimated_dead_rows"]),
    } for x in rows)
