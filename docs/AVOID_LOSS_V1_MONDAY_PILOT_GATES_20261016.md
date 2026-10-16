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


## Ferdig kode: inaktiv V3 CLOSE-dispatch for senere godkjent pilot

\`autotrader_v3_avoid_loss_pilot_dispatch_v1.py\` implementerer en
**separat operatørutløst, men ikke registrert/kalt** CLOSE-dispatch til
eksisterende V3 Saxo-adapter og durable order guard. Den er ikke knyttet
til V3 worker og vil derfor aldri handle ved merge/deploy.

Tre uavhengige barrierer kreves før selv første broker-lesing i et
autorisert pilot-kall: \`explicit_pilot_approval=True\`,
\`PG_AVOID_LOSS_V1_LIVE_PILOT_ENABLE=enabled\` på server, og eksakt
\`PG_AVOID_LOSS_V1_PILOT_TRADER_ID\` +
\`PG_AVOID_LOSS_V1_PILOT_ACCOUNT_ID\`. Koden krever dessuten separat
aktiv V3-instance, riktig konto-ownership og armed LIVE, en attestert
immutable entry anchor, fersk sticky stop state, market_status open,
ingen working orders, riktige broker individual/net positions, identisk
signert inventory ved to GET-avlesninger og godkjent CLOSE-precheck.

Så lagres sticky stop state **før** atomisk V3
RESERVED→SUBMITTING→POST→SUBMITTED. Etter POST: UNKNOWN ved timeout eller
manglende Saxo OrderId; aldri automatisk retry. Dette rapporteres aldri
som broker-FLAT før eksakt CLOSE audit + begge posisjonslesinger er
bekreftet. Koden er bevisst konservativ: Terminal tidligere CLOSE med
fortsatt eksponering krever manuell utredning, ikke en ny ordre.

### Det som fremdeles ikke er bevist
- Om Saxo faktisk oppgir forventet NOK initial margin på
  \`MarginImpactBuySell\` og om alle kostnadskomponenter kan regnes uten
  dobbelttelling. Krav om dette blokkerer ny strategi-entry.
- At \`CurrentPriceLastTraded\` er et quote-tidspunkt. Det kan også være
  en markedspris-/handelsmarkør; egnet tidsgrunnlag må dokumenteres.
- End-to-end virkelig broker-FinalFill og CLOSE→FLAT for isolert konto,
  og arbeidstid under API timeout. Det skal måles mandag med spesifikt
  budsjett og eksplisitt arming.

**Ingen feature-flagg skal settes i Railway under helgearbeidet.**


## Ferdig kode: CLOSE→FLAT-koordinator og stopplås ved restart

\`autotrader_v3_avoid_loss_pilot_coordinator_v1.py\` kobler
\`AvoidLossPilotPlanV1\` til eksisterende vedvarende state-table:
\`persist_avoid_loss_plan_v1\` lagrer oppdatert HWM/sticky stop
**før** CLOSE kan forsøkes.

Etter ordre-submit er en egen, aldri automatisk påkalt
\`reconcile_avoid_loss_close_v1\` definert: krever
1. Durable CLOSE request med \`RECONCILED\`, uten uavklart ordre på
   konto/instrument.
2. Bekreftet unik konto og NOK, ingen aktive Saxo-ordre.
3. To påfølgende tomme GET-resultater fra *begge* eksakt NET og
   individuell Saxo posisjon.
4. Eksakt \`OrderId\` fra durable ledger, \`FinalFill\`,
   \`SubStatus=Confirmed\`, riktig side/mengde/**PositionId**.
5. Ytterligere tom NET/individual GET og ingen working order eller
   pending-lock før ankeret kan pensjoneres.
6. Skriver \`last_exit_signal_at\` slik at neste MACD-2m entry aldri
   re-spiller en eldre candle etter FLAT.

Dette setter IKKE \`live_ready=True\`. Ingen av modulene kjøres
fra normal V3 LIVE worker eller eksponerer en LIVE-knapp. Dette er
isolert og testbar funksjonalitet for mandagens verifisering.
