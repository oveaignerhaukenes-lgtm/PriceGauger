# Live-Sim Lab v2 — Shadow Selector og evolusjonskø

**Type:** Research-only. Ingen LIVE-autoritet, Saxo-ordrer eller endringer i aktive motorer.

## Shadow Selector

Tre uavhengige forward-paper-porteføljer: RECENT (nettoavkastning siste 2–6 timer, drawdown-straff), REGIME (tidligere observert nettoavkastning i det nåværende tekniske regimet) og HYBRID. Krever minst 25 femminuttsobservasjoner og to virtuelle handler; regimevariantene krever i tillegg minst 60 regime-barer.

Alle beslutninger tas etter ferdig 1m-bar; target eksponering fylles først ved neste baråpning. Papirporteføljene belastes 5 basispunkter per eksponeringsendring og 7 basispunkter ekstra ved bytte. Bytte krever minst 0,15 prosentpoeng skårforbedring og enten negativ rullerende avkastning hos incumbent eller en tydelig 0,50 pp forbedring. 60 minutters cooldown og maksimalt åtte bytter per UTC-dag. Ingen LIVE-autoritet.

## Evolusjon og historikk

Startkohort: 72 LAB-native MACD-varianter. Global aktivtaksgrense: 100.

Søkegitter: 252 unike konfigurasjoner, bestående av 2 strategifamilier, 3 signalperioder (2/5/10m), 3 regimer (10/15/30m), 7 modifikatorer og 2 eksponeringsnivåer. Fire nye, implementerte kausale modifikatorer: trend_only, volatility_pause, momentum_confirm og adverse_exit. Hver config har varig ID og status QUEUED / RUNNING / RETIRED, parent-ID, tidspunkt og bevarte utfall.

Pensjonering er streng: minst 1200 prospektive barer, minst 8 papirhandler, minst to regimer med ≥120 barer hver, aldri NAV > 10000, ingen positiv netto regimescore, samt tre separate kontroller ≥60 minutter fra hverandre. Pensjonerte ID-er aktiveres aldri på nytt ved reboot.

Etter minst 240 observasjoner kan opptil fire ledige plasser fylles hver time, prioritert fra beste dokumenterte foreldrekontroller. Nye kandidater får aldri retroaktiv P/L. Opprettelse, pensjonering, posisjonstilstand og cursor behandles i samme transaksjon.

Dashboard viser selector-NAV, kostnader, bytter, valgt/ventende modell og full forsøkskø inkludert tapsårsaker for avsluttede eksperimenter.

## Hypotese og forbehold

En strategi som har positiv avkastning i 90 % av barene kan likevel tape samlet hvis de siste 10 % inneholder store tap. Winner selection blant 100 korrelerte varianter medfører vesentlig overtilpasningsrisiko. Før LIVE-aktivering kreves out-of-sample evaluering, kostnader, drawdown, bootstrap-usikkerhet og sammenligning mot fast MACD 5m flip.

Dette er et begrenset søk over **implementerte** varianter. Nye AI-foreslåtte strategifamilier kan senere bli lagt inn etter egen kodeimplementasjon, versjonering og validering. Laboratorieprototypene er ikke bit-identiske med produksjonsstrategier; alle P/L-tall er normalisert papirkapital, ikke faktisk Saxo CFD-resultat.
