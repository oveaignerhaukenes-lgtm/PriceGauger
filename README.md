# PriceGauger Alpha

Mobilvennlig Streamlit-prototype som kobler offentlige meldinger fra Middle East Spectator (MES) mot prisutviklingen i Brent, sølv, gull og DXY.

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
→ SQLite-logg
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
- bruker OpenAI når nøkkel er konfigurert, ellers mock-interpreter
- lagrer Market State, anbefalinger og utfall i SQLite
- oppdaterer 1t/4t-resultater og MFE/MAE i hver syklus

Den låste papirtesten bruker fortsatt 5-minutters prisbarer. Senere kan 1-minutts rådata lagres og aggregeres til 5 minutter uten å endre første testprotokoll.

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

Repositoryet inneholder `railway.toml` med startkommando:

```text
python worker.py --interval 60 --db /data/pricegauger.db
```

Ved deploy:

1. Opprett et Railway-prosjekt fra GitHub-repositoryet.
2. Velg grenen som skal deployes.
3. Legg inn `OPENAI_API_KEY` og `OPENAI_MARKET_MODEL` som Railway Variables.
4. Opprett et persistent volume og monter det på `/data`.
5. Verifiser i loggen at workeren starter med 60 sekunders intervall og skriver `cycle complete`.

Uten volum forsvinner SQLite-databasen ved redeploy eller ny instans.

## Begrensninger i Alpha

- Telegram-data hentes fra den offentlige forhåndsvisningssiden og dekker ikke full historikk.
- Yahoo-data er ikke børsgradert sanntidsdata.
- GDELT DOC er artikkel-/narrativsøk og ikke en komplett, autoritativ hendelsesdatabase.
- Canonical event-klassifiseringen er fortsatt delvis regelbasert.
- Statistikken viser korrelasjon, ikke kausalitet eller validert prediksjon.
- Market State-anbefalingene er et testinstrument, ikke validerte handelsråd.
