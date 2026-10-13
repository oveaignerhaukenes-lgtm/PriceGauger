"""Explicit, one-shot user-authorized Whipsaw LIVE opt-in for Tech100-B.

This operator action runs on the existing V3 worker thread when a matching
Railway environment variable is set. Only the exact existing B instance may
be changed. Nothing here submits, cancels, or closes broker orders.
Once recorded, it NEVER re-applies even if an operator removes the option.
"""
from __future__ import annotations

from dataclasses import replace
import logging
import os

from database import connect
from autotrader_v3_config_v1 import load_autotrader_config_v3, save_autotrader_config_v3
from autotrader_v3_instance_registry_v1 import load_v3_instances_v1
from autotrader_v3_registry_v1 import live_config_issues_v3
from autotrader_v3_order_guard_v1 import pending_order_v3
from autotrader_v3_whipsaw_live_v1 import (
    is_whipsaw_live_approved_v3, set_whipsaw_live_approval_v3,
)

LOGGER=logging.getLogger("pricegauger.autotrader.v3.ops")
TRADER_B="f75cdc83-168b-5eb4-9224-ce73a058b6d3"
OPT_IN_ENV="PG_V3_WHIPSAW_OPTIN_B_ONCE_20261013"
ACTION_KEY="2026-10-13-whipsaw-live-tech100-b-user-opt-in-v1"


def apply_authorized_whipsaw_b_once(*,db_path="pricegauger.db",token=None):
    """Returns SKIP / DEFER_PENDING / ALREADY_APPLIED / ACTIVATED.

    Call only in the EXISTING serial worker, before any V3 broker cycle.
    All unrelated strategy controls, budgets and accounts are unchanged.
    """
    auth=token if token is not None else os.environ.get(OPT_IN_ENV,"")
    if auth != TRADER_B:
        return "SKIP"
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_ops_approvals(
            action_key TEXT PRIMARY KEY,
            trader_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        marker=db.execute("SELECT 1 FROM autotrader_v3_ops_approvals WHERE action_key=?",
                          (ACTION_KEY,)).fetchone()
        if marker:
            return "ALREADY_APPLIED"
    instances=[i for i in load_v3_instances_v1(db_path=db_path)
               if i.instance_id==TRADER_B]
    if len(instances)!=1:
        raise RuntimeError("Tech100-B authorized instance not found")
    instance=instances[0]
    if "tech" not in instance.market_name.lower() and "nas" not in instance.market_name.lower():
        raise RuntimeError("Tech100-B unexpected market; refusing whipsaw opt-in")
    # Never alter an instance with a submitted/unknown broker order.
    pending=pending_order_v3(account_id=instance.account_id,uic=instance.uic,
                             asset_type=instance.asset_type,db_path=db_path)
    if pending:
        return "DEFER_PENDING"
    cfg=load_autotrader_config_v3(TRADER_B,db_path=db_path)
    desired=cfg if "whipsaw" in cfg.modifiers else replace(
        cfg,modifiers=tuple(cfg.modifiers)+("whipsaw",))
    errors=live_config_issues_v3(
        strategy_key=desired.strategy_key,timeframe=desired.timeframe,
        control_mode=desired.control_mode,modifiers=desired.modifiers,
        regime_timeframe=desired.regime_timeframe,
    )
    if errors:
        raise RuntimeError("Tech100-B unsupported LIVE configuration: "+"; ".join(errors))
    if desired!=cfg:
        save_autotrader_config_v3(desired,db_path=db_path)
    if not is_whipsaw_live_approved_v3(TRADER_B,db_path=db_path):
        set_whipsaw_live_approval_v3(TRADER_B,True,db_path=db_path)
    if "whipsaw" not in load_autotrader_config_v3(TRADER_B,db_path=db_path).modifiers:
        raise RuntimeError("Tech100-B whipsaw option did not persist")
    if not is_whipsaw_live_approved_v3(TRADER_B,db_path=db_path):
        raise RuntimeError("Tech100-B whipsaw approval did not persist")
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_ops_approvals(action_key,trader_id)
                      VALUES(?,?) ON CONFLICT(action_key) DO NOTHING""",
                   (ACTION_KEY,TRADER_B))
    LOGGER.warning("USER_AUTHORIZED Tech100-B ONLY: LIVE Whipsaw Detector enabled; "
                   "other strategies/accounts/policies/authority unchanged; no orders sent")
    return "ACTIVATED"
