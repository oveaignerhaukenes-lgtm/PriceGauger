# HyperVigilant Chase 10s · direkte reversering · prospektiv PAPER

## Hypotese
Kan en strategi som bruker *faktiske* Saxo bid/ask-quotes og 10 sekunders
prisimpuls oppnå positiv nettoavkastning ved å følge store bevegelsene
raskere enn 1m MACD/Stochastic, også når den snur **direkte**
fra LONG (+1) til SHORT (-1) uten en egen FLAT-beslutningsperiode?

Dette er en **falsifiserbar hypotese**, ikke en påstand om lønnsomhet.

## Datastrøm
- `lsim_hyper_quotes_1s` eksisterer fra før, generert av Saxos faktisk
  mottatte, ikke-forsinkede, tradable bid/ask på Tech100-UIC.
- Recorder lagrer høyst én ekte quote per sekund. Verken interpolering
  eller nye REST-polls brukes. En hyppighet på 1 Hz er *ikke garantert*.
- Strategilab v2 → **HyperChase · 10s PAPER**. Starter selv etter
  en vellykket deploy via uavhengig 1s-Loop i Live-Sim Lab-worker.
  Ingen avspilling av gamle quotes som om de var prospektive handler.
- Før en beslutning trenger vi minst 9 ekte quotes i de siste
  10 sekundene, inkl. et faktisk 9–10s referansepunkt, maks 3s gap
  mellom observasjoner, gyldig bid/ask og quotealder høyst 5s.
  Manglende signalgrunnlag forblir WAIT / ikke-handel.

## To parallelle varianter
- **CHASE_10S_FAST:** netto 10s-prisbevegelse i ønsket retning, terskel
  minst 4,5 basispunkter, minst 2,5× medianen av observerte absolutte
  quote-avkastninger, og større enn anslått toveis handelsfriksjon.
- **CHASE_10S_FILTERED:** terskel minst 8bp / 4× kortsiktig støy,
  pluss krav om samme prisretning i begge ca. 5s-halvdelene.
- Begge bruker samme ekte Saxo-strøm, samme start-NAV (10 000 PAPER NOK),
  samme bid/ask og gebyrmodell, og kan forbli LONG/SHORT til tydelig
  motsatt 10s-impuls. Ingen kunstig 8s minimum hold eller ventetid.
- Target ±1 normalisert PAPER eksponering (ikke Saxo-lots eller gearing).

## Direkte reversering, men ikke magisk ordre
Et 10s-signal ved quote T legger bare `pending=+1/-1` i
SIM. På den **neste faktisk observerte ferske** bid/ask etter T
endres hypotetisk eksponering fra f.eks. +1 til -1 i én PAPIR-hendelse.
Dette er en reversering med **turnover 2**, ikke en kostnadsfri
netting eller en faktisk Saxo-trade.
- Kostnad: observert halv-bid/ask-spread for begge sider,
  2 basispunkter teoretisk kurtasje per side og
  1 basispunkt teoretisk slippage per side. Alle er basert på
  absolutt endring av normalisert eksponering.
- Eksisterende papirposisjon merkes til faktisk observert mid-price.
  Over datagap flagges verdiendring og utførelseskvalitet; ingen ny
  handel går gjennom gap eller gammel pending-signalinformasjon.
- Tidsforsinkelse fra *registrert signal* til PAPER-fill er målt fra
  faktiske tidsstempler. Den faktiske debut av markedets impuls kan
  ikke tidfestes eksakt med denne metoden.

## Måleplan
Vis begge varianters netto PAPER-prosent, kostnader separat, max DD,
antall fills, direkte flips, quotealder, datagap, signal/fill-latens
og faktiske trade-rader i Strategilab v2. Eksporter JSON og sammenlign
med eksisterende Hyper-Vigilant Stoch på *samme nye markedsperiode*.
Gamle/andre startdatoer er ikke direkte sammenlignbare.

Før vi vurderer LIVE må vi dokumentere at 1s-dataene faktisk kommer
raskt nok til å oppfylle «innen 10s»-ambisjonen. Vi må også verifisere
Saxo-spesifikk direkte nettoreversering, ordrebekreftelse, margin,
slippage, spread, feilrate, ordregrense og tap ved falske utbrudd.
Saxo LIVE-motoren har foreløpig FLAT-før-reversering og er **ikke
endret**. Intet her aktiverer en LIVE-konto, en trigger eller et
automatisk Saxo-ordreforsøk.
