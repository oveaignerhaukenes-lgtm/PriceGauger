# Rytmebygg og RytmeTrend#1: LIVE-ruteklar, ikke aktivert (19.10.2026)

## Hva som er gjort
- **Rytmebygg v1:** Beholder MACD+Stoch V2 sine 70/30 signalkriterier, 2-bar åpning og umiddelbar FLAT. 12 x 1m prisendringer bekrefter når én tranche er tryggere enn pyramidering; trendstruktur kreves før bygg. Eksisterende LIVE-rute åpnes, men kontoer armeres ikke.
- **RytmeTrend#1:** 15m MACD er makroretning; nøyaktig tre komplette 5m-lys bekrefter HH/HL eller LL/LH; 13 sammenhengende avsluttede 1m-lys vurderer retningskvalitet. OPEN én Saxo-lovlig tranche ved samsvar, BUILD bare ved ny avsluttet 5m-grense, aldri over tre trancher; støy reduserer til én; motsatt 5m-struktur eller 15m-regime FULL FLAT; ukjent data FULL FLAT.
- Begge bruker **samme** canonical 1m-data, den eksisterende V3 closed-bar-cursoren og broker-kapital-/margin-/pending-/ordreprecheck. Endring av 15m regime er del av LIVE/SIM kontekstnøkkel så gammel target ikke gjenbrukes.
- Normal Rytmebygg er knyttet til **1m**, RytmeTrend til **1m signal og 15m makro**. Mellomskalaen er fast 5m. Fraktal#1 forblir SIM.
- *Live ready* betyr teknisk tilgjengelig i katalogen ved eksplisitt manuell autorisering. **Ingen Saxo-handler, LIVE-arming, kontovalg eller risikoendring er utført av PR.**

## Kontroll før ekte konto
1. GitHub pytest-regresjon og runtime-route-test for begge, inkl. datagap, samtidige timeframe-signaler, max eksponering og FULL FLAT.
2. Arkitekt sammenligner faktisk Saxo-kostnad/spread og P/L for samme periode mot MACD+Stoch V2.1 og AEn#2.1 (kontroll). Ikke trekk slutninger om netto profitabilitet fra kode-/CI-tester.
3. Tilordne en **separat**, liten pilotkonto og godkjenn LIVE/ramme eksplisitt først etter gjennomgang. Ingen automatisk overgang av eksisterende kontoer ved merge.
4. Følg Saxos fylle- og transaksjonsdata. Feil/uklarheter gir ikke grunnlag for større posisjoner.

## Sikkerhetsinvarianter
- Ingen data etter beslutningsøyeblikket, ingen retrospectively recognized pivot ved sin historiske topp/bunn.
- Manglende/duplisert 1m OHLC hindrer oppbygging; feilet høyereperiode-data fører til FLAT, ikke ventende add.
- LIVE-ordre krever normal Saxo-authority, margin, policy, oppgjør og én ordre i gangen. Motgående posisjon først FLAT, aldri direkte flip.
- Dette er **ikke dokumentasjon på positiv forventet avkastning**. Det krever kronologisk replay med spread, finansiering, fillavvik og drawdown.
