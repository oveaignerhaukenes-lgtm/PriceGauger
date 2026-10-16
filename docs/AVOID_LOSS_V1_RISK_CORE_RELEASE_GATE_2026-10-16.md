# Unngå tap V1 – isolert risikokjerne, ingen LIVE-aktivering

Status 2026-10-16: **RESEARCH / NOT LIVE-READY**. Del-leveranse fra tidligere draft PR #721 inn på fersk main. Oppretter **ingen Saxo-kall, worker-loop, LIVE-registrering, ordre, kontoarming eller ordreautorisasjon**.

## Gjennomført
- `autotrader_v3_avoid_loss_strategy_v1.py`: 2m MACD-entryfunksjon (ren funksjon, ikke koblet til V3 strategy registry).
- `autotrader_v3_avoid_loss_saxo_evidence_v1.py`: rene, read-only parser-/valideringsfunksjoner for individuelle posisjoner, NOK, kostnad og margin (uten nettverkskode).
- `autotrader_v3_avoid_loss_state_v1.py`: persistenshjelpere for bekreftet marginanker, monotont gevinstmaksimum og sticky STOP_PENDING, uten runtime-kobling.
- Unit-tester for kontraktbrudd, uriktig konto/posisjon, kostnader, stop-state og restart. Den rene -1 %/+2 %/10 %-policy og NAV-SIM ligger allerede på main via #722.

## Spesifikasjon
- Ønsket stop: når verifisert netto P/L (NOK) når -1 % av frossen, faktisk inngangsmargin, *forespør* CLOSE.
- Ved +2 % netto gevinst aktiveres trailing; gi tilbake høyst 10 % av observert netto gevinstmaksimum (f.eks. +5 % → +4,5 %).
- Eventuelle stoppsignaler er verken garantert fill, garantert maks-tap eller garantert femsekunders reaksjon.

## Beviselig mangler før det kan bli LIVE
1. Faktisk autorisert Saxo-konto/ordre-lesing for `PositionId`, kontovaluta, postprecheck marginvaluta/FX, `PositionView`/reliabilitet/tidsfelt og fill-audit. Kunstige fixtures er *ikke* tilstrekkelig.
2. Avklar at `CurrentPriceLastTraded` faktisk er et pålitelig klokkeslett på brukt marked; ellers trenger vi verifisert tidsstempel for ferske handler/quotes. Slik validatoren er nå, vil fravær stoppe kontrollen.
3. Avklar `TradeCostsTotalInBaseCurrency`, fees og finansiering, uten dobbelttelling.
4. Separat risikowatcher, volum/fill-guard og CLOSE→broker-FLAT i eksisterende durable V3 ordrekjede, inklusive partial fills, restarted states, datagap, avvisninger og API-timeout.
5. Isoler og begrens broker-latens i worker med øvrige fire LIVE-instanser. Noen eksisterende instans må aldri brukes som uautorisert prøvekanin.
6. Separat live-godkjenning og eksplisitt liten konto, risikobudsjett og nødprosedyre før eventuell faktisk ordre.

## Handoff
Utviklingsgren: `feature/avoid-loss-v1` PR #721 for uverifisert LIVE-kobling. Denne trygge PR-en er et bevisst deluttrekk, ikke en godkjenning av #721. Neste arbeid må gjøres fra fersk `main`, med den dokumenterte LIVE-gaten fortsatt lukket.
