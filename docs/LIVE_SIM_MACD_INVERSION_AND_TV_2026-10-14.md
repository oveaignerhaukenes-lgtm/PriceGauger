# MACD inversjonstest og TradingView-navigasjon · 2026-10-14

## Metode og mål

Brukeren observerte at regelbaserte MACD-strategier ofte taper selv om signaler inverteres. Dette panelet tester dette kausalt mot **like tidsvinduer, beholdningsperioder, inngangsøyeblikk og kostnadsmodell**.

Nytt `Inversjonstest · MACD` i Live-Sim Lab sammenligner:
1. MACD Flip original (MACD-histogram krysser 0).
2. MACD Flip invertert.
3. Histogram Peak Flip original (eksisterende V3-policy).
4. Histogram Peak Flip invertert.
5. 10/30/100 seedede tilfeldig valgte retninger på nøyaktig samme beslutningstidspunkter; kostnadsbelastning er lik **originalt absolutt turnover** og er bare en statistisk placebo.

Målene er nettoretur, bruttoretur, estimert kostnadsdrag, maksimal DD, antall reverseringsbeslutninger og omsatte legs. Bruker velger fast signal-TF (5/15m), kostnad (bps/side), notional/NAV, utvalg og prøveantall. Tradelogikken bruker de eksisterende MACD-observasjonene fra `macd_nextgen_paper_v1._observations` og eksisterende `histogram_peak_flip_transition_v3`, med indikatorwarmup og kun ferdige signallys; fills først på neste tilgjengelige autentiske 1m-åpning. Motposisjon på samme signal får samme nominelle inngangs-/utgangstid.

**Begrensninger:** Ingen Saxo-markedskurser, reelle fills, full CLOSE→FLAT→OPEN-latency, overnight financing, valutaveksling, per-kontraktgearing, spread på faktisk bid/ask eller ordrebekreftelser er regnet inn. Dette er signalinferens, ikke en gyldig prognose av kontoavkastning. Random placebo på identisk opprinnelig turnout er med vilje ikke en direkte handlebar policy.

## Ekstern hurtigtest (separat fra PriceGaugers egen Tech100-feed)

Kilde: `getdata-finance/nas100-5m-ohlcv-index-historical-data`, fil `NAS100_5m.csv`, 36 133 femminuttersbars, 2026-03-26 til 2026-09-25. Testen er gjort mot **5m OHLC**; 15m-signaler bygges av komplette 3×5m-bøtter, og ideelle handler ved neste 5m-open (ikke neste kanoniske 1m-open). MACD 12/26/9, 1× indeksnotional, 1 bp/handlet side. Forbehold om dataenes kvalitet, annen pris- og børsfeed og uten reell Saxo-eksekvering.

| Signal | Brutto original | Brutto invertert | Netto original | Netto invertert | Posisjonsskifter |
| --- | ---: | ---: | ---: | ---: | ---: |
| MACD Flip 5m | +4,82 % | −6,71 % | −40,23 % | −46,81 % | 2 809 |
| Histogram Peak Flip 5m | −17,12 % | +17,98 % | −78,99 % | −70,10 % | 6 863 |
| MACD Flip 15m | −5,41 % | +3,39 % | −20,57 % | −13,19 % | 875 |
| Histogram Peak Flip 15m | +2,82 % | −4,89 % | −34,50 % | −39,41 % | 2 255 |

**Tolkning:** Inversjon kan snu tegn på bruttoavkastningen, men ekstrem turnover skaper netto negativ forventning selv ved 1 bp kostnad per handlet leg. Dette kan ikke generaliseres til nåværende Saxo Tech100 LIVE eller bruke i stedet for nåværende V3-/AEn-reality audit. Test på ekte kanonisk prisfeed og fremoverskuende holdout er neste steg.

## UI-endringer

Alle testpanelene i `Live-Sim Lab` har nå felles TradingView Lightweight Charts v5:
- tidsknapper 1t/4t/1d/3d/7d/Alt, mouse drag-pan, wheel zoom, mobil pinch, price/time axis scaling, crosshair og individuell strategi-legende;
- persistert **per-panel** zoom/logical range ved Streamlit-reruns, med tilgang til «↺» reset;
- justerbar grafhøyde; ekte AEn OHLC-candles med indikatorfri PAPER-fill-overlay;
- aktive AEn Forward-cohorts som primærgraf; PAUSED_REVISION/arkiv for seg.

Alle strategier, LIVE-ordrer, arming, V2/V3-workere og prisinnsamling er uendret. Endringen er kun forskningsvisning og validering av hypotese.
