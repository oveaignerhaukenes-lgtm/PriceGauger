# Live-Sim Whipsaw Lab — kontrollert politikkstudie (12. oktober 2026)

## Problemobservasjon

I LIVE 12. oktober ble flere 2m-motorer sittende LONG under et etterfølgende fall, mens 5m-motoren flippet hyppig i en trang konsolidering. Dette kan gi tap både gjennom uheldig posisjonsretning og ved hyppig omsetning. **Dette er ikke bevis for at detektoren mislyktes:** V3-katalogens `whipsaw`-modifikator er ikke LIVE-ready; kun `reset-on-loss` er implementert som LIVE-modifikator.

Den eksisterende Live-Sim-detektoren (`live_sim_lab_core_v1.technical_regime`) analyserer de 12 siste 1m-returene og gir `WHIPSAW` når det er minst 7 fortegnsskifter og efficiency ratio <0,35. Forsøket gjenbruker akkurat denne klassifiseringen fra lukkede barer. Ingen separat konkurrerende Chop-detektor er innført.

## Fire forward-only PAPER-armer (fem frosne kontrollstrategier)

- **BASE:** helt opprinnelig modell, kontroll.
- **PAUSE:** sperrer nye posisjoner og pyramidering så lenge whipsaw er aktiv; tillater reduksjon/lukking. Motsatt retning må først gå flat.
- **REDUCE:** blokkerer nye innganger under whipsaw og begrenser eksisterende posisjon til maks 50 % av strategiens nominelle eksponering; tillater ytterligere signalstyrt nedskalering og lukking.
- **FLAT:** setter målposisjon null under bekreftet whipsaw, og krever tre påfølgende rolige ferdigstilte barer for re-entry. Ingen revers på samme beslutningsbar.

Detektoren aktiverer umiddelbart ved et ferdig bar-signal og bruker 3-bar hysterese etter siste whipsaw-bar. Ingen fremtidige barer undersøkes ved en beslutning. Alle fire armer får samme utgangspunkt, samme signal fra parent-strategi, samme closed-bar-timeframe og samme 5 bp turnover-kostnad. Ordre simuleres ved **neste baråpning**, ikke retroaktivt. Ingen eksisterende historiske handler gis fiktive forbedringer. Reboot / gjenkjøring av samme bar er idempotent.

Kohorten på fem fryses bare én gang fra uendrede `modifier=none`-strategier med minst 120 prospektive barer, 25 femminuttsprøver og 2 papirhandler, rangert ved allerede observert nylig avkastning. Den rullerer aldri automatisk som følge av utfallet. De 20 parallellbanene er sidecars og tar ikke plasser i den allerede definerte grensen på 100 aktive LAB-varianter.

## Observasjon, kontroll og falsifikasjon

Vis antall observerte barer, antall rå og effektive whipsaw-barer, P/L med identisk kostnad, maksimal drawdown, antall handler, omsetningskostnader, stoppede økninger, tvungne reduksjoner og flater, og differanse mot *sin egen* BASE. En variant er ikke bedre før den viser lavere netto drawdown/tap i choppy perioder, uten større underprestasjon i trend og med tilstrekkelig hendelsesdekning.

De 20 resultatkurvene er **ikke** 20 uavhengige handelsidéer; fem grunnstrategier og tre modifikatorer skaper betydelig korrelasjon. En enkelt kveld kan gi et nyttig analyseeksempel, men ikke evidens for robust regimekunnskap. Effekten av karantene og avkobling fra etablerte trender må analyseres prospektivt over mange sesjoner.

## Sikkerhet og begrensninger

Denne studien endrer **ikke** V3-konfigurasjoner, LIVE-motorer, account binding, avstemmingslogikk eller Saxo-ordrer. `LIVE_MODIFIERS_V3` er fortsatt kun `reset-on-loss`. Selv om whipsaw er synlig i UI-katalogen skal det ikke påstås at den beskytter LIVE. LAB-proxy P/L er normalisert papirkapital, ikke reell Saxo CFD-P/L.

Hvis studien er lovende, trengs separat validering og eksplisitt godkjent, sikker LIVE-implementasjon før eventuell aktivering.
