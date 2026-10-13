# NextGen MACD — ny strategikjerne og isolert PAPER-lab

Dato: 2026-10-13. Dette er **ikke** en LIVE-aktivering eller erstatning av aktive strategier.

## Arkitektur

- **Nye strategier · MACD** er standardvisningen i Live-Sim Lab.
- **Legacy strategies** viser de gamle, uforandrede LiveSim-eksperimentene med eksisterende rapporter, AI-armer og historikk. Tabellen, worker og DB er ikke flyttet eller tømt.
- Eksisterende V3-strategier velges fortsatt fra en egen **Legacy strategies**-nedtrekksboks i V3 Fleet/TradingDesk.
- V3-katalogens eksisterende `macd` kalles nå **MACD Trailing · Legacy**, men beholder samme interne nøkkel og runtime. Det er ikke den rene MACD Flip-kontrollen.
- Feilaktig, tapsgivende mapping fra gamle `macd-Nm-flip-control-shadow-v1` til `macd`/Trailing er fjernet fra deklarativ migrering. Aktive konfigurasjoner endres ikke.

## En ny MACD 12/26/9-klasse

Kun ferdige, konsekutive UTC-justerte timeframe-barer evalueres. Perioder: 1, 2, 5, 10, 15 og 30 min. Fullførte 1-minutts OHLC brukes til historisk PAPER-replay, og signalet kan tidligst få virtuell fill ved neste 1m-åpning.

Fire brytere, ingen implisitte modifikatorer:

1. **Flip**: motsatt bekreftet MACD-regime reverserer LONG/SHORT når Pyramide er AV. Uten Flip går strategien FLAT og må vente på et senere motsatt/samme nytt MACD-kryss.
2. **Hold before flip**: behold posisjon mellom kryss, uten å trappe ned ved svakere MACD-histogram. Denne og Trailing er gjensidig utelukkende.
3. **Pyramide**: én normalisert tranche ved regimejustert histogramakselerasjon, inntil konfigurert makseksponering. **Ved motsatt MACD-regime settes hele målet til FLAT umiddelbart**, uten delvis nedtrapping. Med Flip kan ny retning først bygges etter et etterfølgende ferdig signallys. Denne PAPER-forsinkelsen er konservativ og må erstattes av faktisk broker-bekreftet FLAT ved eventuell LIVE-adapter.
4. **Trailing**: når Hold er AV, reduseres én tranche ved motgående histogramimpuls *innen samme MACD-regime*. Ved faktisk MACD-motsignal brukes full FLAT/reversering som i Flip-reglene. Trailing er ikke tillatt sammen med Hold.

Pyramide er ikke fysisk Saxo-gearing. Målet er en normalisert eksponering i [-1,+1]; hele ordrekjeden, Saxo-lots og risiko skal valideres separat før en fremtidig LIVE-godkjenning.

## Kostnader, resultat og rangering

- Generell **Inkluder kostnader**-bryter; per side antas initialt **0,08 %** avgift og **0,01 % full bid/ask-spread**. Dette er redigerbare testantakelser, **ikke bekreftede Saxo-satser**.
- Ved hver endring brukes `abs(ny_eksponering - gammel_eksponering)` multiplisert med avgift pr. side og **halv** full spread. LONG -> SHORT gir omsetning 2.0 og tilsvarende to avgiftssider.
- Ingen finansiering, fysisk broker-fill, partial fills, intrabar slippage, margin eller valutarisiko er med; tallene er ikke ekvivalent med Saxo netto P/L.
- Alle valgte perioder bruker samme markedsfeed, tidsvindu og kostnadsantakelser. Endringer i toggles / kostnader recalculerer tabell og graf umiddelbart; **historisk replay**, ikke ny uavhengig forwardtest.
- Legenden på høyre side ved bred skjerm sorteres etter avkastning, vinnende øverst; på smale skjermer flyttes den under. Mus over linje identifiserer nærmeste serie. Dobbeltklikk på kurve eller trykk legend-navn isolerer linjen; gjenta for alle.
- Resultat-ID er versjonert og inkluderer timeframe, brytere og maks trancher. Referanser til eventuell fremtidig manager må bruke versjonert identitet og **verifiserte, kostnadsjusterte forwardresultater**, ikke automatisk kopiere den foreløpige historiske vinneren.

## Veien videre

- Implementer egne **Histogram**- og **Stochastic**-familier etter samme target/filled-price-kontrakt, og senere eksplisitte hybrider. Ikke gjenbruk `macd` som tvetydig navn.
- Legg til en durabel, framoverrettet NextGen-paper-ledger som fryser hver config/signalversjon ved aktivering. Historiske replay-resultater skal aldri kamufleres som prospektiv P/L.
- Etabler broker-kalibrert spread, kommisjon, slippage, funding, handelsstørrelse og markedsstenging per instrument/konto.
- Før en mulig LIVE-adapter: paritetstester med samme frosne data og full CLOSE -> broker-bekreftet FLAT -> OPEN, idempotens og feil/duplikat-ordre-guard. Ingen LIVE-autoritet til NextGen i denne PR.

## Sikkerhetsgrense

Ingen Saxo-klient eller LIVE-trading importeres i `macd_nextgen_paper_v1.py`, og ingen konfigurasjon migreres/oppdateres ved rendering. Ingen endring i eksisterende V3 LIVE-ordrelogikk, instansers enabled/armed, allokeringer eller posisjoner.
