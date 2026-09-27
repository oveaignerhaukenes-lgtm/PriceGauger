# PriceGauger — handoff fra Arkitekt 14 til Arkitekt 15

**Dato:** 2026-09-27  
**Verifisert utgangspunkt:** `main` på `340e8cd03e40e443bca9a24b614696a30dd29095` (#528). Oppdater fra fersk `main` før du begynner; samtidige bidragsytere kan ha landet mer kode.

## Les dette først

1. `docs/CURRENT_STATUS.md` (øverst står den ferske Strategy Lab-statusen).
2. `docs/STRATEGY_LAB_EXECUTION_FEATURE_REPORT_2026-09-27.md` (opprinnelig krav og sikkerhetsinvarianter; beskrivelsen av *manglende* budsjettkjede der er historisk etter #528).
3. Denne handoffen og aktuell kode/tester på fersk `main`. Eldre arkitekthandoffer er bakgrunn, ikke fasit om driftstilstanden.

## Brukerens mål og nåværende grense

Brukeren ønsker at en godkjent Strategy Lab-plan skal kunne sendes til LIVE på et uttrykkelig valgt Saxo-produkt med NOK-budsjett og eksponeringsprosent, og at kontrollene i samme strategitråd skal styre kun den tilhørende posisjonen. Brukeren ønsker at utviklingsoppdrag følges gjennom testing, PR, merge og faktisk deploy, uten rutinemessige stopp. **Ingen handling i denne handoffen gir tillatelse til å plassere en reell Saxo-ordre på brukerens vegne.** En eventuell LIVE-ordre krever brukerens uttrykkelige handling i produktet og gyldige autoritetsporter.

## Hva som faktisk er levert

| Leveranse | Status ved handoff |
| --- | --- |
| #527, `5524dcd`: reparasjon av to syntaksfeil i Strategy Lab og strategichat; budsjett/eksponering til planforslag | Merget og deployet |
| #528, `340e8cd`: eksakt Strategy Lab-scope, immutable handoff og varig OPEN-proveniens i samme transaksjon som canonical request | Merget og deployet |
| Budsjettgrense | Føres gjennom canonical sizing, alle Saxo-precheck-kandidater og siste precheck før eksisterende durable submit |
| LIVE OPEN API | Finnes internt i `strategy_execution_open_v1.py`; eksakt enrollment/produkt, konto, market-open, flat tilstand, motstridende ordre og gates må bestås |
| CLOSE fra management intent | Consumer bruker eksisterende durable manual-close-løp, eksakt reconciled posisjon og idempotent kontroll-ID; ack fra PENDING via ACCEPTED til EXECUTED/REJECTED |
| Trailing profit, scale-down, stop-loss | Intents kan lagres, men consumer avviser dem eksplisitt; knappene er deaktivert i UI |
| LIVE OPEN i Strategy Lab UI | **SPERRET:** `live_open_budget_supported_v1(...)` returnerer fortsatt `False`; ingen ny LIVE-autoritet er åpnet |

Lokalt ble `python -m compileall -q .` og hele pytest-suiten kjørt med **1673 beståtte tester**. GitHub CI på #527 og #528 var grønn før merge. Railway web, worker og stream rapporterte `SUCCESS` etter #528; web ble røykprøvd i nettleser med Strategy Lab DRAFT-form. Ingen godkjente planer var tilgjengelige ved røykprøven, så kontrollpanelet under en godkjent plan ble ikke visuelt validert i produksjon. Eksisterende varsler om manglende Natural Gas-historikk/futures-rollover i streamlogger var ikke nye Strategy Lab-feil. Ikke påstå at LIVE OPEN eller kontrollene er produksjonsprøvd med ekte ordre.

## Hvorfor OPEN fortsatt er sperret

`budget_nok * exposure_pct / 100` behandles foreløpig som et **hardt NOK-notionaltak**. Saxo precheck kan måle en MARKET-ordre innenfor taket mens endelig fill/slippage eller FX-omregning skyver faktisk notional over det. En SHORT limitpris er ikke i seg selv et øvre tak for fill-notional. Vi har ikke bevist at egnet limit/FOK/IOC-policy støttes for dette konkrete Saxo-produktet, eller hvordan kansellert/delvis fylt ordre skal reconciles mot taket. Derfor skal neste arkitekt **ikke** bare endre `live_open_budget_supported_v1` til `True` eller ta bort taket. Avklar med brukeren først dersom det kreves et valg mellom absolutt notionaltak, marginallokering eller en eksplisitt toleranse for avvik. Gjør i mellomtiden all mulig implementasjon og verifikasjon som er uavhengig av beslutningen.

## Nærmeste arbeidsoppgaver

1. Inspiser gjeldende `main`, eksisterende Saxo ordretyper og aktuell produktstøtte. Utform og test en fill-sikker budsjettpolicy, inkludert FX, delvis fill, avvisning og reconciliation. Bind det faktiske utfallet til originalt scope/proveniens. Bevar den stengte porten inntil hele kjeden kan bevises.
2. Fullfør statusvisning per godkjent plan: READY, BLOCKED med konkret grunn, QUEUED, LIVE og CLOSED fra durable tilstand. Røykprøv panelet med en representativ, trygg godkjent testplan.
3. For de tre resterende kontrollene: bygg reell **scope-isolert** håndtering på eksisterende canonical execution-/management-kjede eller hold dem eksplisitt utilgjengelige. `autotrader_risk_control_v2.py` har global `config_id=1`; ikke skriv Strategy Lab-trådspesifikke stop/trailing-verdier dit. Scale-down mangler canonical partial CLOSE og trenger eget durable reduksjons- og reconciliation-løp. Ingen egen Saxo POST-sti fra UI.
4. Vurder durable notification outbox først etter tilstandsoverganger (approval required, queued, filled, rejected, stop/invalidation), med push som første konsument. Ikke send forhåndsvarsler som om en ordre er fylt.
5. Oppdater `docs/CURRENT_STATUS.md` ved reell statusendring. Sjekk samtidig annen pågående AutoTrader V3-/TradingDesk-jobb på fersk `main` før du endrer delte moduler.

Viktige filer: `strategy_execution_scope_v1.py`, `strategy_execution_adapter_v1.py`, `strategy_execution_budget_v1.py`, `strategy_execution_open_v1.py`, `strategy_execution_control_consumer_v1.py`, `autotrader_fast_live_runtime_v2.py`, `autotrader_open_sizing_v2.py`, `autotrader_live_open_legacy_v2.py`, `autotrader_automanage_dispatch_v2.py`, `pages/0_Strategy_Lab.py`; tester `tests/test_strategy_open_budget_v1.py`, `tests/test_strategy_live_open_budget_chain_v1.py`, `tests/test_strategy_execution_open_v1.py`, `tests/test_strategy_execution_control_consumer_v1.py`.

**Invarianter:** Strategichat/DRAFT har ingen brokerautoritet. Godkjent plan er immutable input, ikke ordre. Eksakt `strategy_key:plan_id`, handoff, pilot, konto, UIC, asset type, NOK-budsjett og eksponering må matche; feil i ett felt blokkerer. CLOSE må identifisere *samme* reconciled posisjon; ingen handling på tilsynelatende like produktnavn. All brokeraktivitet går gjennom eksisterende durable execution, gates, watchdog og reconciliation. Ikke endre aktive posisjoner, restart eller LIVE-gates bare for å validere UI.

## Arbeidsmåten som fungerte i denne runden

- Begynn med fersk `main`, les lokale repo-instruksjoner og se etter skitne worktrees. Opprett eget isolert worktree; en parallell utvikler kan ha ucommittede chart-endringer i hoved-worktree.
- Utled neste steg fra brukerens allerede uttrykte mål. Gjennomfør autorisert, reversibel kode- og dokumentasjonsjobb helt til PR, grønn CI, merge og deploy uten å spørre «skal jeg fortsette?» ved hvert delsteg. Be om avklaring bare ved faktisk manglende beslutning om risiko/økonomisk mandat, og legg fram et konkret gjennomarbeidet valg først.
- Gi korte fremdriftsmeldinger med funn eller beslutninger underveis. Fiks blokkerende feil når de dukker opp; syntaksbrudd ble for eksempel reparert i en separat, rask #527 før hovedintegrasjonen #528.
- Test relevante grenser og hele suiten for execution-endringer. Kontroller PR-diff og CI, merge mot forventet head, følg alle Railway-tjenester til `SUCCESS`, inspiser relevante runtime-logger og prøv faktisk UI når mulig. Et grønt deploy er ikke alene bevis for at en knapp virker.
- Rapporter presist hva som er kode, hva som er observert i drift, og hva som fremdeles er sperret. Sikkerhetsporter som stopper ordre er et korrekt utfall inntil ordreutfallet er forsvarlig bevist.

## Ferdigkriterium for LIVE-promotering

En ende-til-ende-test må vise `APPROVED handoff -> eksakt LIVE enrollment/scope -> sizing og Saxo precheck under valgt bindende budsjettpolicy -> durable request -> ordre-/fill-reconciliation -> UI-status`, med negative tester for alle kryssede tråder, avvikende produkt/konto, delvis fill og restart. Først etter dette kan OPEN-gaten vurderes åpnet. Reell bruk krever fortsatt en eksplisitt ordrehandling fra kontoeier i UI.
