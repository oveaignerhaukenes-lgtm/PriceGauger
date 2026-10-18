# MACD+Stoch Rytmebygg v1 — kontrollert sammenligning med B og Hvelvet

Opprettet 18. oktober 2026. En *ny*, ren og deterministisk V3-strategi for å
teste brukerens idé: **minst mulig eksponering i whipsaw, bygg bare ved
dokumentert retning, og FLAT hele beholdningen når grunnsignalet går feil.**

Ingen av de eksisterende kontoene konfigureres eller armeres av PR-en.
Kontrollstrategiene MACD+Stoch v2 og v2.1 er uendret. Dette er ikke
dokumentasjon på positiv forventet avkastning.

## Godkjenningsstatus: KUN SIM/PAPER etter merge

Rytmebygg er med hensikt eksplisitt LIVE-sperret i *to* uavhengige lag:
`live_config_issues_v3` i katalog/UI og `StrategyAdapterV3.live_route_enabled=False`
i den faktiske LIVE-worker-rutingen. Eksisterende V3-kontoer påvirkes ikke.
Selv en direkte endring av databasekonfigurasjonen kan ikke aktivere Rytmebygg på LIVE.
Dette er ikke en vurdering av netto lønnsomhet. Før LIVE må same-clock backtest,
faktisk cost/margin/fill og separat godkjenning av isolert lavbudsjettkonto
være dokumentert.

## Strategi som kan velges i SIM etter merge

- Katalog: `MACD+Stoch · Rytmebygg v1`
- Konfigurasjonsnøkkel: `macd-stoch-rhythm-build`
- Runtime: `macd-stoch-rhythm-build-v1`
- Tidsperiode: **kun 1m**, validert i både LIVE og SIM
- Baseline: `macd-stoch-v2`, identisk 70/30 ATR-normalisert MACD-histogram
  og Stochastic, inngang etter to ferdige aligned bars. Samme harde
  `OPPOSITE_FLAT`, `WEAK_FLAT` og `FLAT_WARMUP` som V2.
- Oppstart: V2 åpner bare én Saxo-lovlig enhet ved gyldig nytt signal;
  driverens en-gang-per-lukkede-bar-tilstand forhindrer replay/akkumulering.
- Choppy: siste 12 ferdig lukkede og **sammenhengende** 1m-prisendringer:
  `efficiency = |price[-1]-price[-13]| / Σ |minute_returns|`;
  `reversals` = antall tegnskifter i retningsbevegelsene.
  Hvis effektivitet <= 0.35 **eller** minst 6 retningstilbakeslag,
  trim straks overeksponering ned til én enhet. Dersom FLAT, ikke åpne
  mot dette choppy-markedet; dersom allerede én enhet, behold den
  så lenge V2s score ikke krever full FLAT.
- Oppbygging: V2 må selv gi BUILD og markedet må samtidig ha:
  netto/path-effektivitet >=0.60, maks 3 tegnskifter på 12m,
  tre påfølgende sluttkurser i riktig retning og siste high/low
  som fortsetter samme retning. Én *ny* tranche per fullførte bar,
  opp til eksisterende V3/instrument-/kontogrense. Ingen egen
  leverage, bonus-risk eller ukontrollert sizing.
- Uklart prisforløp eller datahull: nekt OPEN/ADD og trim ned til én
  tranche hvis posisjonen er større. V2s FLAT går alltid foran.
- En oppgitt «minsteposisjon i whipsaw» betyr ikke at strategien
  tvinges til å åpne posisjon: den kan være FLAT, og om score sier
  feil retning skal ALLE enheter lukkes.

## Hvorfor vi holder den så enkel

V2 bygget fortløpende så lenge indikatorscoren var stabilt over terskelen.
V2.1 krever bare akselererende score før flere inkrementer.
Rytmebygg V1 er **én alternativ sizing-policy** og endrer ikke
grunnsignalet. Vi kan dermed teste den presise hypotesen:
«Gir begrenset eksponering under chop og oppbygging først i pris-trend
bedre *netto kontoutvikling* enn V2s umiddelbare oppbygging?»

Det er også mulig at filteret reduserer avkastningen:
trendbevegelser kan bestå av mange raske retningstilbakeslag, og
hyppig `TRIM_CHOP`/ny oppbygging kan øke omsetning og kostnader.

## Test-design mot de to kontrollkontoene

1. **Kontroll B:** Tech100-B, uendret MACD+Stoch v2/1m.
2. **Kontroll H:** Hvelvet, uendret MACD+Stoch v2/1m.
3. **Kandidat:** Én separat konto/instans som operatøren eksplisitt
   velger etter review – ikke utpekt eller armert av denne PR-en.
4. Lås starttidspunkt, instrument UIC, modifikatorer, timeframe,
   kontobeløp, capital cap/margin/risikoandel, valutaveksling og
   handelsvindu *før* periodens første handel. Like innskudd alene
   gjør ikke to kontoer direkte sammenlignbare.
5. Snapshot saldo/NAV og åpen posisjon rett før start. Bruk
   `start_NAV` og normalisert `net_return =
   (end_NAV - start_NAV - net_deposits_withdrawals) / start_NAV`.
   Dette er bare korrekt for en fast sammenligningsperiode uten
   tidsvektede inn-/utbetalinger; ved kapitalendringer underveis
   må det brukes tidsvektet avkastning.
6. Score **faktiske Saxo-fills** og gebyrer, ikke bare V3
   `executed` (som betyr akseptert ordreforsøk). Mål entry/exit-tid,
   størrelse, all-in kostnader, antall avvik og blokkerte ordre.
7. Rapporter nettoavkastning %, absolutt NOK, maksimal drawdown,
   tid i markedet, antall endringer, gjennomsnittlig eksponering,
   spread/slippage samt P/L per markedstype. Samme utvalgsvindu.
8. Kjør minst over flere forskjellige markedsdager/regimer;
   én grønn dag er ikke statistisk grunnlag for å øke kapital.

**Margin:** Per tidligere drift har PG eksponeringstak på 300 NOK per
instans og Saxo global klientmargin; forsøk på ekstra 0,01 kan bli
avvist selv om den valgte strategien lovlig ønsker 0,03.
Mer penger på konto ≠ automatisk høyere kapasitetsgrense.
Ikke endre kapitaltak, brokermargin eller kontrollkonti i denne PR-en.

## Tekniske sikkerhetskrav for review

- Ny identitet, samme V3 closed-bar driver og ordreplan,
  ingen Saxo-kall fra strategimodulen.
- LIVE-konti endres ikke ved deploy: kun eksplisitt valg
  av strategi og senere separat LIVE-arming gjennom eksisterende V3.
- Uansett rytme gir motsatt score FLAT hele posisjonen og
  ingen direkte reversering.
- Utdatert, ufullstendig eller gappet OHLC kan ikke bygge.
- Rejected/blocked BUILD må ikke senere gjenoppstå fra gammel
  cursor; eksisterende `align_closed_bar_target_v3` beholdes.
- Kontoer med lik saldo kan fortsatt ha ulike fill-tider,
  priser og kostnader; logg signal vs faktisk fill separat.
- Behold B/H uendret og ikke skriv om historisk NAV til
  «resultat av nåværende strategi».

## Testdekning

`tests/test_v3_macd_stoch_rhythm_build_20261018.py`:
syntetisk trend vs whipsaw, long/short symmetri, harde
FLAT-signaler, ingen bygg på hull, baseline-paritet for
førsteinngang, selvstendige V2-kontroller, persisted
cursor/idempotens, tidsrammevalidering, lovlig Saxo-enhet og
ingen direkte broker/DB myndighet.

Denne PR-en inneholder bevisst **ikke** noen ny indikatorscore,
AI, fraktalmodell eller adaptiv motor. Vi tester én endring.
