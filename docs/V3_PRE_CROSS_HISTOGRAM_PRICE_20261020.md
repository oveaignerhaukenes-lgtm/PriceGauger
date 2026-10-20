# V3 mekaniske prisbekreftede MACD-strategier (20.10.2026)

To nye **reelle deterministiske V3-strategier** som er registrert
direkte i LIVE-valgene, med normal lagring/LIVE-bryter og vanlig
Saxo-instrumentstørrelse, risikopolicy, bekreftet FLAT-før-reversering
og ordre-/pending-reconciliation. Ingen konto eller posisjon skrus på i deploy.

## 1. PreCross#1 · MACD 2m + Pris 1m
- V3 signalperiode **1m**; 2m MACD 12/26/9 bygges fra hele ferdiglukkede
  kanoniske 1m-candles uten interpolerte manglende minutter.
- Ser ikke primært etter nullkrysset: *endringen i histogrammet* er
  retningen. Negativ slopesignal mens histogrammet fortsatt er positivt
  kan varsle SHORT før bearish MACD-kryss; symmetrisk LONG.
- Inngang bare med **ny prisbreakout på siste ferdige 1m-candle**:
  sluttkurs over de tre tidligere høye nivåene / under de tre tidligere
  lave nivåene, i samme retning som histogramslope, med body relativ til
  de seneste candle-range og 1,5 basispunkter.
- Histogramkontraksjon/parallell posisjon eller motsatt prisbrudd fører
  til **FLAT**, og nytt motsatt signal kan først åpnes gjennom vanlig
  V3 Saxo-bekreftet flat-first på senere syklus.
- Én minste Saxo-enhet, ingen pyramidering.

## 2. Histogram + Price · MACD 2m / Pris 1m
- Samme ferdiglukkede datagrunnlag og histogramdelta.
- Tidligere inngang enn PreCross#1 mulig ved **to påfølgende 1m-prislukk**
  i histogramdeltaets retning + tilstrekkelig siste candle-body.
- Motsatt histogramdelta eller tilnærmet parallell MACD fører til FLAT.
- Ingen åpning i prisretning alene; retningen må sammenfalle med MACD
  histogramslope. Ingen direkte +/- flip.

## Kvalitetsgrenser
- Det finnes ennå ikke verifisert 10/30-sekunders historikk med tilstrekkelig
  tids-/markedskvalitet. Disse to er derfor **ærlige 1m/2m-prototyper**;
  de kan ikke forventes å fange de aller raskeste subminutt-vendingene.
- Ingen tilgang til Saxo er implementert i strategiobjektene.
  Handelsutførelse skjer utelukkende gjennom eksisterende V3-ordremotor.
- Ufullstendig 1m-/2m-evidens resulterer i FLAT, aldri en prisprognose
  eller implisitt gjenbruk av gamle indikatorer.
- Normalisering og terskler (10 % median MACD-endring,
  35 % av nylig candle-range og 1,5bp) er **provisoriske hypoteser**,
  ikke avledet fra målt forventet avkastning.
- AI Loss Manager er uavhengig og kan eventuelt brukes som modifikator.
  Kombinasjoner må evalueres mot mekanisk baseline og Saxo netto-P/L.
- Ingen garantert fordel mot MACD Flip. Før større kapitalallokering:
  dokumenter tidsstemplede faktiske innganger, spread/slippage og avkastning
  for identisk konto/regime over flere ulike markedsdager.

## Hvordan velge
I Fleet / TradingDesk: `Administrer instansen` →
`Strategi / AI-oppsett (LIVE)` → `PreCross#1 · MACD 2m + Pris 1m`
eller `Histogram + Price · MACD 2m / Pris 1m`. Signalperiode blir 1m
automatisk i utkastet. Lagre med `Bruk på denne instansen`.
Bruk ordinær LIVE ON/OFF; ingen ekstra per-strategi godkjenning.
