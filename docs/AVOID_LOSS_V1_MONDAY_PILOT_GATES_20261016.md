# Unngå tap V1 — helgearbeid og mandagspilot (2026-10-16)

**Status: REN, TESTBAR STYRINGSMODELL. IKKE LIVE-ARMED.**

Markedet er stengt frem til mandag. Vi bygger funksjonelle
state transitions uten å kjøre handler eller endre fire aktive V3-motorer.

## Autoritativ livssyklus
1. **OPEN** må være en ny Saxo-posisjon med validert individuell PositionId,
   RECONCILED durable OPEN og riktig bekreftet full fill og fryst **NOK**
   initial-margin fra akkurat ordren. Aldri adopter eldre manuelle posisjoner.
2. **MONITORING** holder HWM og aktivering av +2 % / 10 % giveback. Netto
   NOK P/L fra samme konto/posisjon med dokumenterte kostnader; -1 % er
   bare trigger til CLOSE, **ingen garantert maks-tap**.
3. **CLOSE_REQUIRED** er en intent, IKKE ordrefill. Før LIVE-dispatch
   kreves ferske Saxo-priser, marked åpent, riktig konto/posisjon, ingen
   andre broker-ordre og en unik V3 durable request (CAS).
4. **WAIT_ORDER** ved SUBMITTING/SUBMITTED/UNKNOWN/RESERVED. Ingen
   retry på timeout, partial fill eller ukjent Saxo-status. Terminal
   REJECTED/RECONCILED med posisjon fortsatt åpen ⇒ UNPROTECTED,
   krever separat avstemming.
5. **WAIT_MARKET** beholder sticky stop pending over natt/helg. Ingen
   ordre ved stengt marked eller ukjent status. Oppfrisket quote og
   nytt Saxo-posisjonsbevis må foreligge ved ny åpning.
6. **BROKER_FLAT_VERIFIED** krever både tomme account-scoped NET og
   INDIVIDUAL posisjonslesinger, ingen arbeidsordrer, en reconciled
   CLOSE + uavhengig \`FinalFill/Confirmed\` audit og varig stopplås.
   Slett aldri ankret på grunnlag av order POST-svar alene.
7. **FLAT**: ny MACD 2m inngang krever ny ferdig bar etter forrige exit,
   og dokumentert Saxo-margin/cost/marked åpent, én lovlig tranche.

Modulen \`autotrader_v3_avoid_loss_supervisor_v1.py\` er en **ren
planlegger** uten ordre-, database- eller worker-importer; den returnerer
intents/statuskoder, ikke eksekvering. Full regresjonstest kjøres i CI,
inkludert mandagsåpning, omstart/latch, kostnads/P&L outage, delvis
fill, UNKNOWN og feil konto.

## Operasjonell helgestatus / mandag
- Eksisterende V3 og Saxo-kontoer urørt. Ingen automatisk arming.
- Repo \`#721\` forblir DRAFT; aldri bulk-merge.
- Diagnostikk per instans fra \`#732\` er tilgjengelig i Fleet.
- Før en begrenset LIVE-pilot må **reell Saxo-posisjonsrespons med P/L,
  quote-tidssemantikk, full funding/kostnad og NOK-margin dokumenteres**.
  Enhetstester og en vellykket read-only GET er ikke dette beviset.
- Isolert konto, spesifikt beløp og eksplisitt tillatelse før ordre.
- V3-ordreflyt må bevare idempotens under restart og partial fills.
