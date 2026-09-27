from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from database import connect

STRATEGY_KEY_GOLD_FED = "gold-fed-rates"
STRATEGY_KEY_SILVER_MACRO = "silver-fed-industry-supply"
STRATEGY_KEY_OIL_BALANCE = "oil-balance-resupply"

@dataclass(frozen=True, slots=True)
class ResearchEventV1:
    id: str
    strategy_key: str
    version: int
    event_type: str
    verdict: str
    title: str
    body: str
    observed_at: datetime

def ensure_research_strategy_schema_v1() -> None:
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_research_strategy_events (
                id TEXT PRIMARY KEY,
                strategy_key TEXT NOT NULL, version INTEGER NOT NULL,
                event_type TEXT NOT NULL, verdict TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""CREATE INDEX IF NOT EXISTS pg_v2_research_strategy_events_key_time_idx
                      ON pg_v2_research_strategy_events(strategy_key, observed_at DESC)""")

def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def append_research_event_v1(*, strategy_key: str, version: int, event_type: str,
                             verdict: str, title: str, body: str,
                             observed_at: datetime | str | None = None) -> None:
    ensure_research_strategy_schema_v1()
    with connect() as db:
        db.execute("""INSERT INTO pg_v2_research_strategy_events(
                        id, strategy_key, version, event_type, verdict, title, body, observed_at
                      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (str(uuid4()), str(strategy_key), int(version), str(event_type), str(verdict),
                    str(title).strip(), str(body).strip(), _utc(observed_at)))

def load_research_events_v1(strategy_key: str) -> tuple[ResearchEventV1, ...]:
    ensure_research_strategy_schema_v1()
    with connect() as db:
        rows = db.execute("""SELECT id, strategy_key, version, event_type, verdict, title, body, observed_at
                             FROM pg_v2_research_strategy_events
                             WHERE strategy_key = ? ORDER BY observed_at ASC, id ASC""",
                          (str(strategy_key),)).fetchall()
    return tuple(ResearchEventV1(
        id=str(row["id"]), strategy_key=str(row["strategy_key"]), version=int(row["version"]),
        event_type=str(row["event_type"]), verdict=str(row["verdict"]), title=str(row["title"]),
        body=str(row["body"]), observed_at=_utc(row["observed_at"]),
    ) for row in rows)

def seed_gold_fed_hypothesis_v1() -> None:
    if load_research_events_v1(STRATEGY_KEY_GOLD_FED):
        return
    append_research_event_v1(
        strategy_key=STRATEGY_KEY_GOLD_FED, version=1, event_type="hypothesis",
        verdict="baseline", title="Starthypotese v1",
        body=("Fed-innstramming gir først motvind til gull og sølv gjennom høyere "
              "front-end/realrenter og sterkere dollar. Hypotesen forventer deretter et "
              "mulig regimeskifte dersom høye renter svekker aktivitet og kreditt før "
              "inflasjonen er varig slått ned: 2Y/DXY kan da miste styrke mens lange "
              "renter forblir høye, og metallene kan gå fra motvind til medvind. "
              "Hypotesen falsifiseres dersom inflasjonen faller varig samtidig som "
              "økonomien tåler innstrammingen og realrentene forblir høye."),
        observed_at="2026-09-27T16:00:00+00:00",
    )


def _seed_hypothesis_once_v1(*, strategy_key: str, title: str, body: str, observed_at: str) -> None:
    if load_research_events_v1(strategy_key):
        return
    append_research_event_v1(
        strategy_key=strategy_key, version=1, event_type="hypothesis",
        verdict="baseline", title=title, body=body, observed_at=observed_at,
    )

def seed_silver_macro_hypothesis_v1() -> None:
    _seed_hypothesis_once_v1(
        strategy_key=STRATEGY_KEY_SILVER_MACRO, title="Starthypotese v1",
        body=("Sølv deler gulls monetære drivere, men utfallet avhenger også av industriell "
              "etterspørsel og et tilbud som delvis bestemmes av produksjonen av andre metaller. "
              "Strategien vurderer derfor Fed/realrenter og USD sammen med industri, gruve- og "
              "biprodukttilbud, fysiske flows og gull/sølv-relativprising. En monetær medvind er "
              "ikke alene tilstrekkelig dersom industri- eller tilbudssiden utvikler seg klart negativt."),
        observed_at="2026-09-27T18:30:00+00:00",
    )

def seed_oil_balance_hypothesis_v1() -> None:
    _seed_hypothesis_once_v1(
        strategy_key=STRATEGY_KEY_OIL_BALANCE, title="Starthypotese v1",
        body=("Oljestrategien følger balansen mellom etterspørsel, produksjon, kommersielle og "
              "strategiske lagerbevegelser, resupply/refill, geopolitisk risikopremie og terminkurve. "
              "Arbeidshypotesen er at vedvarende lagerstramhet eller framtidig refill/resupply kan "
              "skape asymmetrisk oppside når tilbudsresponsen ikke holder tritt. Hypotesen skal "
              "falsifiseres eller nedvekstes dersom lager bygges, etterspørselen svekkes eller "
              "produksjonsresponsen gir varig overskudd."),
        observed_at="2026-09-27T18:30:00+00:00",
    )

def seed_research_strategies_v1() -> None:
    seed_gold_fed_hypothesis_v1()
    seed_silver_macro_hypothesis_v1()
    seed_oil_balance_hypothesis_v1()
