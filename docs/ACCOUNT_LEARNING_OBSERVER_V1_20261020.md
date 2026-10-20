# Konto-læring v1 — valgfri, kontoavgrenset observatør

## Bruk
Åpne **Analyse → Konto-læring**. Velg en konto som allerede finnes i
Saxo-fasit; trykk **Følg kontoen automatisk hvert femte minutt**.
Fulgte kontoer lagres i Postgres med enkle PÅ/AV-verdier. Valg krever
ikke en aktiv V3-instans. Tomme kontoer er valgbare, men genererer
ikke falske resultater.

Den eksisterende `telegram_multi_worker` / separate konto-telemetriloopen
kjører `run_account_learning_cycle_v1` etter de vanlige Saxo-GETs.
Ingen ny HTTP/Saxo-klient og ingen direkte ordre. Selv om Streamlit-siden
lukkes, fortsetter femminuttersobservasjonen i Railway-worker.

## Grunnlag og kvalitet
- Eksakt account_id, currency, Saxo `TotalValue`, tidsstempel og
  `CalculationReliability=Ok` (kontoverdi hvert femte minutt).
- Historisk `context_json` lagret sammen med samme *øyeblikks* Saxo
  avlesning, med V3-strategi, timeframe og LIVE-status.
- `autotrader_v3_execution_events` er avstemte Saxo-ordre fra samme konto,
  nøyaktig samme V3-instans og innenfor strategiperioden.
- Læringsmotoren gjenbruker `observed_live_nav_windows_v1`: strategibytte,
  tidsbrudd >12,5 min, ukjent/mer enn én LIVE-strategi, ikke-verifisert
  Saxo-balansedata, eller ufinansierte kontoer stanser attribusjonen.
- Vi lagrer først hypoteser etter minst fire påfølgende verifiserte
  avlesninger og 15 minutters faktisk periode, der siste avlesning ikke
  er eldre enn 45 minutter.
- **Ingen** NAV-endring behandles som ren netto strategi-P/L; brokerens
  cashflows, funding, FX, andre instrumenter og manuelle handler er
  ikke avstemt. Vi bruker derfor bare `RESEARCH_ONLY` og
  `OBSERVATIONAL_NAV_NOT_STRATEGY_PNL`, uten win-rate-påstander.

## Tre observerte situasjoner
1. **Uavstemt NAV-fall og hyppige bekreftede V3-handler.**
   Hypotese om whipsaw; foreslå SIM A/B med 1–2 barers cooldown eller
   prisbekreftet inngang. Ingen automatisk promotion.
2. **Uavstemt NAV-fall uten tilstrekkelig turnover-bevis.**
   Først avstem innskudd/uttak/manuellhandel/finansiering, ikke tune
   parametre på feilaktig retur.
3. **Høy turnover uansett positiv/flat NAV.**
   Kostnadsfølsom SIM A/B før noen eventuell endring.

Observasjonsbasert hypoteser blir immutable journalrader med eksakt
konto, strategivindu, evidens, problemformulering og foreslått test.
Faste identiteter forhindrer duplikater ved 5m-polling og workerstart.

## Neste fase
Reell automatisk strategiforbedring krever historisk Saxo
cashflow-/transaksjonsavstemming og kausal replay av kandidater under
samme pris-/spreaddata, inkludert walk-forward og out-of-sample
kontroll. V1 **genererer etterprøvbare forslag**, men har ikke
automatisk parameter-tuning, LLM-trening, validering av oppnådde
forbedringer, eller rettigheter til å endre V3 LIVE. Disse er
bevisst ikke representert som ferdige funksjoner.
