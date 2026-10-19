# V3 AutoTrader: handelskart, teknisk kontroll og etterprøvbart AI-minne

Dato: 2026-10-19. Observasjonslag, **ingen nye LIVE-handelsbeslutninger**.

## Begrunnelse
Brukeren trenger å kunne kontrollere hver AutoTrader-instans visuelt, ikke bare se
LIVE-status: utførte OPEN/ADD/REDUCE/CLOSE på markedspris, MACD 12/26/9 og
Stochastic %K/%D 14/3 under grafen. Ved fremtidige AI-inngrep må hendelsens
begrunnelse og *det eksakte datagrunnlaget AI hadde* kunne inspiseres på samme sted.

## Implementert
- Fleet: visningsbryter direkte under **hver instans**, også utenfor ekspanderen
  «Administrer instansen».
- TradingDesk: tilsvarende bryter under den valgte V3-instansens kontrollpanel.
- **Lazy** rendering: ingen kurs-/event-historikk hentes når panelet er lukket.
- Kun barer fra eksakt kanonisk instrument-ID; beregner **ferdiglukkede**
  1m OHLC til den valgte strategiens 1/2/5/10/15/30/60m-oppløsning.
  Aggregater med manglende 1m-barer droppes, ikke interpoleres.
- MACD/Stochastic gjenbruker `trading_desk_indicators.calculate_indicators`
  med de dokumenterte standardparametrene. Dette er et kontrollplott,
  ikke et løfte om full intern paritet med andre strategier som eventuelt
  bruker andre Stochastic-parametre.
- Markører leser kun `autotrader_v3_execution_events` avgrenset til eksakt
  instans og konto; disse er ordremotorens utførelseshendelser.
  Kursankeret er siste eksisterende bar-close, **ikke Saxos bekreftede fillpris**.
  Ingen SIM-event blandes inn og ingen V2-kontotransaksjoner tilordnes V3.
- `pg_v3_ai_decision_memory_v1` er en egen append-only logg:
  `decision_id`, V3-instans, eksakt Saxo-konto, instrument-ID, strategi,
  `evaluated_at`, `evidence_as_of`, SHA256 av modellens JSON-inndata,
  `model_id`, `SHADOW/LIVE`, `HOLD/REDUCE/FLAT/REVERSE`, confidence,
  fri begrunnelse og uforanderlig evidens-JSON.
  Gjenbruk av en beslutnings-ID med andre data avvises.
  Ingen fremtidsdaterte inputklokker aksepteres.
- Til fremtidig AI-integrasjon: skriv minnet samtidig som beslutningen
  beregnes, ikke i ettertid ved grafvisning. Inntil en V3-AI-manager
  virkelig finnes, viser UI «Ingen AI-inngrep dokumentert».

## Feilgrenser
- AI-forklaringer skal ALDRI genereres retrospektivt for historiske
  deterministiske handler.
- Lesetilgang til konto-/posisjonsdata er per instans og Saxo AccountId.
  Ikke send kontoidentitet, tokens eller unødvendige broker-responser til LLM.
- Normal LIVE ON/OFF, Saxo order guard, kapitalgrenser, strategimål og
  existing decision-engine er **urørt** i denne PR-en.
- Ingen ny prissamler er nødvendig for panel v1; 10/30s-varianter av PreCross
  trenger derimot separat dokumentert subminutt-prisdatastrøm.

## Veien videre: AI Manager
1. Behold deterministisk TA og feature-spine som eneste numeriske kilde.
2. Opprett kanonisk snapshot med samtidige pris-/MACD-/Stoch-/struktur-
   /volatilitetssignaler, eksakt Saxo åpen P/L, kontoverdi, spread/kostnad,
   aktiv strategi, motorens mål og faktiske posisjon.
3. Legg en AI-manager **i SHADOW først** med 60s maks eskaleringstid,
   tidligere ved stor motimpuls. Ikke trigge bare på spread-negativ P/L.
4. AI-beslutninger brukes kun via V3 target/risk/execution-adapteren, aldri
   direkte Saxo POST. Handling, modellversjon, input-SHA og resultat
   ved senere horisonter må kunne sammenlignes med samme strategi uten AI.
5. Test kostnadsjustert utfall: basal strategi vs tapstrigget AI vs kontinuerlig
   AI-evaluering. AI skal ikke tilkjennes forbedring kun fordi den lukker tap
   tidligere hvis den også kapper lønnsomme rekyler.
6. Externalisering ved behov: velg AI-modell via provider-abstraksjon,
   men behold TA, datarekonstruksjon, kontoavstemming og ordregrensesnitt
   internt for å unngå forskjellig matematisk sannhet.
