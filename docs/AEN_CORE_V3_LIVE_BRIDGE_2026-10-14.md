# AEn Core → V3 LIVE, første fase

Dato 2026-10-14. Fem valgbare AEn-strategier i V3 LIVE og SIM:

| Strategi | Familie |
| --- | --- |
| AEn Core · MACD Hold | MACD Hold |
| AEn Core · Histogram | MACD Histogram |
| AEn Core · Hysteresis | MACD Hysteresis |
| AEn Core · MACD+Stochastic | MACD + Stochastic |
| AEn Core · Adaptive Hold | MACD Hold med deterministisk AUTO-tidsramme |

## LIVE-kontrakt
- Fast valgt start-tidsramme 1, 2, 5, 10, 15 eller 30 minutter. Adaptive Hold kan bytte disse internt etter dwell/hysterese. V3s generelle «Adaptiv» periodemeny er ikke støttet.
- Bekreftet HH/HL/LL/LH-struktur fra 5-minutts barer, 2 + 2 pivotbekreftelse.
- Maks mål om én minste lovlige Saxo-mengde per instrument, vanligvis 0,01 lot for Tech100. Ingen pyramidering, Impulse Detector, 1→2→5m-pulsstige eller AI-ordreautonomi.
- Ny LIVE-strategi bootstrappes fra aktuell Saxo-posisjon, men sender IKKE ordre på gamle PAPER-fills. Bare nye, ferdige 1m-barer kan produsere nye mål.
- Tilstand per V3-instans persisteres i PostgreSQL; ingen cross-instance deling av HH/HL-memory, sikringsnivå eller dynamisk tidsramme.
- Duplikat, missing data, manglende precheck og endrede brokerposisjoner må fail-close uten gammel automatisk re-entry.
- Eksisterende V3-autoritet, kontoeierskap, kapitalramme, kostnadssjekk, durabel ordrebokføring og CLOSE → CONFIRM_FLAT → OPEN beholdes. PR-en aktiverer ikke LIVE eller endrer eksisterende instanser/posisjoner.

## Avgrensning
Dette er den deterministiske én-enhetsversjonen av AEn Core, og ikke identiske fill-resultater som tidligere PAPER-replay. LIVE-handling kan avvike ved Saxo-kostnader, forsinkelse og bekreftet flat-før-reversering. Utvidet struktur-skalering og modifikatorer må valideres separat før implementasjon.
