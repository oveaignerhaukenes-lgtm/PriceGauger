# Live-Sim Lab – Hyper-Vigilant Stochastic (prospektivt PAPER-forsøk)

Dato: 2026-10-12. Eksperiment: `hyper-stoch-1s-v1`.

## Forskningsspørsmål

Gir Stochastic-styrt sekundersignal bedre nettoresultater når MACD fungerer som en reservemotor ved ubestemt Stochastic, en separat **prisobservatør** kan overstyre posisjoner som beveger seg galt, og whipsaw-detektoren hindrer gjentatt flipp i svært små svingninger?

Brukeren observerte at 2m/15m-motorene beholdt LONG under fall mens en 5m-motor flippet hyppig i konsolidering. Dette kan være feil kombinasjon av signalhorisont, kostnad og regime. Hyper-Vigilant undersøker hypotesen separat **uten LIVE fullmakt**.

## Datagrunnlag – faktisk 1s, ikke syntetisk

- Eksisterende Saxo WebSocket har nominell refresh 1000 ms. Lab recorder i samme strøm lagrer høyst én **faktisk mottatt, omsettelig og ikke-forsinket** bid/ask-quote per sekund per Tech100-UIC.
- Kun ekte bid/ask med `DelayedByMinutes=0` og begge `PriceType* = Tradable`; unaturlig spread, stale (over 5 sekunder) og fremtidsstemplede quotes avvises.
- Ingen REST polling per sekund, ingen Saxo-ordreendepunkt, ingen interpolering eller sekunddata utledet fra minuttsbarer.
- Oppstart: allerede registrerte quotes kan varme indikatorene, men genererer **ikke** historisk P/L. Posisjoner aktiveres bare på senere fremoverrettede quotes.
- Databrudd over 5 sekunder avbryter hypotetiske pending fills og nullstiller kortsiktig indikatorhistorikk. Ingen hypotetisk handel gjennom et databrudd.
- Om Saxo-prisstrømmen faktisk leverer sjeldnere enn 1 Hz, må datadekningen telles; tidsintervallene er reelle, ikke antatt.

## Strategien

**Stochastic primær:** høy/lav beregnes fra omtrent 60 sekunder med faktiske 1s samples (≥45 samples kreves). K-linjen skal ha positiv endring over 2 poeng fra siste quote og ligge mer enn ett poeng over utjevnet D (EMA8) for LONG; tilsvarende negativt for SHORT. Når K står nesten stille (ΔK ≤1 og |K-D| ≤3), kan MACD 20/45/15 på quote-prisene avgjøre retningen hvis histogrammet er betydelig større enn den observerte lokale prissstøyen.

**Pris som uavhengig observatør:** ved SHORT og en oppgang på minst maksimum av 0,06 % eller en adaptiv 15s-støygrense, foreslår PRICE-modellen FLAT selv om oscillator fremdeles peker ned. Motsatt for LONG. Også 0,12 % ugunstig bevegelse fra teoretisk inngang gir FLAT. Ingen umiddelbar full motsatt revers; 12s karantene ved prisoverstyring.

**Whipsaw på sekunder:** 12 *ferdig observerte* femsekundersbevegelser (13 komplette femsekundersprøver), ≥7 retningsvekslinger og Efficiency Ratio under 0,35. Først etter tre rolige femsekundersperioder frigjøres whipsaw-sperren.

**Andre begrensninger:** minimum 8 sekunder mellom posisjonsøkninger, men en ugunstig retningsvending kan føre til flat umiddelbart; åpningsforslag blir fylt først på *neste ekte mottatte quote*. Paper-P/L er mid-price merket til markedet, med bid/ask-halvspread samt ytterligere 2 bp på **absolutt eksponeringsendring**. Ingen gearing, margin eller Saxo-lotsimulasjon er modellert: eksponering er normalisert ±1/0/±0,5.

## Seks matchede armer

| Navn | Stoch | MACD i rolig Stoch | Prisoverstyring | Whipsaw |
|---|---|---|---|---|
| STOCH_ONLY | Ja | Nei | Nei | Nei |
| STOCH_MACD | Ja | Ja | Nei | Nei |
| STOCH_PRICE | Ja | Ja | Ja | Nei |
| WHIP_PAUSE | Ja | Ja | Ja | Sperrer nye innganger ved whipsaw |
| WHIP_REDUCE | Ja | Ja | Ja | Setter makseksponering ±0,5 under whipsaw |
| WHIP_FLAT | Ja | Ja | Ja | Setter eksponering null under whipsaw |

Alle armer starter med 10 000 virtuelle NOK på samme tidspunkt, alle handler på samme quote-serie og betaler samme spread/kostnad. Matchet hovedkontroll for whipsaw-effekten er **STOCH_PRICE**. Sammenlikn avkastning, maksimal drawdown, antall transaksjoner, prisoverstyringer, whipsaw-blokkeringer/reduksjoner/flater, databrudd og kostnad.

## Begrensninger og falsifikasjon

- `RefreshRate=1000ms` fra Saxo er ønsket frekvens, ikke garanti om hvert sekund. UI må vise antall reelle observasjoner og siste quote, også når markedet er stengt.
- Normalisert papir-eksekvering via quote BBO er bare en kostnadsproxy og garanterer ikke Saxo-fylling, forsinkelse, likviditet eller mulige minimumstørrelser.
- Alle varianter er sterkt korrelerte, og én kveld er ikke robust nok for optimalisering. WHIPSAW-regler kan hindre gode innganger etter regimebrudd; det er en konkret falsifiseringsrisiko.
- Samme last-quote/timestamp kan ikke behandles to ganger. Posisjoner er ikke aktivert på noen LIVE-motor, og whipsaw er fremdeles ikke en godkjent LIVE-modifikator.
- En eventuell senere intrabar-LIVE-strategi krever særskilt sikkerhetsvurdering av 1s datakvalitet, pending Saxo-ordre, ordregrenser/time, margin og tap.

## Kode og drift

- Capture: `live_sim_hyper_quotes_v1.py`, koblet valgfritt på `saxo_streaming.py`.
- Paper engine: `live_sim_hyper_vigilant_v1.py`, egen 1s research thread i `live_sim_lab_worker_v1.py`.
- UI: Live-Sim Lab → «Hyper-Vigilant Stochastic · sekundsignaler».
- Egen tabell for quotes, features, seks porteføljestater og datapunkter. Eksisterende 72+100-regime/whipsaw/makro-strategier endres ikke.
- Begge laboratoriumstjenester har ingen trading-fullmakt; feil i forskningsopptak blir logget, men skal ikke stoppe den eksisterende Saxo-streamingen.
