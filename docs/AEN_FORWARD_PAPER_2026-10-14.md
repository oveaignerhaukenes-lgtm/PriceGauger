# AEn Core — fase 2: fremoverskuende PAPER og diagnostikk

Dato: 2026-10-14. **Kun SIM/PAPER**. Dette dokumentet beskriver utviklingsgrenen `feature/aen-forward-paper-v1`.

## Nytt
- Fem forhåndsdefinerte, 1-enhets AEn-kohorter starter fremoverskuende på **neste hele minutt** når Live-Sim-workeren har bekreftet en eksisterende Tech100-feed. Fire basisfamilier på 5m (Hold, Histogram, Hysteresis, Stochastic), pluss regelbasert Adaptive MACD Hold 10m.
- Konfigurasjoner lagres som frosne `config_json` med SHA-basert ID. Samme aktivering gjentas ikke ved prosessrestart.
- Maks observasjonsperiode 14 dager per kohort; de avsluttes uten sletting av historikk. Avkastning før enrolment inngår ikke.
- Egne `aen_forward_runs` og `aen_forward_points` i eksisterende DB, uten råquotes; pointserier samples hvert 5. minutt og ved virtuelle fills.
- Neste-bar-PAPER-utførelse med foreløpige spread-/avgiftsproxyer. **Ikke Saxo-realiserte fills**, ikke faktisk nominell eksponering/margin.
- Ved endret historisk OHLCV-input fryses kohorten i `PAUSED_REVISION`; kurven restates aldri i ettertid. Også endringer mens porteføljen er flat oppdages via prefix-SHA.
- Egen AEn Forward-scoreboard over historisk AEn replay. Skiller prospektive og retrospektive kurver tydelig.
- Beskyttende HL/LH-nivå følger en åpnet posisjon gjennom neste-bar-fill; volumreferansen kommer aldri fra foregående handelssesjon.
- Diagnostikk: antall enheter omsatt, brutto–netto-kostnadsdrag, gjeninnganger etter flat innen 1/2/5 minutter, valgfri fem-arms komponentablasjon.

## Arbeidsdeling og sikkerhet
1. `aen_replay_v1.py` er deterministisk; kan kun produsere virtuelle mål/fills.
2. `aen_forward_paper_v1.py` kan kun lese ferdige markedsbarer og skrive egne PAPER-tabeller.
3. `live_sim_lab_worker_v1.py` kaller forward-modulen under eksisterende separat Live-Sim-worker, omgitt av isolert error handling.
4. `aen_lab_ui_v1.py` leser forward-tabellene. UI kan aldri autorisere LIVE-ordre.
5. **Ingen endring i V3 LIVE-ordrer, konto-arming, Saxo-posisjoner eller eksisterende strategi.**

**Operativt stoppunkt før merge/deploy:** Brukeren ønsker alle LIVE-systemer av. I kontrollen 2026-10-14 kl. ca. 08:52 CEST viste runtime likevel én V3 armed/enabled: Tech100-B (`f75cdc83-168b-5eb4-9224-ce73a058b6d3`), rapportert `MANAGING` med +0,02 lot. Før ny produksjons-deploy bør dette avklares i UI og mot Saxo. Ingen automatisk deaktivering fra denne utviklingsgrenen.

## Begrensninger / neste forskningsrunde
- Prospektiv simulering er fortsatt rekonstruksjon av neste-bar-fills på kanoniske data etter bar-close, **ikke observasjon av faktisk ordreutførelse**. En separat Saxo-test-/kalibreringsfase trengs.
- Inputmangel, dataskifte eller algoritmeendring må føre til pause / separat ny forsøkskohort, ikke umerket omregning.
- 14 dagers sample på én markedsperiode er ikke statistisk bevis for stabil forventningsverdi. Test flere opp-/ned-/sideveis-regimer, kostnader, stopplogikk og nullhypoteser med walk-forward/out-of-sample.
- AI-modellen har fremdeles **ingen posisjons- eller ordreautoritet**. Neste fase er AI-forslag for valg av `signal_tf_minutes` innenfor forhåndssatte dwell/hysterese-regler, med full audit.
- Bank-/Saxo-konto og fysisk 0,01-lot notional må kalibreres separat. `unit_exposure=0.2` er en syntetisk forskningsparameter, ikke en faktisk Tech100-margin.
- Systemet trenger ikke å endre eller slette PostgreSQL volum eller historikk. Kontrollér likevel CPU/DB-last fra reprospektiv beregning per nytt minutt.
