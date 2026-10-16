# Unngå tap V1 — operatørstyrt Saxo-diagnose i Fleet (2026-10-16)

Status: **READ-ONLY DIAGNOSTIKK; IKKE LIVE-READY**. Alle autoriteter og
ordrerutinger er uendret.

## Hvorfor
En reell Railway SSH GET-only prøve returnerte fire NOK Saxo-kontoer for
US Tech 100 NAS (UIC 4912), hvorav tre var FLAT_OBSERVED og den første
returnerte \`SAXO_RESPONSE_VALIDATION_FAILED\` i den eldre prøven. En
senere separat GET fant ingen åpne posisjoner på første konto i det
øyeblikket. Ingen av utfallene dokumenterer reell LIVE tapsstoppsikkerhet.

Den gamle prøven slo sammen ugyldige Saxo-responsfelter i én uklar
valideringsfeil og krevde manuell PowerShell/Railway SSH. Nå finnes
en knappeutløst, isolert GET-only diagnose **inne i Fleet per V3-instans**.

## Bruk
Fleet → Administrer instansen → \`Unngå tap V1 · Saxo datakontroll
(kun lesing)\` → \`Les og valider Saxo-feltene nå\`.

Returnerer kun statiske status-/fase-/årsakkoder og statiske verifiserte
felt, eksempel:
\`BLOCKED · QUOTE · LAST_TRADED_MARKER_NOT_TIMESTAMP\`.
Ingen konto-ID, PositionId, pris, P/L, margin, antall lot, tokens, rå
Saxo-respons eller broker-unntakstekst blir eksponert av diagnostikken.
Den er ikke automatisk schedulert, og sender kun Saxo GET. Den lagrer
heller ikke resultatet i database eller logg.

## Verifiseringssekvens
1. Unik eksakt NOK-konto.
2. Eksakt account+instrument-scoped net/individual GET.
3. Én unik PositionId, korrekt konto/UIC/type og åpen posisjon.
4. Samsvar signert net inventory vs individuell størrelse (mengder vises ikke).
5. Tallvaliditet på P/L i basiskontoen og kostnadsfelt (beløp vises ikke).
6. Saxo \`CalculationReliability\`, delay og parsebar ISO-tidsmarkør.
   \`CurrentPriceLastTraded\` har **ikke bevist semantikk som executable quote
   timestamp**. Dermed gir selv "recent last traded" ikke sikker
   quote-ferskhet og **kan aldri sette live_ready=True**.

Hvis posisjonen er flat: \`FLAT_OBSERVED\` er gyldig observasjon,
men viser ikke om P/L-/kostnadsfeltene fungerer når en posisjon åpnes.

## Neste porter før LIVE
- Reell bekreftelse av margin og konto-NAV-valuta; frys initial margin
  fra en verifisert **ny** åpningsordre, aldri eksisterende posisjoner.
- Valider Saxo quote tidskilde, P/L, finansiering og kostnader uten
  dobbeltregning.
- Reconciled FinalFill+Confirmed og robust broker CLOSE→FLAT inklusive
  timeout, delvis fill, arbeidende ordre og worker restart.
- Isolert konto + eksplisitt godkjent minimal risiko LIVE-pilot.
- Ikke merge gammel \`#721\` helhetlig; LIVE-rutingen er ikke verifisert.

Per instans-reset \`#731\` påvirkes ikke.
