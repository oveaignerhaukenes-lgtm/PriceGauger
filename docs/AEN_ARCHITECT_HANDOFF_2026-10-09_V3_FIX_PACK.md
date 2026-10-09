# Arkitekt-handoff — PriceGauger V3: chart markers, LIVE idempotence, status UI
**Dato:** 2026-10-09
**Omfang:** Håndtering av PR #680, #683, #684. Parallell utvikling av Live-Sim Lab og strategier må ikke forstyrres.
**Arbeidsgrunnlag:** `main` var `0d55ccd20744e36ca03fbda162f82ce80502fb42` da PR #683 og #684 ble forgrenet. PR #680 er basert på en tidligere `main` og må kontrolleres mot siste endringer før merge.

## Operasjonell status fra produksjonen (bevist i Railway worker, UTC)

- Fire V3 LIVE-instanser var `armed`.
- Den eneste 10m-instansen, `f3e65462…` (Hvelvet etter valgt 10m-oppsett på skjermbildet; bekreft eksakt account binding i UI/DB), åpnet short 0.01 kl. 09:00:30 UTC og økte til 0.02 kl. 09:10:24; begge ble `RECONCILED`.
- 5m-instansen `f115f072…` forsøkte en gyldig short på 0.02 (precheck 296.671 NOK under PG-grense 300 NOK) kl. 08:32 UTC. `autotrader_v3_order_guard_pkey` UniqueViolation kastet **før** Saxo `place_order`. Det samme skjedde gjentatte ganger i fire senere sykluser frem til ca. 08:34:48.
- 5m-instansen gjenopptok faktisk handel: OPEN SELL 0.01 kl. 09:00:27 UTC og ADD SELL 0.01 kl. 09:05:46, begge rekonsilierte. Videre ønsket ADD til 0.03 ble korrekt holdt igjen fordi kravet var rundt 445 NOK > 300 NOK.
- **Kapitalgrensen er tilsiktet, ikke en feil som må overstyres.** Ikke øk brukerens investeringsrammer på eget initiativ.

## PR-er som skal vurderes

1. **#683 [V3 order idempotence](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/683)** — kritisk LIVE runtime bug, issue [#682](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/issues/682). `autotrader_v3_order_guard_v1.reserve` får en *valgfri* atomisk `idempotent=True`, men gamle strenge kall beholder normal UNIQUE-exception. Runtime forhindrer replay av RECONCILED intent, lar in-flight requests reconciles, og leser tilbake durable state etter unik konfliktsituasjon før den noensinne kan sende Saxo-ordre. Det finnes regresjonstester. CI ved siste sjekk: **success**.
2. **#680 [TradingDesk execution triangles](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/680)** — presentasjonsrettelse. Aktiv renderer `simple_live_v2` overskrev canonical BUY/SELL basert på *resulting position direction* ved både mount og 1-sekunds oppdatering; rettelse bevarer V3-side-markører. V3-leser hentet dessuten feilaktig de *eldste* 1000 av de siste 14 dager; rettelse henter nyeste 1000 og sorterer for kronologisk rendering. CI tidligere: **2057 passed**. Visuell kontroll av samtidige markører gjenstår; browser stacking kan fremdeles skjule overlappende markører på samme candle.
3. **#684 [V3 readable instance status](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/684)** — ren *read-only* UI. Viser `actual` og `target` **kun** dersom tallene finnes i siste worker-heartbeat, sammen med `status`, tidspunkt, kapitalramme, siste account-scopede rekonsilierte event og tydelig "PG capital cap reached". Ingen nye Saxo API-kall, beslutningsendringer eller execution writes. Ved manglende heartbeat vises `ukjent` (ikke en oppdiktet flat posisjon). CI avventes.

## Anbefalt gjennomføring

1. **Koordiner med parallell arkitekt** om nye PR-er/commits på `main`. Start med `git fetch`; sjekk berørte filer, innhold og eventuelle kryssende UI-oppdateringer.
2. **#683 først** (ordre-idempotence), etter code review og grønn CI. Verifiser at `ON CONFLICT DO NOTHING` er atomisk på både Postgres og SQLite, at `rowcount` brukes til å forby broker-submit ved konflikt, og at gammel `reserve()` fortsatt feiler strengt for andre kall (inkl. V2 pyramid). Unngå enhver uautorisert re-submit av RECONCILED/UNKNOWN intent.
3. **#680 deretter** (graf), rebase/merge mot frisk `main`. En merged CI-test alene beviser ikke at to/tre piler på samme candle fysisk er synlige. Test i TradingDesk med ulike kontoer, SELL-reduksjon fra LONG, BUY-lukk fra SHORT, og manuelle markører separat. Sjekk ID, time-alignment, backend count, UI payload count og `setMarkers` count dersom visuelle overlapp består.
4. **#684** (status), rebase/merge. Bekreft på mobil og desktop i **både TradingDesk og Fleet** at riktig account_id/UIC/instance brukes, at det faktisk står "siste heartbeat", og at stale/ukjent ikke fremstilles som bekreftet sanntid.
5. Kjør hel CI for hver sammenfletting. Verifiser hver gang Railway worker/web deployment bruker forventet `main` SHA, og at ingen eldre build blir rullet over nyere parallelle commits. Følg deployment til SUCCESS.
6. Kontroller 5m ved ett eller flere *naturlig oppståtte* nye lukkede bars: ingen `order_guard_pkey` i ny logg, ingen duplicate broker submissions, RECONCILED historikk beholdes, og forskjellige kontoer fortsetter uavhengig. Ingen manuell live-ordre skal brukes som test.
7. Kontroller at en PG-kapitalramme på 300 NOK fortsatt tillater ~0.02 lot men stopper 0.03 når precheck viser ~445 NOK. Bruk faktisk Saxo precheck; ikke hardkod disse estimatene.
8. Hvis visning fortsatt virker feil: hent read-only `autotrader_v3_live_runtime_state`, `autotrader_v3_execution_events` og siste durable guard for **eksakt** `instance_id+account_id+uic+asset_type`. Skill utvidelsesblokkering fra faktisk ordre-ID-konflikt og fra strategiens legitime `target=0`.

## Risiko og ikke-mål

- Ingen LIVE arming/disarming, Saxo-handler, justeringer av kapitalrammer, konto-overtakelser, strategiendringer eller schema-migrering er del av disse PR-ene.
- Ikke anta at Saxos liste "Lukk posisjon" er lik nettoeksponering; intradag gross long/short kan være motgående. Autoritativ runtime-verifikasjon krever eksakt account/product Saxo net inventory og reconciliation.
- Last-execution UI viser en **avstemt historisk hendelse**, ikke nødvendigvis åpen posisjon. Last runtime heartbeat er tekstbasert og kan være stale; skjermbildet må gjøre dette eksplisitt.
- Dersom en PR er i konflikt med parallell innsats, flytt bare dens relevante endringer framover til frisk base; ikke force-push den andres arbeid.
