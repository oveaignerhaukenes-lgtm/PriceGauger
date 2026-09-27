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

GOLD_FACTOR_DEFAULTS=(
 ("fed_real_rates","Fed / realrenter",True,"Makro","Front-end, realrenter og policyforventninger."),
 ("usd","USD / DXY",True,"Makro","Dollarstyrke og finansielle flows."),
 ("inflation","Inflasjon / breakevens",True,"Makro","Inflasjon og forventet realavkastning."),
 ("oil_inflation","Olje / energipress",True,"Kryssmarked","Olje som input til energidrevet inflasjonspress."),
 ("gold_relative","Relativ gullstyrke",True,"Metaller","Gull som holder seg sterkt/svakt relativt til makrodriverne."),
 ("credit_spreads","Kredittspreader / stress",True,"Likviditet","IG/HY OAS og kredittstress som tidlig regimesignal."),
 ("equity_buybacks","Aksje-buybacks",True,"Likviditet","Størrelse og timing på buybacks som mulig kanal for likviditetsrotasjon."),
 ("equity_flows","Aksjeflows / margin debt",True,"Likviditet","ETF-flows, posisjonering og margin debt som mål på kapitalrotasjon."),
 ("market_liquidity","Systemlikviditet",True,"Likviditet","Sentralbankbalanser, reserve-/repo-forhold og annen systemlikviditet."),
 ("volatility_skew","VIX / opsjonsskew",True,"Marked","Volatilitet og skew som mål på risk-on/risk-off og haleetterspørsel."),
 ("funding_repo","Funding / repo-stress",True,"Likviditet","Funding- og repo-stress som signal om finansiell friksjon."),
 ("metal_flows","GLD/SLV / CFTC-flows",True,"Metaller","ETF-flows og futuresposisjonering som bekreftelse på metallrotasjon."),
)

SILVER_FACTOR_DEFAULTS=(
 ("fed_real_rates","Fed / realrenter",True,"Makro","Front-end, realrenter og policyforventninger."),
 ("usd","USD / DXY",True,"Makro","Dollarstyrke påvirker metallprising og finansielle flows."),
 ("gold_relative","Gull / relativ metallstyrke",True,"Metaller","Skiller felles edelmetallregime fra sølvspesifikk bevegelse."),
 ("industrial_demand","Industriell etterspørsel",True,"Fundamentalt","Etterspørsel fra industri og elektrifisering/sol m.m."),
 ("mine_supply","Gruveproduksjon / tilbud",True,"Fundamentalt","Tilbud, prosjektpipeline og produksjonsforventninger."),
 ("byproduct_supply","Biprodukt-eksponering",True,"Fundamentalt","Sølvtilbud påvirkes av økonomien i andre metallgruver, ikke sølvpris alene."),
 ("inventories_flows","Lagre / fysiske flows",True,"Fundamentalt","Lagerutvikling og fysisk stramhet når datagrunnlaget finnes."),
 ("oil_inflation","Olje / energipress",True,"Kryssmarked","Olje som input til inflasjon, kostnader og realrenteforventninger."),
 ("growth_copper","Vekst / kobber-proxy",False,"Kryssmarked","Mulig proxy for industriell konjunktur; av som standard for å unngå dobbeltelling."),
 ("gold_silver_ratio","Gull/sølv-ratio",True,"Kryssmarked","Relativ prising mellom gull og sølv."),
)

OIL_FACTOR_DEFAULTS=(
 ("demand_growth","Global etterspørsel / vekst",True,"Etterspørsel","Aktivitet, transport og forventet forbruksvekst."),
 ("commercial_inventories","Kommersielle lagre",True,"Balanse","Lagerbygg/-trekk som signal om fysisk balanse."),
 ("strategic_reserves","Strategiske lagre",True,"Balanse","Trekk, refill/resupply og forventet offentlig lageretterspørsel."),
 ("supply_growth","Produksjon / tilbudsvekst",True,"Tilbud","Produksjonsrespons og forventet ny kapasitet."),
 ("opec_policy","OPEC+ / tilbudspolitikk",True,"Tilbud","Kommuniserte og realiserte produksjonsendringer."),
 ("curve_spreads","Terminkurve / spreads",True,"Marked","Backwardation/contango og nærliggende spreads som balansesignal."),
 ("geopolitical_risk","Geopolitisk risikopremie",True,"Marked","Forsyningsrisiko og transportforstyrrelser."),
 ("usd","USD / DXY",False,"Makro","Finansiell motvind/medvind; av som standard for å begrense dobbeltelling."),
)

FACTOR_DEFAULTS_BY_STRATEGY={
 "gold-fed-rates": GOLD_FACTOR_DEFAULTS,
 "silver-fed-industry-supply": SILVER_FACTOR_DEFAULTS,
 "oil-balance-resupply": OIL_FACTOR_DEFAULTS,
}

def ensure_strategy_factor_schema_v1()->None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_strategy_factors(
          strategy_key TEXT NOT NULL,factor_key TEXT NOT NULL,label TEXT NOT NULL,
          enabled BOOLEAN NOT NULL,category TEXT NOT NULL,rationale TEXT NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(strategy_key,factor_key))""")

def seed_strategy_factors_v1(strategy_key:str)->None:
    ensure_strategy_factor_schema_v1()
    with connect() as db:
        defaults=FACTOR_DEFAULTS_BY_STRATEGY.get(strategy_key, ())
        for key,label,enabled,category,rationale in defaults:
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
