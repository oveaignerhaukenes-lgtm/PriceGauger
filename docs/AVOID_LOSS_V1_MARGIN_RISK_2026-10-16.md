# Unngå tap V1 — spesifikasjon og LIVE-gates

**Status 2026-10-16: RESEARCH-ONLY.** Denne PR-en innfører en ren policy, Saxo-evidensvalidator og persistente research-tabeller. Ingen LIVE-strategi registreres, konto armeres eller ordre sendes.

## Avtalte regler
- Retning: MACD 12/26/9 på bekreftede 2m-lys.
- Tap: REQUEST_CLOSE når netto P/L <= -1 % av frossen initialmargin for akkurat denne gearede posisjonen.
- Fra +2 % netto P/L aktiveres trailing på 10 % av høyeste observerte positive nettogevinst.
- En gevinsttopp på +5 % gir gevinststopp ved +4,5 %. HIGH WATER bevares ved restart.
- Etter utstopping: FLAT til nytt ferdig 2m-kryss, eller akselererende histogram pluss bekreftet breakout.
- Ingen inngang hvis estimert bevegelsesmulighet er mindre enn +2 % av margin pluss verifiserte round-trip kostnader. Dette er et filterestimat, ikke en prognose.
- Ingen pyramidering i V1. Posjonsendring eller ny Saxo NetPositionId krever ny bekreftet marginanker.
- Suksessmålet er netto endring i konto-NAV etter alle gebyrer, finansiering og valutakostnader.

## Økonomisk måling
Eksempel med frossen initialmargin 1000 NOK: -10 NOK utløser stop, +20 NOK aktiverer trailing; dersom peak var +50 NOK, utløses CLOSE ved +45 NOK.

Viktig: ProfitLossOnTrade fra Saxo er i instrumentvaluta. Bruk ProfitLossOnTradeInBaseCurrency bare etter at basevalutaen er kontrollert som faktisk NOK-kontovaluta (Saxo kan benytte klient-/gruppebase). Fratrekk TradeCostsTotalInBaseCurrency og bare dokumenterte ekstrakostnader for exit som ikke allerede er inkludert. Unngå dobbel kostnadsføring.

Saxos MarginImpactBuySell.InitialMarginBuy/InitialMarginSell med Currency=NOK er estimert inngangsmargin; lagre først marginen som en *immutable confirmed-position anchor* når varig ordrestatus, faktisk Saxo-fill og NetPositionId er reconciliert.

## Implementert i PR
1. autotrader_v3_avoid_loss_v1.py — ren -1/+2/10-policy, sticky EXIT_PENDING og MACD-2m re-entry-forslag.
2. autotrader_v3_avoid_loss_saxo_evidence_v1.py — strikt NOK P/L, kostnader, konto, UIC, posisjons-ID, ferskhet og marginverifikasjon. Ingen HTTP.
3. autotrader_v3_avoid_loss_state_v1.py — persistente research-tabeller for immutable initialmargin, high-water og stopp-latch.
4. Egne tester for feil valuta, NaN, feil lot, gamle priser, restart, exit-pending og kostnader.

## Må være på plass FØR LIVE
- Egen hurtig risikoloop, ikke avhengig av 2m signal-cadence eller en 30-sekunders V3-runde.
- Sammenkoble marginanker og order-ledger mot faktisk Saxo ORDERID/NetPositionId ETTER bekreftet fill. Ikke adopter gamle eller manuelle posisjoner med fiktivt marginbeløp.
- Utfør CLOSE gjennom V3 durable order guard og eksakt konto/UIC/asset type; aldri direkte fra forskningsmotor.
- Bekreft sanntid bid/ask, NOK-basevaluta, finansiering, fylte ordre og komplette omkostninger. Ved svak evidens: varsle UNPROTECTED, ikke hevde at stoppen virker.
- Modellér finansiering og fill timing i SIM med gearet P/L/NOK, ikke indeksprosent.
- Test gap, API-timeout, restart, avvist/ukjent ordre, re-entry og manuell posisjonsendring.
- Valider netto kontoverdi og drawdown på out-of-sample, sammenliknet med FLAT og referansestrategier.

Teknisk risiko: et programvarestopp kan ikke garantere -1 % ved gaps, slippage, ordreforsinkelse eller Saxo-/nettutfall.

Kilder: https://www.developer.saxo/openapi/referencedocs/port/v1/netpositions/post__port__subscriptions/schema-netpositiondynamic
https://www.developer.saxo/openapi/referencedocs/trade/v2/orders/post__trade__precheck/schema-marginimpactbuysell