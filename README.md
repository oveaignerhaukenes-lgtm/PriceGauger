# PriceGauger

PriceGauger er et worker-first markedanalyse-system som kombinerer nyhets-/hendelsesdata, teknisk markedsstate, multi-horizon forecasts, outcome-læring og eksplisitt cross-market/adaptation-observasjon. PostgreSQL er autoritativ delt state i produksjon.

Se [`docs/PROJECT_HANDOFF.md`](docs/PROJECT_HANDOFF.md) for gjeldende arkitektur, guardrails, stabil baseline og eksplisitt utsatt arbeid.

## Hovedflyt

```text
Telegram / event context
→ Information State
→ Technical State
→ Decision State
→ 5m / 15m / 30m / 1h / 4h / 12h / 24h / 7d Forecasts
→ Outcomes
→ immutable ForecastErrorObservations
```

Parallelt kjører den deskriptive cross-market-kjeden:

```text
CrossMarketState
→ ResponseDivergence
→ TransmissionState
```

Denne kjeden observerer hvordan markedet faktisk reagerer og hvilke transmisjonsmekanismer som er konsistente med dataene. Den påvirker foreløpig ikke Decision State eller forecast-vekter.

## Produksjonsarkitektur

Produksjonen bruker tre Railway-tjenester fra samme `main` og samme PostgreSQL-database:

| Tjeneste | Config | Ansvar |
| --- | --- | --- |
| `pricegauger-web` | `/railway.streamlit.toml` | Streamlit UI / read-render |
| `pricegauger-worker` | `/railway.worker.toml` | Telegram, context, state, forecasts, outcomes |
| `pricegauger-stream` | `/railway.stream.toml` | Saxo realtime stream → canonical 1m bars |

Canonical realtime-dataflyt:

```text
Saxo stream
→ canonical completed 1m OHLC bars
→ PostgreSQL
→ TradingDesk / technical analysis / cross-market analysis
```

Browseren er aldri autoritativ market-data-producer og snakker ikke direkte med Saxo.

## Forecasts og læring

Forecasts er immutable og knyttet til eksakt Decision/Information/Technical state ved opprettelse.

- Åtte horisonter: `5m / 15m / 30m / 1h / 4h / 12h / 24h / 7d`.
- Movement magnitude kalibreres fra COMPLETE outcomes separat per `market × horizon`.
- Direction learning og regime learning er fortsatt eksplisitt deaktivert.
- Aktiv intrahorizon-bane kan visualiseres fra forecast-dommen + teknisk regime + volatilitet, men terminalintervallet er autoritativt.
- Historiske mellomliggende forecast-baner er visuell kontekst, ikke retroaktiv evidens.

## Cross-market / adaptation

`CrossMarketState` bruker canonical Silver / Gold / Brent / DXY og eksplisitte 15m / 1h / 4h-vinduer. US 2Y / 10Y / 30Y er definert som yields, men forblir `MISSING` til en verifisert yield-feed finnes; Treasury futures-priser skal aldri brukes som erstatning.

`ResponseDivergence` registrerer om realisert Silver-respons er `ALIGNED`, `DIVERGENT` eller `UNCONFIRMED` mot informasjonssignalet, med korrekt post-event tidsretning.

`TransmissionState` bruker diskrete evidensklasser (`SUPPORTED`, `PARTIAL`, `CONFLICTING`, `INSUFFICIENT`) og kan forbli `UNRESOLVED`. Den tvinger ikke fram en kausal historie.

## TradingDesk og AutoTrader

TradingDesk bruker samme canonical 1m-data og samme AutoTrader execution-komponent.

AutoTrader har to fysisk avgrensede execution-kapabiliteter:

- manuell entry/handel er fortsatt Saxo **SIM-only**, med server-side validering, precheck, eksplisitt confirmation, én submit og autoritativ read-back
- LIVE er kun close-only for en allerede åpen, eksakt Auto-managed posisjon
- LIVE close krever LIVE-miljø, separat kode-gate, aktiv execution-motor og gyldig per-position enrollment
- RiskControl bruker produktets egen posisjonsavkastning; canonical standard hard stop er **−2 %**
- 30m MACD LONG/FLAT kjører fortsatt kun som observerbar dry-run og har ingen execution-kobling
- ingen automatisk entry-strategi eller AI-execution er aktiv

## Markedschat

Markedschat er read-only beslutningsstøtte og bygger authoritative PostgreSQL-kontekst på nytt for hvert spørsmål. Samtalehistorikk kan videreføres, men chatten får ikke egen markedssannhet og har ingen execution-kobling.

Merk: CrossMarketState / ResponseDivergence / TransmissionState / forecast-error adaptation er ennå ikke lagt inn i Markedschat-konteksten.

## Lokal kjøring

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Én worker-runde:

```bash
python worker.py --once
```

Kontinuerlig worker:

```bash
python worker.py --interval 60
```

Realtime stream:

```bash
python realtime_worker.py --refresh-ms 1000
```

SQLite brukes bare lokalt/test der det er hensiktsmessig. Produksjon skal bruke `DATABASE_URL` og delt PostgreSQL.

## Utviklingsregel

All ny utvikling følger:

```text
fresh main
→ isolert branch
→ én bounded capability
→ focused tests
→ full GitHub Actions
→ draft PR
→ architecture/diff review
→ fresh-main check
→ merge med exact-head guard
```

Ikke gjenoppta gamle branches blindt. Historiske forecasts skal aldri omskrives, heuristikker skal være synlige/versionerte, og nye forklaringsmekanismer skal ikke få læringsvekt uten outcome-evidens.
