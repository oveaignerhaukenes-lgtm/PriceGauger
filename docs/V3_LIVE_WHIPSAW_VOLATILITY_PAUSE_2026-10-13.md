# LIVE V3: Whipsaw Pause og Volatility Pause

Dato: 13. oktober 2026. PR #695.

## Status, virkeområde og godkjenning

De to modifikatorene er tilgjengelige under **Options / modifiers** for hver V3-instans med runtime-klar strategi. De er slått **AV som standard**, og denne PR-en endrer ingen eksisterende Saxo-ordre, kontoinnstillinger eller ACTIVE LIVE-toggles.

- **Whipsaw Detector:** en eksplisitt **ekstra LIVE-godkjenningsknapp** per instans kreves etter at modifikatoren er valgt og konfigurert. Dette hindrer eldre SIM-only modifikatorvalg fra å bli aktivert automatisk ved deploy. Godkjenningen kan trekkes tilbake. Ved valgt, men ikke godkjent whipsaw, tillates utganger og reduksjoner, mens nye innganger/ADD av sikkerhetshensyn sperres.
- **Volatility Pause:** dette alternativet finnes ikke i eldre config. Velg modifikatoren og **«Bruk på denne instansen»** før den får LIVE-effekt. Det er ingen automatisk aktivering.
- **Fast Exit S10/R30 + Volatility Pause:** separat **forhåndsvalgsknapp** i hver V3-instans. Setter *bare skjemaet* til `aen21-sticky-fast-exit`, signal **10m**, regime **30m**, og `volatility-pause`. Brukeren må fortsatt trykke **«Bruk på denne instansen»**; knappen armer ikke LIVE eller sender ordrer.

## Sikkerhetsregler (begge)

- Blokkerer kun **nye innganger** og **økning/pyramidering** når respektive pause er aktiv.
- Tillater **normal REDUCE og CLOSE**. Et mål på motsatt side av den faktiske Saxo-posisjonen tvinges først til **FLAT**, aldri HOLD av feil side.
- Ved **manglende/stale/ikke-sammenhengende** fullt lukkede 1m-barer blokkeres også *nye* posisjoner og ADD for en konfigurert pause; eksisterende reduksjons- og exitsignaler får fortsatt passere.
- Eksisterende durable ordrevern, avstemming mot Saxo, kapitalgrense, kostnadsguard og eksakt instrument/konto-eierskap brukes uendret.
- Vetoerte pyramideringsmål justeres ned til faktisk broker-inventory i eksisterende V3 closed-bar cursor; de hoper seg ikke opp og blir ikke «utløst» mellom ferdige strategibarer.
- **Ingen LIVE-handelsgaranti uten gyldig Saxo-autentisering.** Ved `REAUTH_REQUIRED` kan motoren ikke verifisere eller justere posisjoner. Før motorene fortsetter etter databasehendelsen må OPEN/SENT/UNKNOWN-ordrer og faktiske Saxo-posisjoner stemme.

## Hvordan detekteres whipsaw?

Basert på reelle, **ferdige sammenhengende 1-minuttsbarer**, uavhengig av strategiens egen S- og R-tidsramme.

- Krever minst 31 sammenhengende 1m-barer og fersk siste bar.
- De **12 siste 1m-avkastningene** må ha minst **7 fortegnsskifter**, og Efficiency Ratio må være under **0,35**.
- Etter deteksjon forblir sperren aktiv til **tre påfølgende rolige lukkede 1m-barer** har passert, målt én gang per unik bar. En re-start kan ikke dobbelttelle tid.

Standardinnstillinger: `lookback_bars=12`, `max_direction_changes=6` (detekter ved > 6), `cooldown_bars=3`. Tidligere lagrede per-instans-parametere gjelder dersom de finnes.

## Hva er Volatility Pause?

Samme markedsvolatilitetsproxy som Live-Sim Lab (HIGH_VOL):

- Minst **61 sammenhengende** ferdige 1m-prispunkter (60 enminuttsavkastninger).
- `stdev(siste 12 avkastninger) > max(0.00001, 1.5 × stdev(siste 60))` signaliserer `HIGH_VOL`.
- Når dette skjer, begrenses nye posisjoner/pyramidering; eksisterende utgang og reduksjon påvirkes ikke.
- Dette er en **markedsregimepause**, ikke automatisk stop-loss. Den er ikke lik whipsaw-detektoren og kan brukes separat eller sammen med den.

## LAB vs LIVE – viktig forskjell

Varianten **`fast_exit S10/R30 volatility_pause`** i Live-Sim Lab og **`Aen#2.1 Fast Exit R30/S10 + Volatility Pause`** i LIVE har lignende oppsett, men **ikke identisk signallogikk eller P/L-beregning**. LAB bruker normalisert eksponering og simulert neste-bar-open; LIVE bruker Saxo-posisjoner, instrumentstørrelse, faktiske spreader og ordreavstemming. En LAB-vinner er en hypotese, ikke grunnlag for å anta samme LIVE-resultat.

Ingen automatisk binding til en bestemt Saxo-konto. Brukeren må angi konto/instans og bekrefte strategivalget etter at Saxo-innloggingen er frisk.

## Operasjonell sjekkliste

1. Bekreft gyldig Saxo-autentisering og at LIVE-worker ikke rapporterer `REAUTH_REQUIRED`.
2. Kontroller eksakte posisjoner og eventuelle SENT/UNKNOWN/PENDING ordre etter recovery.
3. Velg V3-instans og eventuelt «Forhåndsvelg Fast Exit S10/R30 + Volatility Pause».
4. Se over konto, faktisk strategi og eksponeringsramme, og trykk «Bruk på denne instansen».
5. Hvis whipsaw også velges: gi separat godkjenning; se at den er registrert. Whipsaw kan trekkes tilbake uavhengig.
6. Følg V3-runtime-loggene `v3 LIVE whipsaw` og `v3 LIVE volatility-pause`, kontrollér at REDUCE/CLOSE fortsatt går gjennom, og at nye signaler først handles på riktig bar.

