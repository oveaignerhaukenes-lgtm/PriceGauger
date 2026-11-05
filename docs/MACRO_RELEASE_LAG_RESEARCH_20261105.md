# Makroslipp · Lead/Lag observer V1 (PAPER)

**Formål:** Analysere tidsforskjellen mellom faktisk *mottatte* bid/ask-observasjoner fra Saxo for gull, sølv, Tech100 og eventuelt US500 ved NFP/CPI/PPI.

## Fast 2026-plan (BLS)
- Fredag 6. nov. NFP 08.30 US Eastern = 13.30 UTC = **14.30 Oslo**.
- Tirsdag 10. nov. CPI, samme klokkeslett.
- Fredag 13. nov. PPI, samme klokkeslett.
- Opptaksvindu: 180 sekunder før til 900 sekunder etter hvert slipp. Tech100-opptak utenfor dette er uendret.

## Datavei
- Eksisterende Saxo websocket og `HyperQuoteRecorder.observe`: allerede abonnerte instrumenter med begge sider `Tradable` og `DelayedByMinutes=0`.
- Høyst én faktisk observert bid/ask-rad per sekund og UIC i eksisterende `lsim_hyper_quotes_1s`. Ikke syntetiserte ticks, ikke ekstra Saxo REST-kall.
- Andre markeder enn Tech100 registreres kun i makrovinduet. Ingen justering av abonnementslisten. **Manglende Gold/Silver-subscription innebærer ingen lead/lag-konklusjon**.
- Felt: `quote_at` (source observation), `received_at` (PriceGauger receive), `provider_uic`, `market_name`, `asset_type`, `bid`, `ask`.
- UI: **Analyse → Makroslipp · Markedsreaksjon og etterslep**, `pages/0_Macro_Release_Lag.py`. Autorefresh mens siden er åpen i opptaksvindu. Opptak pågår på stream-worker selv om siden er lukket.

## Analyse
- Referanse siste faktisk mottatte quote *før* slippet og høyst 10 sekunder gammel.
- Første signifikante terskelbrudd etter slippet, målt i sekunder fra `received_at`; standard minimum 5bp eller 2× løpende spread (det største).
- Hver UIC analyseres isolert. Rapporten velger høyeste datadekning for samme markedsgruppe, men alle UICs bevares i JSON.
- Gap gjennom slippet >6 sekunder eller manglende referanse markerer `GAP_OR_MISSING_BASELINE`; i så fall publiseres **ikke** et pålitelig første-reaksjonstidsstempel.
- 1/2/5/10/20/30/60/120/300/600s avkastning fra pre-release mid, bare hvis quote ble mottatt 0–2,5s etter det aktuelle tidspunktet. Ingen fylling av mellomliggende sekunder.
- Utforskende PAPER: første gullsignal ved terskelpassering; retning kopieres til Tech100 etter antatt 1/3/5/10s ekstra latency, kjøp på ask/selg på bid, exit etter 10/30/60/120/300s. Bare cross-spread proxy, ikke Saxo fills, gebyrer, ekstra slippage eller garantert fill.

## LIVE-feed verifikasjon 5. november 2026
- Railway `PriceGauger-stream` bekreftet ekte prisstrøm på Tech100 UIC 4912 (`DelayedByMinutes=0`, `Tradable`).
- Saxo InfoPrice-diagnostikk for nåværende Gold UIC 50511697 og Silver UIC 46652614 viser `DelayedByMinutes=10`, `OldIndicative`. Disse kan IKKE brukes som tidlige realtime-signaler. Oppsettet vil derfor rapportere manglende gull/sølv-dekning med mindre tilgang til ekte udelt, tradable BBO etableres før slippet. Observasjonsmodulen skal aldri bruke eldre priser for å fylle et slikt hull.

## Begrensninger før LIVE
1. Vi fanger maks 1Hz, ikke millisekundrekkefølge; 1s datapunkt er ikke hele ordreboken.
2. Kilden mottar pris på Saxo CFD-ene, ikke nødvendigvis futures. Forskjeller kan skyldes leverandørfeed, instrument eller spread.
3. Ulike markeder har ulike volatilitet/spreader. Forskjell i 5bp terskeltid er ikke nødvendigvis kausal lag.
4. Positive enkelthendelser gir ikke statistisk sikkerhet. Test på mange publiseringer, med uendrede terskler og uavhengig holdout.
5. Ingen LIVE-order, gearing, risikomodifikasjon, per-konto endring eller automatisk aktivering inngår.

Kilde til kalender: https://www.bls.gov/schedule/2026/11_sched.htm
