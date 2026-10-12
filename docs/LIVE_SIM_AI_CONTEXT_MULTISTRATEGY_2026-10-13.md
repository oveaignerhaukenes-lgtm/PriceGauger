# Live-Sim AI-Strategilab: valgbare grunnstrategier, teknisk og kontekstuell AI

**Dato:** 2026-10-13. **Motor:** `lsim-ai-context-pairs-v1`. Kun fremoverrettet PAPER-forskning. Ingen Saxo-ordre, LIVE-endringer eller nye handelsfullmakter.

## Fem armer per valgt grunnstrategi

Operatøren kan velge opptil seks aktive LAB-varianter, som lagres i en egen, durabel forskningskohort. For **hver** valgt strategi startes fem likt finansierte og separat kostnadsførte spor:

| Arm | Hva bestemmer posisjonen? | Kan velge annen retning enn grunnstrategien? |
|---|---|---|
| BASE | Uendret LAB-grunnstrategi | Nei |
| TECH_AI | AI kan beholde, halvere eller lukke grunnstrategiens signal, kun tekniske data | Nei |
| TECH_AUTO | AI bestemmer selv SHORT, FLAT eller LONG, kun tekniske data | **Ja, full PAPER-disposisjon** |
| CONTEXT_AI | AI kan beholde, halvere eller lukke grunnstrategiens signal, med kildeverifisert kontekst | Nei |
| CONTEXT_AUTO | AI bestemmer selv SHORT, FLAT eller LONG, med kildeverifisert kontekst | **Ja, full PAPER-disposisjon** |

Det samme AI-kallet gir både en risikovurdering (KEEP/HALF/FLAT) og en autonom målposisjon. Dette holder modellutgifter nede og gjør hver vurdering etterprøvbar. De autonome armene kan være uenige med sin grunnstrategi og gå SHORT selv når grunnstrategien ville være LONG. Papireksponeringen er normalisert i trinn på 0,5 og absolutt begrenset til valgt grunnstrategis `max_exposure`. **Ingen ordre går til Saxo**, og LIVE-AutoTrader er uberørt.

## UI

Live-Sim Lab → **AI-strategilab · nyheter, makro og geopolitikk**, lenger nede på siden:

- Flervalg: 1–6 grunnstrategier fra aktiv LAB-katalog, med eksplisitt «Bruk strategivalget».
- Fanene «Teknisk AI mot grunnstrategi» og «AI + nyheter / makro / geopolitikk».
- Per strategi: avkastningstabell samt **egen kurve for BASE, AI-risikolag og autonom AI**, med identisk starttidspunkt.
- Oversikt over faktiske modellvurderinger med tidspunkt, begge målposisjoner, konfidens, begrunnelse, dekning og status.
- Ved endring av utvalg stoppes fjernede forsøk uten å slette historikk. Gjeninnmelding oppretter ny kohort med ny nullstilling.

## Tids- og kildekrav

Bare nye, ferdigstilte canonical 1m-barer etter brukerens starttidspunkt påvirker forsøket. Hver vurdering krever aktuell teknisk featuretilstand og en faktisk fullført grunnstrategibar. Modellsvar lagres **når det foreligger**, aldri tilbakedatert til databarens tidspunkt. Både base, begrenset AI og autonom AI oppdaterer PAPER-P/L ved neste baråpning, med samme konservative omsetningskostnader og prisbevegelse.

Kontekst-AI bruker nåværende eksisterende PriceGauger-kilder, kun når kjent ved modellvurdering:

- Generelle nyheter: eksisterende Telegram-/nyhetsvurderinger, med publisering/observasjon og maks 45 min ferskhet. Dette er ikke uttømmende nyhetsdekning.
- Makro: eksisterende offisielle BLS/BEA/Fed-**kalendere**, inkludert kilde-/tilgjengelighetstid. Det betyr planlagte publiseringer, ikke faktisk CPI/NFP, konsensus eller rapportoverraskelse.
- Geopolitikk: fersk global Context v2 med kildereferanser, kontrollert `as_of`, `recorded_at`, `coverage_end`, publiserings- og observasjonstid; maks 30 min ferskhet.

Manglende, gamle eller utilgjengelige kilder vises som **MISSING**, aldri som bevis på at det ikke er relevante hendelser. Hvis samtlige kildetyper mangler, gis ingen kontekstuell modellvurdering: risikolaget følger BASE og den autonome kontekstarmen holder seg FLAT.

Modellkall begrenses til minst 15 minutter per forsøksvariant; maks to kall per ettminutts researchersyklus og 480 totalt pr. UTC-dag, delt mellom alle valgte strategier. Kall kan gi faktiske OpenAI-API-utgifter, og kilde-/markedspause gir null nye vurderinger. Autonom AI holder ikke en modellposisjon evig hvis modellen slutter å svare: siste beslutning utløper etter 20 minutter og PAPER-posisjonen går til FLAT på neste simulerte bar.

## Vurdering og begrensninger

Se først på prisutvikling **etter spread, kommisjon og flat/short-kostnader**, deretter DD, antall handler og antall gyldige AI-vurderinger. Liten prøve, samme markedsdata og korrelerte basevarianter er ikke statistisk bevis for en robust fordel. Flest positive handler kan være ren tilfeldighet eller for kort dataserie.

**Full execution rights betyr kun frihet til å velge egen simulasjonsposisjon**, aldri tilgang til Saxo. Før en eventuell LIVE-versjon kreves separat risikoprosedyre og eksplisitt godkjenning av konto, ordretype og kapitalgrenser.
