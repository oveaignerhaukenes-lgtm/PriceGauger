# Strategilab v2 – nytt isolert forskningsarbeidsområde

## Navigasjon
Analyse → **Strategilab v2**. Gamle Strategy Lab og Live-Sim Lab er beholdt som
egne sider inntil v2 er verifisert. Ny lab har fanene
**Historisk SIM / Strategier** og **Kontoprestasjon**.

### Historisk SIM
1. Åpne kollapsbare familier; alle offisielle V3-strategier listes med navn
   og beskrivelse. Flervalg for de faktisk kausalt replay-klare strategiene.
   **18 rene V3-mekanikker**: MACD Flip, MACD Trailing,
   MACD Histogram/Flip+Build/Peak Flip, MACD+Stoch v1/v2/v2.1,
   Rytmebygg v1, PreCross#1, Histogram+Price, VWAP-regime,
   MACD R/S, AEn#2/2.1 sticky, RytmeTrend og begge fraktalrytmevariantene. De øvrige ligger synlig under sin familie som
   **Ikke replay-klar**, inkludert AEn-kjernestrategier som benytter varig
   tilstand. Vi fabrikerer aldri replay-resultater for disse.
2. Velg marked, eksakt produkt/UIC blant **Saxo-abonnerte og kanonisk innsamlede**
   instrumenter. Historisk data hentes direkte fra eksakt `instrument_id` i
   `pg_v2_market_bars_1m`, aldri ved navn fra et annet instrument.
3. Velg klokke, UTC-dato og periode; flere strategier replayes på samme
   råhistorikk med samme kostnadsprofil.
4. Velg kostnader:
   - **Saxo-kalibrert:** read-only Saxo infoPrice, instrument details,
     USDNOK/EURNOK spot-kryss og cost illustration på eksakt kontokey, UIC og
     asset type. Alle deler kreves for dette alternativet; man bruker nåværende
     indikativt spread/kurtasje på historiske barer. Det er ikke arkivert BBO.
   - **Manuelt scenario:** egne eksplisitte NOK/point, spread-bps, variabel
     kommisjon bps og fast NOK/ordre. All statistikk merkes MANUAL_SCENARIO.
     UI-modusen må testes med eksakt likhet: teksten «ikke Saxo-verifisert»
     inneholder også «Saxo», og en substring-test valgte tidligere feil panel.
   - Manglende Saxo-pris, valutakurs, kontraktstørrelse, gebyr eller
     handelsinkrement listes ved navn; en generell sperremelding er ikke nok.
   - V3-strategiens `tranche`/Saxo step, max lots og startkapital er synlige;
     ingen kontoordre eller precheck utføres i denne forskningssiden.
5. PAPER fills på **neste faktiske 1m OPEN etter ferdig beslutningsbar**.
   Ved reversering må gammel side lukkes før senere motsatt PAPER-åpning
   (minste én separat candle). Ingen samme-tidspunkt cross/net orders.
   Kostnader belastes per gjennomført posisjonsendring. Ingen posisjoner
   eller ventende signaler får gi gevinst gjennom 1m-hull; langvarige hull
   nullstiller MACD og stenger siste registrerte posisjon til sist
   observerte kurs, med simulert handelsgebyr. Dette er en konservativ
   forskningsantakelse, ikke en dokumentert realisert Saxo-fill.
6. Handelsmarkører, TradingView Lightweight PAPER-kurver, spoling per
   ferdig 1m-observasjon, direkte hopp til en handelsevent, teknisk
   beslutningsbegrunnelse, og komplett maskinlesbar JSON/CSV-eksport
   slik at brukeren kan **laste opp filen i ChatGPT** for analyse.
   Et klikk i Lightweight-kursgrafen velger ferdiglukkede 1m-priser og flytter
   spolemarkøren. Brukeren kan vise hele historien for navigasjon eller
   skjule framtidige candles for en blind gjennomgang. AI-input er alltid as-of.

### AI-dialog
- Høyrespalte følger valgt replay-strategi og spolepunkt.
- På eksplisitt knapp/sendt spørsmål sendes kun et begrenset, tidslåst
  as-of utdrag (siste 24 ferdige PAPER-barer og 12 foregående PAPER-fills)
  til eksisterende OpenAI-modell. Kun teknisk forskningsdialog.
- Å spole til nytt tidspunkt forkaster dialogminnet for forrige as-of,
  slik at historien ikke lekker fremtidige datapunkter.
- AI-manager-varianter oppføres som **IKKE historisk replay-klare** uten
  arkiverte as-of modellbeslutninger. Basisstrategienes resultater er
  ikke bevis for oppnådde AI-forbedringer.
- Serveren legger ikke ved Saxo AccountKey, API-token, e-post eller
  en kontoidentitet i modellgrunnlaget. `store=False`.
- Ingen automatisk handelseksekvering eller strategiendring.

### Kontoprestasjon
- Velg opptil seks faktiske Saxo-kontoer.
- Eksakt `Saxo TotalValue` som observeres ca. hvert femte minutt,
  med nederste tidsbånd fra samme lagrede `context_json`: hvilken
  V3 LIVE-strategi som ble observert, og når. Byttetidspunkt avgrenses
  til målepunkter og kan ikke gis falsk eksakt tid.
- Uavstemte kontoverdiendringer merkes **ikke netto strategiresultat**;
  cashflows, manuellhandel, valuta og overnight-funding kan påvirke NAV.
- Velg flere PAPER-strategier ved siden av kontografen. Et ekstra
  synkronisert TradingView sammenligningspanel normaliserer både
  kontoverdiendring og PAPER-utvikling til prosent; dette er separate
  scenariobaserte serier med eventuelt ulike start-/sluttider.
  Aldri bland eller summer brutto NOMINAL PAPER NAV inn i Saxo NOK-fasit.

## Test og utrulling
- Regresjonstester for 1m datagap, kausal next-open, fremtidslekkasje,
  faste/variable simkostnader, validering av Saxo kostnadsillustrasjon,
  isolert strategi-katalog, konto-isolasjon og markerte kontoperioder.
- Ingen referanse til V3 LIVE-ordre/arming, ingen skriving til LIVE state,
  ingen nye automatiske Saxo-handelstoggles.
- Railway-builds var pauset av plattformleverandøren da koden ble utviklet.
  Bekreft derfor deploy-SHA, web/worker health og skjematilgang før
  Strategilab v2 annonseres som tilgjengelig i produksjon.

## Videre milepæler
1. Utvid ekte replayadapter til alle varige AEn/fraktal/AI-varianter ved
   å løfte deres tilstandsoverganger til rene isolerte funksjoner.
2. Historisk ordrebok/1s-bid/ask, reell Saxo funding/fees, eksplisitt
   fill latency, margin og porteføljebaserte risikobudsjetter.
3. Full flerstrategi AI-historikk og forklaringsmarkører per PAPER-handel.
4. Lagre signerte, reproduserbare SIM-run-manifester i DB og sammenlign
   med kontoresultat, walk-forward og out-of-sample; ikke optimizer på
   samme vindu uten korrigering for data mining.
