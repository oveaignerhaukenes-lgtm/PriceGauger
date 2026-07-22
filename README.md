# PriceGauger Alpha

Mobilvennlig Streamlit-prototype som kobler offentlige meldinger fra Middle East Spectator (MES) mot prisutviklingen i Brent, sølv, gull og DXY.

## Kjør lokalt

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Publiser på Streamlit Community Cloud

1. Logg inn på Streamlit Community Cloud.
2. Velg **Create app**.
3. Velg repository `oveaignerhaukenes-lgtm/PriceGauger`.
4. Velg branch `main`.
5. Sett main file path til `app.py`.
6. Trykk **Deploy**.

## Første test

- Åpne appen på telefonen.
- Velg Brent eller Silver.
- Start med intervall `1h`, historikk `30d` og reaksjonsvindu `4` timer.
- Sjekk at både MES-meldinger og prisbarer lastes.
- Sammenlign hendelsesmarkørene med prisgrafen.

## Market State MVP

På grenen `feature/market-state-mvp` finnes en egen Streamlit-side, **Market State**, som tester den nye kjeden:

```text
Telegram-observasjon
→ strukturert state-delta
→ tidsvektet Market State
→ transparent mapping til Brent, Gold, Silver og DXY
→ LONG / SHORT / NEUTRAL
→ SQLite-logg
```

Uten modellnøkkel brukes en deterministisk mock-interpreter. Med OpenAI konfigurert brukes Responses API med strict JSON Schema; modellen leverer bare state-deltaer, evidens og usikkerhet. Handelsretningen beregnes fortsatt av vanlig kode. Når modellen byttes fra mock til OpenAI, tolkes den lagrede siste hendelsen automatisk på nytt én gang.

### Secrets / miljøvariabler

```toml
OPENAI_API_KEY = "..."
OPENAI_MARKET_MODEL = "gpt-5-mini"  # valgfri
```

De samme navnene kan settes som miljøvariabler ved lokal Linux-kjøring. Nøkkelen skal aldri legges i repositoryet.

## Begrensninger i Alpha

- Telegram-data hentes fra den offentlige forhåndsvisningssiden og dekker ikke full historikk.
- Yahoo-data er ikke børsgradert sanntidsdata.
- Canonical event-klassifiseringen er fortsatt delvis regelbasert.
- Statistikken viser korrelasjon, ikke kausalitet eller validert prediksjon.
- Market State-anbefalingene er et testinstrument, ikke validerte handelsråd.

Neste steg er kontinuerlig Telegram-innsamling, full smoketest på Linux og logging av priser etter anbefalingene.
