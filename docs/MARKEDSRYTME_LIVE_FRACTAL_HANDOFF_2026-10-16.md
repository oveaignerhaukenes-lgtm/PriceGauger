# Markedsrytme: live observatorium + iterativ fraktal forskningskontrakt

Dato: 16. oktober 2026. Opphavsidé: mål markedets rytme som amplitude × tid × stabilitet × hastighet, ikke bare `CHOPPY`/TREND. **Denne PR-en er lesende analyse, ingen LIVE-ordre eller strategimutasjon.**

## Mergebar leveranse i denne PR-en

- Hovedmeny **Markedsrytme** med egen Streamlit-side `pages/0_Markedsrytme.py`, plassert ved TradingDesk/Live Chart.
- Valg av konkret Saxo-instrument fra eksisterende subscribed sources (eksakt instrument_id; ingen name-only joins).
- Kanoniske **ferdiglukkede 1m-kurser**, ikke uferdig candle, historikk 6t/24t/7d; fragment poll hvert 30 s, database-lesing cachet 24 s.
- Varsel når siste datapunkt er over 3 minutter gammelt. Kan skyldes markedspause; alarm er **dataalder**, ikke dokumentert Saxo-feil.
- Toppkort: median halv-/helsyklus, swingamplitude, vendinger per observert markedstime, siste bekreftede topp/bunn, deteksjonsforsinkelse, syklusregelmessighet (CV), antall komplette sykluser.
- Visuelt: prisgraf med historiske swingmarkører og eksplisitt `confirmed_at` hover; gruppert syklusvarighetsdiagram; heatmap amplitude × varighet; varighet/amplitude og opp/ned-hastighetsdiagram; fraktal hierarki-plot over seks terskler; krysskala-sammenfall; siste bekreftede turn- og leg-tabeller.
- Eksisterende `autotrader_market_rhythm_v1.py` fra #724 beholdes som autoritativ turning-point detector. Visninger i `market_rhythm_dashboard_v1.py` er rene funksjoner.
- Ingen nye databasetabeller, ingen Saxo-order-API, ingen ekstra rådatainnsamling og ingen ny LIVE-authority.

## Tidsmodell (kritisk)

Et faktisk pivot kl. 12:00 er ikke kjent før prisen har beveget seg minst terskelen *motsatt vei*, f.eks. kl. 12:03.
`pivot_at=12:00` er en **retrospektiv visualisering**, mens `confirmed_at=12:03` er første mulige beslutningstid. En fylling kan tidligst skje **etter** det tidspunktet og videre validert markeds-/broker-latens.

Vi må ikke bruke siste komplette graf eller perfekt framtidig syklus til å instruere en tidligere handel. Panelenes pivot- og syklusbaserte statistikk er retrospektiv, ikke et pålitelig realtids-faseestimat.

**Dynamisk underliggende prosent** er ikke gearet kontonavkastning; kontoresultater må analyseres separat mot Saxo-fills og kostnader.

Hvert terskelnivå har sine egne fullførte legs/sykler. En og samme prisbevegelse kan opptre ved flere terskler; derfor heatmap teller bare minste terskel, ikke alle lag kumulativt.

## Forskningshypotesen: iterativ fraktal, uten antatt edge

Et mulig generativt marked kan ha nestede strukturserier, hvor mikro (1–2m), meso (5–15m) og makro (30m–4h+) samvarierer via risikosentiment og ordreflow. **Det er en hypotese**, ikke et påvist fraktalt mønster, og «håp/frykt» er ikke observert data. Selvlikhet kan være skalaavhengig og endres ved events/lav likviditet.

Foreslåtte forklaringsvariabler for hver skala s og tidspunkt t:

1. `as_of(t)`: sist bekreftet PEAK/TROUGH; current close og tidsstempel; ingen skjult framtid.
2. `amp_s`: median og spredning i ferdigbekreftet swingamplitude.
3. `period_s`: median og CV for fullførte halv- og helsykluser.
4. `velocity_s`: retning, fart (%/min) og historisk akselerasjon på **bekreftede** legs.
5. `directional_drift_s`: netto prisbevegelse / absolutt prisvandring, per skala.
6. `relative_position_s`: nåværende pris relativt siste bekreftede pivot og sist bekreftede swingrange (ikke «ekte fase»).
7. `cross_scale_lag`: observasjonstid mellom tidligere bekreftet mikrovending og senere bekreftet makrovending, ikke årsaksforklaring.

### Iterativ forskning i separat PAPER-lab (IKKE del av denne PR-en)

A. Lag først **frosset as-seen snapshot** ved hvert nytt ferdige 1m-lys, med input/data-versjon og `confirmed_at`. Først en beskrivende feature-profil.

B. På hver skala, estimer neste mulige retnings-/svingutfall **probabilistisk**, med nullmodell som konstant retning, momentum, tilfeldig vendetid og ordinær MACD Flip. Noe kan være uforutsigbart; modellen må tillate `UNKNOWN`.

C. Iterativ conditioning: mål om `macro(t)` gir ekstra prediktiv verdi til `meso(t)`, og denne igjen til `micro(t)`. Bruk bare foreliggende makroregimer og manglende-data-flagg. Sammenlign mot enkel baseline og uten makrokontekst (ablation).

D. Tren/test i kronologiske walk-forward-vinduer med purge/embargo rundt overlappende bekreftelsesvinduer; frys parameterne før testintervallet. Ingen beste kurve valgt i ettertid som bevis.

E. Beregn **faktisk fangeandel**, signal-latens, turnover, drift, kostnader, broker spread/slippage/funding, maksimal DD og tapstail. Kombiner med fremtidig Strategy Performance Journal som gir eksakt frozen config/Saxo-fill-P/L per aktiveringsperiode.

F. Bare hvis nettoeffekten generaliserer på flere instrumenter/sesjoner: foreslå anbefalinger i read-only; senere egen opt-in PAPER og til slutt separat LIVE-autorisert adapter gjennom V3-kjedens CLOSE→bekreftet FLAT→OPEN.

### Lengre skalaer

Langtidsnivå på uker/år krever separat justert dag/uke-kilde, sesjon-/roll-/splitkontroll og eksplisitt kvalitetsproveniens. Den eksisterende 1m-serien gir **ikke** grunnlag for å hevde års-rytmer. Ikke innfør uhåndterlig lagring før Postgres-retensjon og backup er avklart.

## Review/test-sjekkliste til arkitekt

- [ ] Navigasjon viser Markedsrytme uten duplikat/default-overstyring, også mobil.
- [ ] Bytt marked: nøyaktig provider-instrument, ingen blanding mellom kontoer/UIC.
- [ ] Auto-refresh etter 30s oppdaterer nye **ferdige** candles; gammel feed varsles.
- [ ] Test symbolikk: pivot ved 12:00, confirm 12:03, aldri inverse tidsrekkefølge.
- [ ] Ufullstendige tidsserier og markedsstengt gap gir ingen oppdiktede korte sykler.
- [ ] Heatmap teller minsteterskel én gang; legendserier kan dobbelttelle *definisjoner* eksplisitt.
- [ ] 0–få sykluser gir `ukjent`, ikke falsk «perfekt rytme».
- [ ] CI gjennomført; fremtidige UI-endringer krever mobilskjermkontroll.
- [ ] Ingen koblinger fra siden til `set_live_enabled`, `place_order`, strategi-bytte eller nye DB-write-kjeder.

Kilder i repo: `autotrader_market_rhythm_v1.py`, `docs/MARKET_RHYTHM_PROFILE_2026-10-16.md`, `canonical_market_bars_v2.py`, `autotrader_strategy_scoreboard_v1.py`.
