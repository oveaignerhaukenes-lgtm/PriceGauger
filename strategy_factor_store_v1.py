from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from database import connect

@dataclass(frozen=True, slots=True)
class StrategyFactorV1:
    strategy_key: str
    factor_key: str
    label: str
    enabled: bool
    category: str
    rationale: str
    updated_at: datetime

SILVER_FACTOR_DEFAULTS=(
 ("fed_real_rates","Fed / realrenter",True,"Macro","Front-end, realrenter og policyforventninger."),
 ("usd","USD / DXY",True,"Macro","Dollarstyrke påvirker metallprising og finansielle flows."),
 ("gold_relative","Gull / relativ metallstyrke",True,"Metaller","Skiller felles edelmetallregime fra sølvspesifikk bevegelse."),
 ("industrial_demand","Industriell etterspørsel",True,"Fundamentalt","Etterspørsel fra industri og elektrifisering/sol m.m."),
 ("mine_supply","Gruveproduksjon / tilbud",True,"Fundamentalt","Tilbud, prosjektpipeline og produksjonsforventninger."),
 ("byproduct_supply","Biprodukt-eksponering",True,"Fundamentalt","Mye sølvtilbud bestemmes av økonomien i andre metallgruver, ikke sølvpris alene."),
 ("inventories_flows","Lagre / fysiske flows",True,"Fundamentalt","Lagerutvikling og fysisk stramhet når datagrunnlaget finnes."),
 ("growth_copper","Vekst / kobber-proxy",False,"Kryssmarked","Mulig proxy for industriell konjunktur; av som standard for å unngå dobbeltelling."),
 ("gold_silver_ratio","Gull/sølv-ratio",True,"Kryssmarked","Relativ prising mellom gull og sølv."),
)

def ensure_strategy_factor_schema_v1()->None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_strategy_factors(
          strategy_key TEXT NOT NULL,factor_key TEXT NOT NULL,label TEXT NOT NULL,
          enabled BOOLEAN NOT NULL,category TEXT NOT NULL,rationale TEXT NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(strategy_key,factor_key))""")

def seed_strategy_factors_v1(strategy_key:str)->None:
    ensure_strategy_factor_schema_v1()
    with connect() as db:
        for key,label,enabled,category,rationale in SILVER_FACTOR_DEFAULTS:
            db.execute("""INSERT INTO pg_v2_strategy_factors
              (strategy_key,factor_key,label,enabled,category,rationale,updated_at)
              VALUES (?,?,?,?,?,?,?) ON CONFLICT(strategy_key,factor_key) DO NOTHING""",
              (strategy_key,key,label,enabled,category,rationale,datetime.now(timezone.utc)))

def load_strategy_factors_v1(strategy_key:str)->tuple[StrategyFactorV1,...]:
    seed_strategy_factors_v1(strategy_key)
    with connect() as db:
        rows=db.execute("""SELECT * FROM pg_v2_strategy_factors WHERE strategy_key=?
                           ORDER BY category,label""",(strategy_key,)).fetchall()
    return tuple(StrategyFactorV1(**dict(r)) for r in rows)

def set_strategy_factor_enabled_v1(strategy_key:str,factor_key:str,enabled:bool)->None:
    seed_strategy_factors_v1(strategy_key)
    with connect() as db:
        db.execute("""UPDATE pg_v2_strategy_factors SET enabled=?,updated_at=?
                      WHERE strategy_key=? AND factor_key=?""",
                   (bool(enabled),datetime.now(timezone.utc),strategy_key,factor_key))
