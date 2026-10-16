# PriceGauger v3 — handoff: Unngå tap V1
**Dato:** 2026-10-16. **Repo:** `oveaignerhaukenes-lgtm/PriceGauger`. **Gren:** `feature/avoid-loss-v1`. **PR:** https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/721 (DRAFT). **Produksjon:** https://pricegauger-web-production.up.railway.app

## Oppdrag og brukerens beslutninger
Brukeren ønsker å minimere tap og fange lønnsomme bevegelser, ikke maksimal treffprosent. **Måltall: langsiktig økning i Saxo-kontoens netto NAV i NOK etter alle kostnader.** Ikke underliggende indeksprosent, historisk «SHADOW»-retur eller prosent av hele kontoen for hver enkelt stop.

**Unngå tap V1:**
- Én lovlig Saxo-handelsenhet, ingen pyramidering. MACD 12/26/9 **2m**, ferdige candles, for inngang ved kryss eller akselererende histogram sammen med bekreftet breakout.
- Første tapsstopp ved **−1 % av gearet posisjons P/L i forhold til frossen inngangsmargin**.
- Ved **+2 % netto avkastning på samme margin** aktiveres high-water trailing; lukk når 10 % av høyeste hittil observerte **opparbeidede gevinst** er gitt tilbake. Topp +5 % gir stop +4,5 %, topp +2 % gir +1,8 %.
- Posisjonen forblir FLAT ved støy/utilstrekkelig forventet bevegelse. Etter exit: vent på nytt bekreftet 2m MACD-signal, ikke samme gamle kryss.
- Disse prosentene er **planlagte triggers**, ikke garanterte fill-priser eller maksimal faktisk tapsprosent. Gjør aldri risikogaranti.
- Fire LIVE V3-instansar kjører i produksjon. **Ikke bytt, armer, flytt konto, løft cap, eller endre aktive posisjoner uten uttrykkelig tillatelse.**

## Hva som faktisk er pushet
Alle endringer er committet og pushet til GitHub-grenen i PR #721. **PR står DRAFT og er ikke merget/deployet.** Dette er bevisst fordi Saxos produksjons-API, posisjonsidentitet og stop-utgang må ende-til-ende-valideres før kapital kan utsettes.

Implementerte moduler:
- `autotrader_v3_avoid_loss_v1.py`: ren, deterministisk margin-normalisert P/L policy, høyvannmerke og sticky STOP_PENDING, MACD-2m re-entry evaluering.
- `autotrader_v3_avoid_loss_saxo_evidence_v1.py`: streng P/L-validering i kontovaluta, posisjonsidentitet, timestamp, pålitelighet og rapporterte exitkostnader.
- `autotrader_v3_avoid_loss_state_v1.py`: persistente tabeller for entydig Saxo-ordre → frossen startmargin → PositionId, high water, risikolatch og re-entry-sperre; ingen tilbakerulling av topp eller utløst stop.
- `autotrader_v3_avoid_loss_strategy_v1.py`: egen én-tranche MACD 2m innsteg.
- `autotrader_v3_avoid_loss_sim_v1.py`: kausal research-SIM på reelle 1m OHLC, kostnader, finansiering, modellert gearet P/L og NETTO kontoverdi i NOK. SIM er et scenario, **ikke Saxo fill-/NAV-replay**.
- `autotrader_v3_avoid_loss_lab_ui_v1.py`: eget NAV-testpanel i Live-Sim Lab, TradingView-lignende zoom og valgbare kostnads-/marginantakelser.
- `autotrader_v3_avoid_loss_live_v1.py`: read-only Saxo observer av nøyaktig account, uic, asset_type, **individuell PositionId** (NetPositionId er ikke unik for en handel), NOK P/L, opprinnelig precheck-margin og Saxo-fill. Ved stop lar den V3s **eksisterende** durable CLOSE/FLAT-ordrekjede ta over, aldri egen ordre-POST.
- V3-strategikatalog, sizing, closed-bar driver, worker og LIVE runtime registrerer strategien. Worker foreslår risikokontroll hvert 5. sekund i **samme tråd**, ikke separat konkurrerende Saxo-ordrekanal.
- `autotrader_v3_fleet_ui_v1.py`: tydelig `PROTECTED`, `UNPROTECTED`, `STOP_PENDING`, `FLAT` og kontroll av om oppdateringen er gammel.
- `autotrader_v3_instance_controls_ui_v1.py`: sperre mot å overta allerede armert LIVE, og kontroll av Saxo FLAT og NOK før opparming.

Tester i `tests/test_autotrader_v3_avoid_loss_*.py` dekker policy, P/L, marginanker, SIM, konto/NOK, restart, re-entry, kostnad og fakes for stop-watch. Eksisterende regresjonstest for transaction cost guard ble oppdatert for optional cost assessment ved CLOSE. Dokumentert policy: `docs/AVOID_LOSS_V1_MARGIN_RISK_2026-10-16.md`.

## Hva som gjenstår — disse er **LIVE-blokkere**, ikke kosmetikk
1. **GitHub CI:** Siste GitHub Actions run på gren må være grønn. Siste kjente tidligere run 38866312439 var **1 failed / 2388 passed** pga utdatert substring-assertion i `tests/test_v3_transaction_cost_guard_v1.py`. Dette er nå fikset i commit `278a04fd799bb01de6be7cfaf158ce63fc60ad91`; kjør og kontroller på nytt med siste HEAD (kan være newer etter denne handoff).
2. **Broker-kontrakt og realisme:** Verifiser `broker.positions_exact` returform fra `port/v1/positions` med eksakt AccountKey, `PositionBase.PositionId`, `OpeningDirection`, `Amount`, `PositionView.ProfitLossOnTradeInBaseCurrency`, kostnad, `CurrentPriceLastTraded`, `CalculationReliability`, `CurrentPriceDelayMinutes`. Dette er testet med fake, **ikke Saxo produksjons- eller simuleringens sanne responser**. Kontroller at `AccountId` faktisk er samme ID-format som `e.account_id`, og at ingen posisjoner skjules pga paginering.
3. **Ordrebekreftelse:** Kontroller eksakt `broker.order_activity_exact` return schema, broker-order-id, faktisk fill/retning/mengde og om `stage_entry_preflight_v1` matcher varig ordre-reconciliation korrekt for flere livsløp. Ikke konstruer en marginanker for gamle/manuelle posisjoner.
4. **Kostnader og nevner:** Verifiser at Saxos `MarginImpactBuySell.InitialMarginBuy/Sell` er riktig **NOK initialmargin for første bekreftede posisjon**, og at `TradeCostsTotalInBaseCurrency` inkluderer/utelater eventuell faktisk lukkeavgift, finansiering og valutakomponent som forutsatt. **Ikke dobbelttrekk kostnader, ikke bruk underliggende indeksprosent.** Kun trygt med riktige ekte P/L og kontovaluta.
5. **Stoppens faktisk utførelse:** Integrationstester for forsinket Saxo, delvis fill, unknown status, konto-posisjon endret utenfor V3, API outage, prisgaps, marked stengt, restart mellom REQUEST_CLOSE og bekreftet FLAT, og kronologien fra 5-sek watchersignal til varig V3 CLOSE. Sjekk at worker-omstart ikke skaper dobbeltordre og at risiko aldri kalles «PROTECTED» ved nedetid.
6. **SIM-korrekthet:** Test perioder med manglende 1m-data, indikatorsampling, åpningsfill i forhold til MACD-kryss og konservativ intrabar stop. Verifiser mulighet for netto negativ avkastning; unngå lookahead. SIM bruker brukerdefinert teoretisk notional/margin og kan ikke erstatte eksekverings- og porteføljedata fra Saxo.
7. **Deploy:** Hold draft-/LIVE-gate til punktene over er verifisert. Før eventuell merge må eier godkjenne risikoen ved deployment på fire aktive LIVE-instansar. Dersom kun SIM/research er klart, **splitt i separat sikker research-PR** og behold LIVE-koden ute av main.
8. **Endelig evaluering:** Samme instrument, samme historiske vindu, netto NOK konto-NAV og faktiske fills; sammenlign med MACD+Stoch V2/V2.1, FLAT-kontroll og out-of-sample. Strategien har ingen bekreftet lønnsomhet ennå.

## Drift og referanser
- GitHub PR: https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/721
- Ingen LIVE-konfigurasjonsendringer utført av denne oppgaven. V2/V3 eksisterende strategier skal fortsette i egne Saxo-kontoer som før.
- Railway project: `482dad8f-efc5-415a-b1f7-99f45cb2bd7b`, environment `9a9b7cc6-1dd0-4044-a0f0-221b06138e8f`, V3 worker service `5267feed-b5cb-4f85-a24a-0c5124664b59`. Bruk `environment_status` og `get_logs` etter safe deploy.
- Relaterte historiske undersøkelser: MACD+Stoch V2.1 [PR #720](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/720); LIVE vs SHADOW signal-paritetsundersøkelse [issue #716](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/issues/716).
- Handoff første inngangsfil for ny tråd: **denne filen**. Oppdater med ny HEAD, CI og eventuelt API-valideringsfunn i neste økt.

## Instruks til neste arkitekt
Begynn med siste HEAD og CI i PR #721. Verifiser Saxo/OpenAPI felt mot faktisk, autorisert respons og kjør feilscenarioene. Prioriter å beholde eksisterende kontoer trygge. Rett tekniske feil i PR før merge. Hvis LIVE-evidensen mangler, ikke fremstille arbeidet som fullført LIVE eller endre brukerens aktive Saxo-strategier. Hvis nødvendig, merge kun en isolert, bevist trygg research/SIM-del. Dokumenter nøyaktig hva som er validert og hva som gjenstår.
