# PriceGauger

PriceGauger er et worker-first markedanalyse- og trading-supportsystem med canonical markedsdata, deterministisk Technical Core, eksplisitte context/forecast-lag og et separat risk-controlled AutoTrader-subsystem. PostgreSQL er autoritativ delt state i produksjon.

**Gjeldende implementasjonsstatus:** [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md)  
**Arkitekturprinsipper:** [`docs/PRICEGAUGER_V2_ARCHITECTURE.md`](docs/PRICEGAUGER_V2_ARCHITECTURE.md)  
**Systemoversikt:** [`docs/PRICEGAUGER_V2_SYSTEM_OVERVIEW.md`](docs/PRICEGAUGER_V2_SYSTEM_OVERVIEW.md)

Eldre handoff-filer er historiske. Ikke bruk dem som current authority uten å kontrollere `CURRENT_STATUS.md` og fersk `main`.

## Hovedarkitektur

```text
Provider / Saxo instrument identity
→ dynamic instrument registry / subscriptions
→ canonical 1m observations
→ deterministic Technical Core
→ technical baseline forecasts
→ WorkspaceSnapshotV2
→ optional explicit context / interpretation layers
→ recipe-composed forecast
→ Overview / TradingDesk / Companion
→ AutoTrader risk/execution boundary
→ realized outcome / evaluation / calibration
```

Technical Core er bevisst context-blind og skal alltid kunne brukes som TA-only kontrollgruppe. Høyere lag kan påvirke eksplisitte recipes, men skal ikke stille og rolig omskrive den deterministiske baseline.

## Produksjon

Produksjonen kjører fra samme `main` og samme PostgreSQL-database på Railway:

| Tjeneste | Ansvar |
| --- | --- |
| `pricegauger-web` | Streamlit UI, Overview, TradingDesk |
| `PriceGauger-worker` | Telegram/news ingest, context/state/forecast-relatert workerflyt |
| `PriceGauger-stream` | Saxo realtime/canonical data, Technical Core og AutoTrader-daemons |
| PostgreSQL | autoritativ delt persistens |

Canonical realtime-dataflyt:

```text
Saxo / provider data
→ exact provider instrument identity
→ canonical completed 1m OHLC
→ PostgreSQL
→ shared technical / forecast / TradingDesk / AutoTrader consumers
```

Browseren er aldri autoritativ market-data-producer.

## Forecasts, context og cross-market

Forecasts er immutable/idempotente ved semantisk identitet og kan evalueres mot realiserte outcomes. Optional layer-output er bundet til eksakt workspace fingerprint.

Context/Companion ligger over Technical Core og har ingen direkte execution-authority.

Den deskriptive cross-market-kjeden følger fortsatt prinsippet:

```text
CrossMarketState
→ ResponseDivergence
→ TransmissionState
```

Den skal beskrive evidens, ikke tvinge fram en kausal historie. US 2Y / 10Y / 30Y skal bare representeres som yields når en verifisert yield-feed finnes; Treasury futures-priser er ikke en erstatning.

## TradingDesk og AutoTrader

TradingDesk bruker canonical v2 identity og går gjennom AutoTrader for execution. AutoTrader er et separat product/strategy/risk/execution-subsystem.

### 30m MACD-strategier

- `macd-30m-long-flat-v1`: bullish cross → LONG, bearish cross → FLAT
- `macd-30m-short-flat-v1`: bearish cross → SHORT, bullish cross → FLAT
- `macd-30m-long-short-v1`: LONG ↔ SHORT via **CLOSE → confirmed FLAT → OPEN**

Signalgrunnlaget er fully closed 30m MACD 12/26/9 på eksakt canonical instrumenthistorikk.

### Entry-policy er separat fra strategi

- **Manage-only:** brukeren åpner/resizer/reverserer; PriceGauger kan håndtere exit, men sender aldri OPEN.
- **Full auto:** fersk strategi-entry kan gå gjennom alle Product Admission / Margin / Saxo precheck / idempotency-gater uten ny bekreftelse.
- **Approval required:** CLOSE kan være automatisk; hver konkret OPEN krever one-shot approval og full revalidering.

Manage-only er persistent på eksakt `account + UIC + AssetType`: senere manuelle posisjoner kan adopteres til ny exact managed basis og nytt risk epoch uten at PG får OPEN-authority.

### Execution safety

LIVE execution er fail-closed og beholder blant annet:

- LIVE Saxo environment + separate code/persisted arming gates
- exact product/position identity og basis re-read
- Saxo precheck før POST
- durable attempt før POST
- no blind retry etter uncertain submission
- separate Product Admission og Margin Envelope for OPEN
- authoritative close/P&L reconciliation
- pilot equity = seed + settled realized net P/L
- unrelated Saxo cash og unrealized P/L brukes ikke til compounding
- LLM/Companion har ingen order placement eller sizing authority

Shadow-scorecardet sammenligner long/flat, short/flat og flip deterministisk fra samme observerte startbasis uten å skrive til LIVE P/L-ledger eller order-path.

## Lokal kjøring

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Worker én runde:

```bash
python worker.py --once
```

Kontinuerlig worker:

```bash
python worker.py --interval 60
```

Realtime / Technical Core / AutoTrader stream-runtime:

```bash
python realtime_worker.py --refresh-ms 1000
```

SQLite brukes bare lokalt/test der det er hensiktsmessig. Produksjon bruker `DATABASE_URL` og PostgreSQL.

## Utviklingsregel

```text
fresh main
→ én bounded capability per branch/PR
→ focused tests
→ full compile + pytest
→ self/architecture review
→ fresh-main check
→ expected-head merge
→ verify exact Railway deployment SHA
→ inspect runtime logs/behavior
```

Ikke gjenoppta gamle branches blindt. Ikke gjør brede execution-refactors for kosmetikk. Nye forklarings- eller læringsmekanismer skal være eksplisitte, versionerte og empirisk målbare.