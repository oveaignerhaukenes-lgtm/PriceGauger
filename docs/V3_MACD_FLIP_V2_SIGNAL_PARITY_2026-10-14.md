# MACD Flip · V3 — signalparitet og driftskontrakt

Dato: 2026-10-14. PR #714. Ingen LIVE-aktivering.

## Hva er lagt til
- Egen katalogstrategi **MACD Flip · V3** med nøkkel `macd-flip`, runtime `macd-flip-v1`.
- **Ikke** alias til `macd`: eksisterende `MACD Trailing · Legacy` beholder nøyaktig tidligere kode og status.
- Bruker allerede tilgjengelig V3-valg av signalperiode (1m, 2m, 5m, 10m, 15m, 30m, 1h).
- Samme V2-bekreftede MACD 12/26/9-kryss: foregående MACD-spread `<=0` og ny `>0` gir LONG; foregående `>=0` og ny `<0` gir SHORT.
- Intet nytt kryss: behold målposisjon; ingen histogram-slope-trailing eller pyramidering.
- Første beregning etter oppstart/strategiskifte har ingen forrige bekreftede bar og er **HOLD**, ikke automatisk inngang basert på historisk regime.
- Et nytt kryss setter én minste instrumentspesifikke lovlig handelsenhet, **ikke** V3s generelle maksimum på ti trancher. For Tech100 er dette typisk 0,01 lot, men det kontrolleres mot Saxo.
- V3 beholder fullstendig sikker ordrekjede: markeds-/kostnads-/kapitalvalidering, eksklusivt kontoeierskap, durabel intent, presis Saxo-posisjon, reversering `CLOSE → CONFIRM_FLAT → OPEN` og pause ved ukjent pending status. Ingen V2-motor eller V2-konto tas i bruk.

## Hvordan teste
1. Åpne V3 Fleet/TradingDesk og velg **MACD Flip · V3** og ønsket signalperiode. Dette endrer ikke LIVE før en eventuell separat aktivering.
2. Bruk gjerne SIM først og sammenlign mot V2s MACD Flip referanse på samme signallys og tidspunkter. Signalparitet er bekreftet i tester.
3. At historiske kurver er grønne betyr **ikke** at faktisk Saxo-nettoavkastning er bekreftet. Spread, provisjon, latency, slippage og posisjonsstørrelse påvirker resultatet.
4. Før eventuell LIVE-test: bekreft eksplisitt en V3-konto og risiko-/NOK-grense. **Alle LIVE-systemer står OFF inntil brukeren autoriserer endring.**

## Avgrensning
V2 30m/2m/5m-kontrollens signalalgoritme overføres; V2-konto-, ordre- og worker-runtime er **ikke** gjenaktivert. V3 bruker sin egen brokerbekreftede flat-first-sekvens, som kan introdusere utførelsesforsinkelse sammenlignet med V2-historisk mark-to-market.
