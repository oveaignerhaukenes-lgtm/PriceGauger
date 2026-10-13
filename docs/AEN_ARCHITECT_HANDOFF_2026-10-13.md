# PriceGauger – handoff til neste arkitekt – 2026-10-13

**Autoritativ fersk overlevering per 13. oktober 2026, ca. kl. 12:25 norsk tid.**
Repository: `oveaignerhaukenes-lgtm/PriceGauger`.
Verifisert `main` før denne dokument-PR-en: `74b4663e32d6e5692ee416d34d7c410698312e58` (PR **#696**, Tech100-B-only LIVE Whipsaw).
Ingen åpne PR-er ved kontroll. GitHub `main` CI for #696 **SUCCESS**.
Railway project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`, production env `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`.
Ved kontroll er de **seks tjenestene SUCCESS** på `74b4663e…` for alle fem apptjenestene. Railway `SUCCESS` sier *deploy frisk*, ikke at hvert eksternt Saxo-ordrekall eller LAB-kilde er komplett.

## 1. Viktigste instruks til neste arkitekt

1. **Begynn med produksjonens faktiske LIVE-status, Saxo-posisjoner og ventende ordre.** Ikke anta at eldre loggutdrag beskriver nåværende posisjoner.
2. Bruk nyeste `main`; den 9. oktober-handoffen er eldre og **foreldet for whipsaw**. Særlig er LIVE Whipsaw nå implementert, og **kun Tech100-B har fått verifisert eksplisitt aktivering**.
3. Ikke endre LIVE-strategi, Saxo-konto, posisjoner, tillatelser, order flow, risikoandel eller øvrige instansers modifikatorer uten konkret brukerfullmakt. SIM/LAB kan eksperimentere separat.
4. Følg brukerens arbeidsform: gå gjennom mange små oppgaver i én økt, PR → CI → guardet merge → Railway-deploy → kontroller faktiske runtime-logger. Korte brukeroppdateringer; ikke bli stående ved CI.
5. **Gjenoppretting av DB er prioritert foran opprydding.** Brukeren har valgt å utsette lokal backup, eventuell tømming og revisjon av datainnsamlingsstrategien til en annen dag. IKKE slett historikk nå.
6. Ikke bland `PRICEGAUGER`-nyhetskontekst, tilgjengelig makrokalender og faktisk makrorapport: ingen automatisk dokumentert fullstendig dekning av publiserte tall. AI-research må unngå lookahead.

## 2. Produksjon og hendelsen med full PostgreSQL

- **13. oktober tidlig:** PostgreSQL-volumet nådde grensen på **10 GB**. Feil: `No space left on device`, etterfulgt av recovery-mode og LIVE-worker / Spring Trade Engine-krasj. Kontoverdier kan fortsette å svinge hos Saxo selv når AutoTrader er nede.
- Brukeren utvidet **eksisterende** `postgres-volume` til **20 000 MB**. PostgreSQL logget `database system is ready to accept connections` etter recovery; IKKE bytt eller slett volumet.
- Aktive volumer kontrollert via Railway: Postgres-volum `41e4dd8f-7817-499b-bd71-0b7e0bd6ccc0` (20 000 MB, `/var/lib/postgresql/data`); worker-volum `21b55edf-48af-4d08-b03a-850bc63dfa2c` (500 MB, `/data`).
- Worker og Spring ble restartet etter DB recovery. Saxo ga midlertidig `REAUTH_REQUIRED` fra utløpt refresh-token (sett 09:35–09:43 UTC). **Etterpå, 09:43–10:25 UTC, ses igjen LIVE eksekveringslogger og Saxo-avstemminger**; eldre `REAUTH_REQUIRED` er altså ikke tilstrekkelig for å konkludere at autentisering fortsatt er nede.
- Nåværende Railway `latestDeployment`: alle seks `SUCCESS`; fem apptjenester på `74b4663e…` (#696). Postgres er selv en separat eldre deploy som kjører.
- Operativ risikofaktor: volumet ble fullt svært raskt pga. historikk/quote/LAB-datainnsamling. **Planlagt separat vedlikehold senere**, med gjennomtenkt lokal backup/restore-test, retensjon, indekser, samplingsstrategi, rådata versus aggregater. Ikke gjør destruktiv opprydding i denne overleveringen.

### Railway service-ID-er

| Tjeneste | ID |
|---|---|
| PriceGauger-worker (LIVE V3) | `5267feed-b5cb-4f85-a24a-0c5124664b59` |
| Spring-Trade-Engine | `254b205b-1633-4c69-aa84-486a0fa6f052` |
| PriceGauger-stream | `0be7cd65-533f-4882-9b81-efeda5b35153` |
| pricegauger-web | `38f57908-1f7a-40ce-9bf4-abcdf43fe429` |
| PriceGauger-LiveSimLab | `750e9d69-68a8-4fd1-8052-8e94bae164bf` |
| Postgres | `a7a66447-8138-4ea9-94b0-5df0c291f337` |

## 3. Siste LIVE-observasjon (12:25 norsk tid / 10:25 UTC)

Worker-logg på gjeldende deploy viser **fire enabled, owned, armed instanser** og énsekunds closed-bar-datavakt. Konkrete ID-er:

| Konto / instans | Trader UUID | Observasjon (IKKE bindende nåværende posisjon) |
|---|---|---|
| Tech100-A | `b6008676-ec57-50e9-9cbf-3b0577c643ab` | `timeframe=1m` i siste logg, `actual=+0.02 → target=+0.01`, REDUCE Sell 0.01 ca. 10:25 UTC; **mange justeringer**, overtrading er fortsatt hypotese |
| Tech100-B | `f75cdc83-168b-5eb4-9224-ce73a058b6d3` | `timeframe=2m regime=15m`, `actual=+0.02 target=+0.02 pending=none`, LIVE whipsaw lagt på og kjørt |
| Tech100-C | `f115f072-036f-5e3b-a61e-459816070186` | **`status=PENDING actual=-0.02 expected=-0.01 pending=waiting; no retry sent`**. Sjekk faktisk Saxo-ordrehistorikk, restkvantum og durable reconciliation. Ikke bypass order guard eller dobbeltsend! |
| Hvelvet | `f3e65462-77a4-5b0b-97a2-d744da0edc66` | `timeframe=10m`, `actual=0 target=0 pending=none`; bruker sa at Hvelvet nylig ble endret til **MACD Histogram**. Bekreft strateginøkkel i faktisk config før rapportering |

**Obs:** A har nå `1m` i logg, mens eldre handoffs beskriver `2m`; bruker/andre arkitekter justerer konfigurering fra UI. Ikke skriv over brukervalg basert på gammel håndbok.

Bruker har tidligere spesifisert: Når han lukker posisjoner manuelt, kan AutoTrader korrekt gjenopprette strategiens ønskede posisjon. Manuell flat er ikke et permanent strategiveto. Problemet må skilles fra uavklarte ordrer og Saxos Tech100-markedspause (23–24 lokal tid).

### LIVE whipsaw: **nyeste og viktigste endring**

- PR **#695**, commit `4b71bb0699…`: Whipsaw Detector og Volatility Pause er nå **LIVE-kapable V3-modifikatorer**, begge OFF som standard. Whipsaw krever **separat per-instans eksplisitt godkjenning**, og kan trekkes tilbake. UI har også ikke-lagrende forhåndsvalg av `Aen#2.1 Fast Exit S10/R30 + Volatility Pause`; brukeren må selv trykke «Bruk på denne instansen».
- PR **#696**, commit `74b4663e…`: eksakt **Tech100-B** autorisert via engangsworker-handling, kontrollert mot market/account/trader-ID, ingen uavklart pending-ordre ved aktivering, varig marker mot senere reaktivering. **IKKE A, C eller Hvelvet**.
- **Bekreftet runtime-aktivering:** 2026-10-13 **10:05:14 UTC**: `USER_AUTHORIZED Tech100-B ONLY: LIVE Whipsaw Detector enabled; ... no orders sent`.
- **Bekreftet faktisk deteksjon:** B kl. 10:16 UTC `active=True data_ok=True changes=8 efficiency=0.220613`. Ved ca. 10:20 UTC `active=False data_ok=True` etter rolig-periode/hysterese. Nyeste 10:25 UTC: `active=False data_ok=True changes=5 efficiency=0.161786`.
- LIVE detector baserer seg på **reelle, 31 sammenhengende fullførte 1m-barer**; i siste 12 avkastninger må >6 skifte fortegn + Efficiency Ratio <0.35. Hysterese: tre påfølgende rolige 1m-barer. Dårlig datakvalitet blokkerer nye innganger/ADD, men aldri normale utganger/reduksjoner. Volatility Pause ser på forholdet stdev(12)/stdev(60).
- **Brukerens siste strategiønske før denne handoffen:** Han opplever for mye whipsaw, spesifikt omtalt «på gull», og ønsker kanskje LIVE-whipsaw. **Ikke anta at Tech100-B-aktiveringen dekker gull**, og ikke anta at «Hvelvet» er et gullinstrument uten å verifisere Saxo UIC/kontobinding. Be om eksplisitt hvilken instans/marked dersom en NY LIVE-aktivering ønskes.
- Les `docs/V3_LIVE_WHIPSAW_VOLATILITY_PAUSE_2026-10-13.md`, `autotrader_v3_whipsaw_live_v1.py` og `autotrader_v3_whipsaw_optin_b_20261013.py`. Sjekk effekten på faktisk turnover og nettoresultat, ikke bare at statuslinjen viser `active=True`.

## 4. Nylige endringer – rask commit/PR-kjede

- **#687** `67cadecfec`: Live-Sim strategiutvalg/evolusjon, 72→252 prospektive kandidater, 3 shadow-selectors, AI-analytiker research-only.
- **#688** `e5b7ef58a2`: makro/geopolitikk-kontekst LAB for fem kvalifiserte grunnstrategier med BASE/MACRO/GEO/BOTH. Delvis/ukjent kildedekning er eksplisitt.
- **#689** `c5d4be70c8`: Whipsaw LAB Pause / Reduce / Flat sammenligning, aldri automatisk LIVE.
- **#690** `499a3dffa3`: `macd-stoch-v2` ny vektet indikator (70% ATR-normalisert MACD-histogram + 30% Stoch K–D; to bekreftende fullførte barer før inngang; flat før ny retning); strategiforklaringer via **❔** i felles V3-strategivelger. Eksisterende v1 uendret.
- **#691** `4d5074ee66`: LIVE **1s read-only kontroll for ny ferdig 1m-markedsbar** og umiddelbar strategi-vurderingsvekking; **30s separat full Saxo-reconciliation**, én ordre-kjede av gangen. Ikke sekundbasert intrabar trading for closed-bar-strategier.
- **#692** `48f2c5ec00`: Hyper-Vigilant Stochastic: research-only ekte Saxo Tech100 bid/ask-snapshots opp til 1 Hz, Stoch primær, MACD i flat Stoch, adaptiv prisoverstyring, seks whipsaw-/kontroll-armer. Quotes ikke syntetisert fra 1m-barer.
- **#693** `9577fa4657`: uavhengig teknisk AI PAPER-trader (LONG/SHORT/FLAT, tap >60s / regelmessig vurdering ~180s); egen høyre **AI-vurderingsticker** 10s oppdatering; AI-heartbeat/status i global status og Worker Status. Aldri Saxo-fullmakt.
- **#694** `a66917bc1f`: egen underseksjon Live-Sim Lab for opptil **seks valgte LAB-grunnstrategier**. **Fem paper-armer per parent**: BASE, TECH_AI (risk overlay), TECH_AUTO (autonom PAPER LONG/SHORT/FLAT), CONTEXT_AI (risk overlay), CONTEXT_AUTO (autonom PAPER). Parvis grafer, dated context, kilde-/freshnesskrav, neste-bar-open fills, samme kostnadsmodell, autonom AI kan være uenig i retningen. Kun SIM.
- **#695** og **#696** omtalt i §3. Aktuelle på `main`.

### Viktig forskjell: AI-modellvurdering vs modellfullmakt

«Full execution rights» ble eksplisitt ønsket **innen SIM**. TECH_AUTO/CONTEXT_AUTO har uavhengig PAPER-målposisjon, men kan **ikke** plassere eller kansellere Saxo-ordre. Kildesituasjonen må fortsatt verifiseres: makro er i stor grad en hendelseskalender, ikke faktiske utfallsdata. AI skal ikke få real-market execution av en UI-/LAB-endring.

## 5. Nåværende UI og forskningskomponenter

- Web: https://pricegauger-web-production.up.railway.app
- TradingDesk: V3 Fleet/strategivelger, ❔ med kort strategioppsummering, felles Live Chart med fargekodede piler for A/B/C/Hvelvet. Brukeren rapporterte at **alle piler nå vises**; ikke regresjonsendring her.
- Live-Sim Lab:
  1. Grunnleggende LAB-strategier og prospektiv sammenlikning / selektorer.
  2. Whipsaw LAB-eksperimenter: BASE, PAUSE, REDUCE, FLAT.
  3. Hyper-Vigilant Stochastic: ekte 1s quote-baserte kontroll-/whipsaw-varianter. Prisoppmerksomhet kan gå FLAT når reell kurs går tilstrekkelig mot posisjonen selv om oscillator fortsatt peker den andre veien.
  4. Teknisk AI PAPER-trader med egen høyre vurderingskolonne og worker-heartbeat.
  5. **AI-strategilab** lenger nede: brukervalgt strategi (opptil 6), to faner teknisk og nyheter/makro/geopolitikk, per-strategi graf for original, regulert AI og autonom AI, fem matcher i alt.
- AI må ikke belastes for sjeldne/ingen quotes, og modelldekning må synliggjøres. LLM-kall har *reelle* kostnader selv om handler er paper. For #694 minst 15m mellom vurderinger per parent/variant, begrenset anropsbudsjett.
- Les `docs/LIVE_SIM_AI_CONTEXT_MULTISTRATEGY_2026-10-13.md`, `docs/LIVE_SIM_HYPER_VIGILANT_STOCH_2026-10-12.md`, `docs/LIVE_SIM_WHIPSAW_ABLATION_2026-10-12.md`.

## 6. Hypoteser og analyse, uten forhastet LIVE-justering

1. **Overtrading på små signaler / whipsaw** i raske Tech100-strategier er hovedhypotesen. 12. oktober var et tydelig mønster med gjentatte reverseringer, høy turnover og for små netto prisbevegelser; ikke dokumentert årsak basert bare på skjermbilder.
2. 13. oktober hadde Tech100-A svært mange `OPEN/ADD/REDUCE/CLOSE` i loggene. **Telle faktisk antall handler / kostnader / regime før konklusjon**; Saxo-kontoens %-tall er ikke intervallets strategiavkastning.
3. Brukeren byttet Hvelvet til MACD Histogram og observerte mulig **regimekomplementaritet** med Aen#2.1. To snapshots er ikke nok; analyser parvis tidsjustert P/L og korrelasjon mellom drawdowns per regime. NB bruker omtaler også gull; kontroller instrument/UIC, ikke koble sammen konto og marked ut fra navn.
4. LIVE Whipsaw på B er nå et naturlig prospektivt eksperiment, men ikke ubegrenset bevis for fordel. Falsifiseres dersom tap fra oversette trendbrudd / forsenket re-entry overstiger spart spread og whipsaw-tap.
5. MACD+Stoch v2 og Hyper-Vigilant skal forbli separate; latternevnte er **intrabar sekunders forskningsstrategi**, ikke en utilsiktet endring av closed-bar-handelslogikken.

## 7. Sikkerhets- og driftssjekker for første økt

1. **Railway status:** kontrollér alle tjenesters aktuelle deployment SHA, health og PostgreSQL volum. Fersk `main`, ingen ukjente staged changes.
2. **Saxo:** kontrollér autentisering, alle A/B/C/Hvelvet eksisterende Saxo-posisjoner (konto, UIC, retning, lot) og durabel order reconciliation. **Tech100-C var PENDING med faktisk -0.02, forventet -0.01 kl. 10:25 UTC**. Finn underliggende Saxo order ID og status før noen form for retry eller ny strategiendring.
3. **Whipsaw B:** se `USER_AUTHORIZED Tech100-B ONLY`, approved config, `v3 LIVE whipsaw` og faktisk antall blokkerte innganger/ADD; behold CLOSE/REDUCE. Ikke aktiver automatisk på andre kontoer, selv om varianter er tilgjengelige i UI.
4. **Gull:** identifiser nøyaktig instrument og kontobinding fra Saxo/PG før du sier noe om whipsaw-LIVE for gull. Hvis bruker ber om det på navngitt instans, gå gjennom separate LIVE-opt-in/risikotiltak.
5. **AI/LAB:** verifiser faktisk opptak (1s BBO), worker-heartbeats, valgte cohorts, eksisterende kontekstkilde-dekning og reelle vurderinger. Ingen tabell med «SIM fortjeneste» uten faktisk prospektivt spor.
6. **DB:** overvåk størrelse og veksthastighet, men utsett opprydding/backup til den avtalte senere økten; ikke flush tabeller, ikke drop volumer, ikke endre datainnsamlingsgrenser uten eksplisitt senere beslutning.
7. **CI, PR, deploy:** alle endringer skal være små og etterprøvbare; oppfølgings-PR med tester, vent på grønne checks, verifiser eksakt Railway commit og lese logger etter deploy.

## 8. Tidsstempler og øvrig ramme

- Norwegian time on 2026-10-13: **UTC + 2**. Railway loggtider er UTC.
- Saxo Tech100 har planlagt daglig **23:00–00:00 norsk markedspause**; andre markeder kan ha andre tidsvinduer. Ikke utled ordrestatus fra markedsstengt-bilde alene.
- Saxo kan ha **global samlet marginkapasitet** selv om PG deler opp i Saxo-subkonti; hver V3-motor har egen PG-cap. Unngå indirekte marginoverskridelser.
- Snapshot bruker ga ca. kl. 11:17: Hvelvet **288,25**, A **307,60**, B **279,09**, C **336,94**, totalt **1 211,88 NOK**; dette var under database-recovery-episoden og beskriver ikke nødvendigvis realiserte strategiretur(er). Eldre morgenbilde kl. 08:17 ga totalt **1 286,27 NOK**. Forskjellen må knyttes til tidsstemplede handler, overføringer, kostnader og åpne P/L – ikke prosentene vist av Saxo.
- Ikke legg hemmeligheter, Saxo-autentiseringstokens, API-nøkler eller sensitiv kontoinformasjon i handoffs/loggfremvisning.

### Nødvendige kodeinnganger ved konkret oppdrag

- LIVE ruter og datavakt: `worker.py`, `autotrader_v3_live_runtime_v1.py`, `autotrader_v3_live_bar_watcher_v1.py`, `autotrader_v3_order_guard_v1.py`, `autotrader_v3_config_v1.py`.
- LIVE whipsaw og authorization: `autotrader_v3_whipsaw_live_v1.py`, `autotrader_v3_whipsaw_optin_b_20261013.py`, `docs/V3_LIVE_WHIPSAW_VOLATILITY_PAUSE_2026-10-13.md`.
- Closed-bar strategies: `autotrader_v3_macd_histogram_v1.py`, `autotrader_v3_aen21_sticky_fast_exit_v1.py`, `autotrader_v3_macd_stoch_v2.py`.
- LAB: `live_sim_lab_worker_v1.py`, `live_sim_lab_core_v1.py`, `live_sim_lab_store_v1.py`, `live_sim_lab_whipsaw_ablation_v1.py`, `live_sim_hyper_vigilant_v1.py`, `live_sim_ai_technical_trader_v1.py`, `live_sim_lab_ai_context_pairs_v1.py`, `live_sim_lab_ai_context_reviewer_v1.py`, `pages/0_Live_Sim_Lab.py`.
- Arkitektur/bootstrap: `docs/PRICEGAUGER_NEW_PROJECT_BOOTSTRAP_2026-10-06.md`; tidligere dybdehistorikk `docs/AEN_ARCHITECT_HANDOFF_2026-10-09.md`.

**Kort sagt:** Produksjonen er gjenopprettet etter 10 GB full disk, 20 GB disk på plass, LIVE-kodestack ny og frisk på Railway; Tech100-B har autorisert LIVE whipsaw, men Tech100-C hadde uavklart ordrestatus ved siste kontroll. LAB/AI er kraftig utvidet, autonomi er foreløpig kun PAPER. Første prioritet for neste arkitekt er å sikre faktisk LIVE-Saxo-samsvar, deretter måle whipsaw-effekt og vurderingen om også gull skal ha LIVE-filter. Backup/retensjon kommer senere.
