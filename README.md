# PriceGauger Alpha

Mobilvennlig Streamlit-prototype som kobler offentlige meldinger fra Middle East Spectator (MES) mot prisutviklingen i Brent, sølv, gull og DXY.

Se [prosjektoverleveringen](docs/PROJECT_HANDOFF.md) for gjeldende produksjonsarkitektur, stabiliseringssjekk og bevisst utsatt arbeid.

## Kjør lokalt

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Market State MVP

```text
Telegram-observasjon
→ strukturert state-delta
→ tidsvektet Market State
→ transparent mapping til Brent, Gold, Silver og DXY
→ LONG / SHORT / NEUTRAL
→ PostgreSQL-logg i produksjon, SQLite lokalt
→ pris ved signal, 1t/4t-resultat og MFE/MAE
```

Uten modellnøkkel brukes en deterministisk mock-interpreter. Med OpenAI konfigurert brukes Responses API med strict JSON Schema; modellen leverer bare state-deltaer, evidens og usikkerhet. Handelsretningen beregnes fortsatt av vanlig kode.

En egen **Signal History**-side viser anbefalingene mot senere markedsrespons.

## Worker

Én kontrollert runde:

```bash
python worker.py --once
```

Kontinuerlig innsamling hvert minutt:

```bash
python worker.py --interval 60
```

Workeren:

- sjekker Telegram hvert 60. sekund
- behandler bare nye meldinger
- oppdaterer og lagrer rullerende nyhetskontekst over 1t/4t/12t/24t/7d
- bruker OpenAI når nøkkel er konfigurert, ellers mock-interpreter
- lagrer Market State, anbefalinger og utfall i PostgreSQL når `DATABASE_URL` er satt, ellers SQLite lokalt
- oppdaterer 1t/4t-resultater og MFE/MAE i hver syklus

Den låste papirtesten bruker fortsatt 5-minutters prisbarer. Senere kan 1-minutts rådata lagres og aggregeres til 5 minutter uten å endre første testprotokoll.

## Realtime stream

Saxo realtime-kjernen kjøres separat fra analyseworkeren:

```bash
python realtime_worker.py --refresh-ms 1000
```

Streamtjenesten:

- bruker Saxo WebSocket/subscriptions i stedet for høyfrekvent REST-polling
- ber om 1000 ms refresh, men registrerer den faktiske raten Saxo tildeler
- holder løpende quotes transient i minnet
- aggregerer og lagrer ferdige 1-minutts OHLC-barer i PostgreSQL
- lagrer UIC, asset type og symbol sammen med barene for kontraktssporbarhet
- registrerer streamstatus og eventuell markedsdataforsinkelse uten å skrive til databasen hvert sekund
- reconnecter etter reset/disconnect uten å påvirke analyseworkeren eller Streamlit-webben

## Secrets / miljøvariabler

```toml
OPENAI_API_KEY = "..."
OPENAI_MARKET_MODEL = "gpt-5-mini"
GDELT_PROVIDER = "direct"
```

`GDELT_PROVIDER` kan være:

- `direct` – gratis offisiell GDELT DOC 2.0, standard og uten nøkkel
- `cloud` – eksisterende betalt GDELT Cloud-provider; krever `GDELT_CLOUD_API_KEY`
- `auto` – bruker cloud når nøkkel finnes, ellers direct

GDELT behandles som sekundær evidens om sirkulasjon, repetisjon og historisk markedsrespons, ikke som autoritativ sannhetskilde.

## Railway

Produksjonen bruker tre Railway-tjenester fra samme repository og branch, koblet
til samme Railway PostgreSQL-database:

| Tjeneste | Config file path | Startkommando |
| --- | --- | --- |
| Streamlit | `/railway.streamlit.toml` | `streamlit run app.py ... --server.port $PORT` |
| Worker | `/railway.worker.toml` | `python worker.py --interval 60` |
| Realtime stream | `/railway.stream.toml` | `python realtime_worker.py --refresh-ms 1000` |

Ved deploy:

1. Opprett eller behold én PostgreSQL-tjeneste i Railway-prosjektet.
2. Opprett tre tjenester fra dette GitHub-repositoryet: `pricegauger-web`,
   `pricegauger-worker` og `pricegauger-stream`. Alle skal bruke `main`.
3. Sett **Config File Path** til `/railway.streamlit.toml` for webtjenesten,
   `/railway.worker.toml` for analyseworkeren og `/railway.stream.toml` for
   realtime-tjenesten.
4. Gjør PostgreSQL-variabelen `DATABASE_URL` tilgjengelig i alle tre tjenester.
   Alle må peke til den samme databasen.
5. Legg `OPENAI_API_KEY`, `OPENAI_MARKET_MODEL` og nødvendige Telegram-variabler
   på analyseworkeren. Saxo-variablene `SAXO_APP_KEY`, `SAXO_APP_SECRET`,
   `SAXO_REDIRECT_URI` og `SAXO_ENVIRONMENT` må være identiske på web, worker og
   realtime stream. Når `DATABASE_URL` er satt, lagres det roterende
   Saxo-tokenparet i PostgreSQL og deles av de tre tjenestene. Realtime-tjenesten
   kan i tillegg bruke `PRICEGAUGER_STREAM_REFRESH_MS` dersom ønsket rate skal
   overstyres; standard er 1000 ms. Legg også modellvariablene på webtjenesten
   dersom UI-et bruker dem direkte.
6. Deploy alle tre tjenester. Webtjenestens healthcheck er `/_stcore/health`;
   workerloggen skal vise `cycle complete` hvert 60. sekund, mens
   `pricegauger-stream` skal vise aktive Saxo subscriptions og løpende quotes
   uten å restarte analyseworkeren.

Det skal ikke monteres et SQLite-volum på `/data` i produksjon. Uten
`DATABASE_URL` faller applikasjonen tilbake til lokal SQLite, som bare er ment
for lokal utvikling og isolerte tester.

## Begrensninger i Alpha

- Telegram-data hentes fra den offentlige forhåndsvisningssiden og dekker ikke full historikk.
- Yahoo-data er ikke børsgradert sanntidsdata.
- GDELT DOC er artikkel-/narrativsøk og ikke en komplett, autoritativ hendelsesdatabase.
- Canonical event-klassifiseringen er fortsatt delvis regelbasert.
- Statistikken viser korrelasjon, ikke kausalitet eller validert prediksjon.
- Market State-anbefalingene er et testinstrument, ikke validerte handelsråd.
