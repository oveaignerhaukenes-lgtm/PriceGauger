# V3 AI Manager LIVE – opt-in eksisterende strategi (20.10.2026)

## Hva er tilgjengelig
V3-strategivelgeren inneholder fortsatt alle deterministiske grunnstrategier.
Under **Options / modifiers** ligger nå **AI Loss Manager · LIVE**. Den er én
gjenbrukbar forvalter som kan legges på eksempelvis `MACD Flip · V3` (2m)
eller `MACD Histogram`, uten å endre selve inngangsstrategien.
PreCross#1 og PreCross#2 er *ikke* ferdige strategiimplementasjoner og
vises derfor ikke med oppdiktet LIVE-støtte.

Ingen ekstra godkjenningsknapp trengs. Bruk eksisterende V3-strategivalg,
lagring og LIVE ON/OFF, samt AI Manager-innstillingene i handelskartet.

## LIVE-beslutningsvei
1. Separat AI SHADOW-tråd kontrollerer hvert 30. sekund vedvarende negativ
   verifisert Saxo open P/L. Per-instans utløsertid 15–180s (standard 60s).
2. Teknisk analysemodell ser ferdiglukkede MACD- og Stochastic-data,
   prisobservasjoner, verifisert Saxo-P/L og tidsstemplet kontoverdi.
   Beslutning og nøyaktig evidens lagres i V3 AI audit memory.
3. LIVE-workeren leser **kun** siste beviselig relevant SHADOW-beslutning:
   samme eksakte instans/konto/instrument/strategi/tidsramme/side/volum,
   fortsatt negativ verifisert Saxo open P/L og maksimalt 100 sekunder gammel.
   Modellens confidence må være minst 0.60. Ny HOLD overstyrer eldre FLAT.
4. På en valgt LIVE-modifikator kan AI redusere én 0.01-lot-enhet hvis det
   finnes minst to, eller lukke hele posisjonen ved FLAT eller REVERSE.
   **REVERSE betyr foreløpig FLAT**, ikke en ny motsatt åpning.
   AI kan aldri skape/øke en posisjon; beslutningen går gjennom felles
   V3 målposisjon/risk/execution/Saxo order guard og avstemming.
5. Hvis AI endrer target, justeres det persistente closed-bar-målet også.
   Den nylig fjernede eksponeringen skal dermed ikke automatisk
   gjenoppstå ved poll av samme candle. Ingen live posisjon/strategi
   velges, aktiveres eller omkonfigureres ved merge.

## Observasjon og begrensninger
- Inspeksjonspanel med TradingView Lightweight viser SHADOW-analyse med
  begrunnelse og kontospesifikke V3 execution-markører. En modellvurdering
  er *ikke* synonym med bekreftet Saxo-fill.
- Når en posisjon kun er én minste enhet kan REDUCE ikke representeres i
  0.01-lot-steg og gir HOLD, ikke skjult tvungen FLAT.
- Manglende verifiserbar broker-P/L, stengte markeder, utgått råd eller
  AI-feil gir ingen AI overstyring. Det deterministiske systemet fortsetter.
- Modellkall er begrenset til fire per instans/time og tre minutters
  cooldown, så denne mekanismen er ikke et hardt 60-sekunders stop.
- Før vi hevder at AI øker nettoavkastning, må faktisk Saxo-resultat
  etter kostnader sammenlignes med en identisk strategi uten AI.
- En mer aggressiv v2 med AI-styrt motsatt inngang krever egen
  evaluering av exekvering, modellsvikt, kostnad og whipsaw.
