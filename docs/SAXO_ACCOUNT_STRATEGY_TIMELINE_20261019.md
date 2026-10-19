# Kontostatistikk: en faktisk Saxo-kontograf per aktiv konto

## Bruk
Analyse → Kontostatistikk → velg periode (standard 7 døgn).

- Alle V3-registrerte aktive kontoer vises **samtidig**, hver med en egen
  Plotly-graf og egen kontovaluta, uten at brukeren må bytte kontovelger.
- Øverste felt: Saxo \`TotalValue\` over faktisk observasjonstid. Bare
  \`CalculationReliability=Ok\` gir kurvepunkter. Manglende tidsrom
  (>2.5 × femminutters kadens) og ugyldige verdier forbindes ikke.
- Nederst: fargebånd på **felles tidsakse**. Båndene viser historisk
  persistert \`context_json\` fra kontosnapshot, med strategi,
  timeframe og LIVE-arming ved den observasjonen, ikke nåværende config.
  Hold over båndet/trykk for full strategitekst, marked,
  første/siste observerte klokkeslett og antall observasjoner.
- Lange perioder får tekst direkte på båndet. Korte perioder viser
  markør/bånd med hover og en utbrettbar tabell over alle observerte
  perioder i samme konto.
- Kontoer uten aktiv V3-instans er skjult som standard, men kan
  slås på med egen avkrysning. Da markeres manuell/ukjent eier
  eksplisitt; vi **tilskriver ikke** andre instrumenter V3-resultat.
- Sekundær kontovelger for EOD/Saxo-offisiell P/L og
  ordre-/markedsdetaljer er beholdt nedenfor.

## Viktige presisjonsbegrensninger
- Strategiskifte kan ha funnet sted **mellom** to femminuttersmålinger.
  Start/slutt er første/siste **observerte** tidspunkt, ikke eksakt
  ordre- eller byttetid. Segmenter slås ikke sammen gjennom datagap.
- Konto-NAV endring er IKKE automatisk strategi-P/L. Kapitaloverføringer,
  valutakurs, manuelle handler, finansiering og instrument utenfor
  V3-kontoens primære marked kan påvirke den viste verdien.
  Offisiell Saxo EOD-nettoprofit vises separat der tilgjengelig.
- Ingen fiktiv historikk før kontoinnsamleren ble aktivert.
- Ingen endring i Saxo-API, collector, ordreutførelse, arming,
  strateginøkler eller LIVE-risikostyring. Funksjonen er ren
  visualisering basert på lagrede data.

## Observasjon av kontoverdi per aktiv LIVE-strategiperiode (19.10)
- Analyse → Kontostatistikk viser nå også en egen tabell per konto med
  observerte, sammenhengende LIVE-strategiperioder fra Saxo TotalValue.
- Det kreves samme konto, valuta, entydig instans/strategi, verifisert
  CalculationReliability=Ok og mellomrom <=2,5 innsamlingsintervaller.
  Manglende/uklare data, LIVE AV, tidsbrudd og strategiendring starter
  ny periode. Verdiforskjellen OVER slike grenser tilordnes ingen strategi.
- Vises: start, slutt, antall målinger, uavstemt endring i kontoens valuta,
  uavstemt prosent og største observerte kontoverdifall. Én måling har
  ukjent endring — aldri 0 eller fabrikkert avkastning.
- Tallene er OBSERVASJON, **ikke** netto strategi-P/L. Manuelle handler,
  kapitaloverføringer, FX og finansiering må avstemmes mot Saxo før
  strategirangering.
- Individuell kontohistorikk leser alle observasjoner i valgt periode.
  Fleet-oversikt er bounded til de 50 000 NYESTE radene, med synlig
  avkortingsvarsel; perioden avkortes ikke stille til de eldste dataene.
- Offisiell Saxo EOD-innsamler rapporterer nå sikre feilkoder pr fase
  (kontoidentitet, timeseries-GET, summary-GET, parsing, persist), og
  HTTP-status uten sensitiv payload. 8/12 tidligere manglende
  EOD-resultater kan diagnostiseres ved neste innsamling.
- GET-only; ingen Saxo-order, arming, kontoinnstillinger eller andre
  LIVE-mutasjoner utføres.

## Videre utvikling
Når Saxo-transaksjonsavstemming er på plass kan nøyaktige
strategibyttetidspunkt (fra en varig config-audit) og faktisk
flow-adjusted konto-/strategiavkastning tegnes på samme tidsakse.
Inntil da skal grafen konsekvent skille observasjon og attribusjon.
