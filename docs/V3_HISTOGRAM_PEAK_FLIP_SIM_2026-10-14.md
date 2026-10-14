# Histogram Peak Flip · V3 (SIM + LIVE)

**Dato:** 2026-10-14 · **Status:** V3-strategi tilgjengelig i SIM og LIVE. Verken LIVE-motorer eller Saxo-posisjoner aktiveres/endras ved kodeutrulling.

## Strategiregler (lukket MACD 12/26/9 histogram)

**Negativt histogram**
1. Histogrammet stiger mens forrige verdi var negativ (eksempel: −5 → −4) ⇒ mål **LONG én minste instrumentspesifikke enhet**.
2. Fortsetter histogrammet å stige, hold LONG og oppdater forrige topp.
3. Hvis histogrammet begynner å falle igjen mens det er negativt (−3 → −4), sett mål **SHORT én enhet**. Frys siste registrerte topp (−3).
4. Hold SHORT til et ferdig histogram bryter **strengt over** frosset topp (−2,8 > −3), deretter LONG igjen. Likhet (−3 = −3) er ikke nok.

**Positivt histogram – speilvendt**
1. Histogrammet faller mens forrige verdi var positiv (+5 → +4) ⇒ **SHORT én enhet**.
2. Fortsett SHORT mens histogrammet avtar og oppdater siste bunn.
3. Nytt positivt push (+3 → +4) ⇒ **LONG én enhet**, frys siste bunn (+3).
4. Hold LONG til histogrammet er **strengt under** denne bunnen (+2,8 < +3); bytt tilbake til SHORT.

Ved overgang mellom negative/positive histogramregimer gjelder samme symmetriske regler; en ny primær positiv kjøling/negativ recovery starter motsatt signal. Ved første candle etter oppstart eller bytte: HOLD og vent på komplett sammenligningspar. Uendret histogram gir HOLD.

## Avgrensning
- Ingen pyramidering, trailing, ekstra indikatorer, AI eller volumbetingelser. Maks **én Saxo-lovlig tranche**, typisk 0,01 lot på Tech100, men instrumentet bestemmer faktisk minstekvantum.
- Hver beslutning krever ferdig signallys. Minnet om topp/bunn persisteres atomisk med V3s candle-cursor og målposisjon. Duplikater og omstarter gir ingen ny signalevaluering.
- Ekstern posisjonskorreksjon fra risiko/broker sletter tidligere låste peak/trough-minner og tvinger en ny bootstrap, slik at det ikke oppstår uønsket re-entry.
- Den nye strategien ligger i V3 som **Histogram Peak Flip · V3**, tilgjengelig i SIM og LIVE. V3 LIVE-capability godtar Manuell/faste tidsrammer; `live_route_enabled=True`. Ingen eksisterende LIVE-konfigurasjon eller arming er endret. Ordreutførelse følger V3s sikkerhetsporter og bekreftet FLAT før motsatt side.
- Den eksisterende **MACD Histogram**, **Histogram Flip+Build** og **MACD Flip** påvirkes ikke.
- Dette er en hypotese, ikke dokumentert nettoavkastning. Reverseringer og spread/kurtasje må måles mot eksisterende histogramvarianter i samme datasett før LIVE eventuelt vurderes.

## Neste evalueringsfase
Sammenlign Peak Flip mot Histogram og Histogram Flip+Build med like candles, én enhet, spread/avgifter og samme lukket-bar-simulering. Se på antall reverseringer, netto-P/L, gevinst gitt tilbake fra maksimal urealiserte gevinst og max drawdown. Ingen automatisk LIVE-aktivering ved deploy eller endring av eksisterende instanser. LIVE innebærer fortsatt risiko for tap, særlig ved mange reverseringer og latency.
