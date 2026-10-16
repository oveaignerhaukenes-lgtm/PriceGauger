# Unngå tap V1 — separat trygg NAV-SIM

Dato: 2026-10-16. Denne leveransen er **kun research/SIM** og er skilt fra sikkerhetskritisk LIVE-adapter i [draft PR #721](https://github.com/oveaignerhaukenes-lgtm/PriceGauger/pull/721).

## Mål og avtalt policy

- MACD 2m definerer mulige LONG/SHORT-innganger og ny inngang etter FLAT.
- Tapstrigger: −1 % av modellert inngangsmargin for den gearede posisjonen.
- Aktiver gevinstsikring ved +2 % netto marginavkastning; da gir 10 % tilbakefall fra høyeste opparbeidede gevinst en exit.
- Suksessmål: netto konto-NAV i NOK etter spread, kurtasje, slippage og finansieringskostnader. Simulerer ett kontrakttrinn om gangen.
- FLAT når datagrunnlag/forventet prisbevegelse er for lite til å rettferdiggjøre modellert retur og kostnader.

## Funksjoner

- `autotrader_v3_avoid_loss_v1.py`: ren risiko-/reentry-policy.
- `autotrader_v3_avoid_loss_sim_v1.py`: kausal NAV-simulering på ferdige kanoniske 1m-candles, modellert margin og kostnader. Kontrollerer verste prisbevegelse først innenfor en 1m-bar; gjelder også selve åpningsminuttet. Verklige stop-fills kan likevel bli dårligere ved gap og slippage.
- `autotrader_v3_avoid_loss_lab_ui_v1.py`: eget Live-Sim Lab-panel med faktisk 1m-markedsdatasett og TradingView-lignende graf for NAV, antall handler, drawdown og netto handel-P/L.
- Tester for policy, margin, reentry, fee-sensitivitet, tidskronologi og NAV/kostnader.

## Tydelig sikkerhetsgrense

Denne PR-en importerer ikke Saxo LIVE-klienten, legger ikke inn en V3 LIVE-strateginøkkel, endrer ikke `worker.py`, `autotrader_v3_live_runtime_v1.py`, ordreguard, konto, position, arming eller aktivt instrument. Dermed er ikke −1 % noe løfte om faktisk stop i produksjon. Valgene i UI gjelder bare historisk sim.

LIVE-adapteren **må ikke deployes** før ekte Saxo-responser er verifisert read-only: `PositionId` (individuell posisjon), `FinalFill/Confirmed` med matching `PositionId` og faktisk fill-mengde, kostnader i korrekt NOK-kontovaluta, pålitelig og fersk quote-tid, immutabel inngangsmargin og robust STOP_PENDING→CLOSE→FLAT med restart/gap/API-timeout. Dette er ikke dokumentert med faktiske konto-responser fra denne sesjonen.

Saxo-kontrakt referanser:
- https://www.developer.saxo/openapi/referencedocs/port/v1/positions/get__port
- https://www.developer.saxo/openapi/learn/audit-orderactivities
- https://www.developer.saxo/openapi/referencedocs/trade/v2/orders/post__trade__precheck

Rettet feil i **draft #721**: Feilaktig `OpeningDirection` for individuelt `PositionBase`; den er dokumentert for nettposisjoner, ikke individuell `PositionStatic`. For fullfill er Saxo `Status=FinalFill`, `SubStatus=Confirmed` (ikke `Executed`). Ordrebekreftelsen må samsvare med individuell `PositionId`. Selv med grønne fixture-tester kan denne koblingen ikke live-sertifiseres uten kontrollerte sanne broker-responser.

Kriterier for å kalle V1 LIVE-klar: undersøk faktisk rapportert Saxo-P/L, margin og quote, verifiser API-feltskjema, deretter kontrollert forsøk med liten eksponering som **brukeren eksplisitt velger**. Ingen automatisk opparming eller endring av de fire eksisterende LIVE-instansene.
