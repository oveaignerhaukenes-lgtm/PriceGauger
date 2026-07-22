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

På grenen `feature/market-state-mvp` finnes en egen Streamlit-side, **Market State**:

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

En egen **Signal History**-side viser anbefalingene mot senere markedsrespons. Uferdige prisresultater fylles når appen åpnes igjen.

### Secrets / miljøvariabler

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

## Begrensninger i Alpha

- Telegram-data hentes fra den offentlige forhåndsvisningssiden og dekker ikke full historikk.
- Yahoo-data er ikke børsgradert sanntidsdata.
- Streamlit fyller prisresultater ved sidekjøring; kontinuerlig bakgrunnsinnsamling kommer senere.
- GDELT DOC er artikkel-/narrativsøk og ikke en komplett, autoritativ hendelsesdatabase.
- Canonical event-klassifiseringen er fortsatt delvis regelbasert.
- Statistikken viser korrelasjon, ikke kausalitet eller validert prediksjon.
- Market State-anbefalingene er et testinstrument, ikke validerte handelsråd.
