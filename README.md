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

Før en modellnøkkel er konfigurert brukes en deterministisk mock-interpreter. Den er laget for å teste dataflyt, lagring, state-matematikk og UI; anbefalingene er ikke ment som validerte markedssignaler.

## Begrensninger i Alpha

- Telegram-data hentes fra den offentlige forhåndsvisningssiden og dekker ikke full historikk.
- Yahoo-data er ikke børsgradert sanntidsdata.
- Hendelsesklassifiseringen er foreløpig nøkkelordbasert.
- Statistikken viser korrelasjon, ikke kausalitet eller validert prediksjon.
- Market State-siden bruker foreløpig en mock-interpreter, ikke en ekstern AI-modell.

Neste steg er å koble en strukturert modellprovider til interpreter-grensesnittet, kjøre kontinuerlig Telegram-innsamling og logge priser etter anbefalingene.
