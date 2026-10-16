# Sykluslaboratorium v1 — separat forskning, ingen ny handelsstrategi

Dato: 2026-10-16. Uavhengig av PR #726 (Markedsrytme) og PR #729 (Fraktal#1).
Denne PR-en kan merges alene mot main; den berører **ikke** LIVE-strategier,
V3 execution/arming, Saxo OpenAPI, eller eksisterende databaser.

## Hva som faktisk bygges

Eget **Analyse → Sykluslaboratorium** med tre enkle observasjoner:

1. **Wavelet-inspirert tidsfrekvenskart** (4/6/8/12/16/24/32/48/64 minutter).
   Lyse felt: økt signalstyrke fra en **ensidig, historikkbasert, kompleks
   Morlet-lignende filterbank** av logaritmiske 1m-avkastninger.
   Ikke en eksakt symmetrisk CWT; derfor heller ingen lookahead.
2. **Uavhengig syklus-kryssjekk** med autokorrelasjon av avkastning ved de
   samme lagene. Inspirert av Ehlers' generelle syklustenkning, men **ikke**
   et forsøk på å implementere nøyaktig John Ehlers' MESA/Hilbert/HT_DCPERIOD.
3. **Bekreftede topper og bunner** fra eksisterende
   `autotrader_market_rhythm_v1.py` ved minimum 0.10% motsving. Tooltip
   skiller historisk pivot fra senere `confirmed_at`.

Et kompakt øyeblikksfelt viser sterkeste rytme om kontrasten mot median
er tilstrekkelig (1.35x), resultat av korrelasjonssjekk (min 0.25),
og antall bekreftede vendepunkter. Ellers står det "ukjent".
Ingen prediksjon av neste pivot eller ordrehint.

## Begrensninger

- Minste 4-minutters kandidat: en 2-minutters syklus er på Nyquist-grensen
  for 1m data og kan ikke måles robust uten subminutt-data.
- Ingen imputering av hull. Analysen avgrenser til siste sammenhengende
  1m-session. Markedsstengt / foreldet feed vises eksplisitt.
- Krever minst 3 perioder per filter før den viser verdi; ACF krever 4
  hele maksimumsperioder. Verdier ved tidspunkt t bruker ikke priser etter t.
- En ensidig kompleks filterbank er tidsforsinket og ikke et «fasenå»-signal.
  Spektraltoppen og korrelasjonsmaksimum kan fremkomme i tilfeldig støy.
- Ingen FRAMA, Hurst, MF-DFA, fasehjul, rekursiv mønstergenerator eller
  automatisk strategi-match i denne PR-en. Vi holder antall bevegelige
  deler nede, særlig i lys av tidligere uheldige komplekse taktikker.
- Effekt på faktisk nettoavkastning er **ikke påvist**. En fristende
  waveletperiode er ikke en handelsregel.

## Kontrollkrav til arkitekt

- [ ] Page inkluderer bare eksisterende subscribed canonical
  `instrument_id`; instrumenter blandes ikke.
- [ ] Kun ferdig lukket 1m med 10s sikkerhetsmargin; refresh hvert 60s.
- [ ] Ingen strategi-parametere, LIVE/SIM-state, databasedata eller Saxo endres.
- [ ] Tidligere waveletceller er identiske etter at senere priser legges til.
- [ ] Hull bryter tidsserien; ingen kunstige sykluser på tvers av helgen.
- [ ] Konstant pris gir «ukjent», ikke falskt dominant markedssignal.
- [ ] Begge metoder vises **som forskjellige målinger**, aldri som en
  lønnsomhetsscore eller en prediktiv AI.
- [ ] UI enkel på mobil: én underliggende, 2 grafer og forklaringsfelt.
- [ ] CI grønn; ingen post-merge automatisk LIVE activation.

## Veien videre (ikke del av PR)

Før en regimeindikator blir strategiinndata, må vi måle dens faktisk
ekstra prediktive verdi mot enkle baselines (f.eks. momentum/MACD,
directional-change og lag-correlation uten wavelets). Bruk tidskausale
as-of snapshots, kronologisk holdout, regimeendringer, datagaps og
netto brokerkostnader. Om effekten ikke er tydelig **forkaster vi den**
eller beholder den som rent visualiseringsverktøy.

Denne PR-en er med hensikt en sidevei til observasjon, ikke enda en
komplisert motor som risikerer levende konti.
