# Fraktaltempo: separat SIM-utvidelse til Rytmebygg og RytmeTrend (19.10.2026)

## Opplegg / hvorfor en egen PR
Dette er **en stacked PR mot PR #753**. Eksisterende rytmestrategier og Fraktal#1 endres ikke. Vi vil teste om fraktalens egen bekreftelsesrytme er en nyttig *tempoindikator*, uten å introdusere komplisert, uetterprøvbar orderlogikk.

### Kilder / kausalitet
- Bruker nøyaktig de tre Fraktal#1-tersklene **0,05 %, 0,15 %, 0,35 %** fra `autotrader_v3_fraktal1_v1.py` via den delte `confirmed_turns_v1`-motoren.
- `causal_closes_v1` tar bare med ettminuttsbarer som var fullstendige da beslutningen tas (+10s safety). Hendelser dateres etter **confirmed_at**. Tidligere `pivot_at` brukes aldri som før-kunnskap.
- Sjekker kontinuerlige siste 13 1m-barer, 4 nye bekreftede mikroturns i samme segment, og friske mikrosvinger (maks 8m), meso (60m) og makro (240m). Manglende bevis => UNKNOWN.
- Bruker median **tid mellom bekreftede mikro-vendinger**. Tempo FAST hvis median <=4m og alle tre skalaer peker likt; NORMAL hvis median <=9m og mikro/meso peker likt; ellers SLOW.
- Det er *beslutnings-/oppbyggingsrytme*, **ikke** Saxo polling-rate eller et prediktivt tidspunkt for neste topp/bunn.

### To isolerte kandidater (SIM/PAPER only)
| Kandidat | FAST | NORMAL | SLOW | UNKNOWN |
| --- | --- | --- | --- | --- |
| Rytmebygg + Fraktaltempo | tillat baseline OPEN/BUILD 1m | hver 2m | hver 4m | ingen ny eksponering |
| RytmeTrend + Fraktaltempo | tillat baseline OPEN/BUILD 5m | hver 10m | hver 15m | ingen ny eksponering |

- **Exit / full FLAT / TRIM / HOLD** fra original strategi er alltid uendret og går først.
- Aldri større tranche, aldri flip direkte, aldri høyere eksponering enn baseline. V3s broker/capital/pending-order sikkerhetsmekanismer berøres ikke.
- Katalog: `rhythm-build-fractal` og `rhythm-trend-fractal`. Ingen endring i opprinnelig `macd-stoch-rhythm-build`, `rhythm-trend-1` eller `fraktal-1`.
- SIM-rute gjennom normal V3 closed-bar dedup/cursor, med egen trader-instans og konfigurert signalperioden 1m. Begge har `live_route_enabled=False` og eksplisitt LIVE-forbud i konfiguratoren, selv om de kan vises i katalogen.

### Evaluering som kan avgjøre om modellen er bedre
- Replay samme markedstidspunkt på alle fire modeller (to originaler + to fraktaltempo), og relevante kontroller MACD+Stoch V2.1/AEn#2.1.
- Samme initialkonto, instrument, spread, finansiering, slippage, margin/tak og broker-tranche.
- Rapporter fra **bekreftet** data ved hver beslutning: regime, fraktaltempo, median bekreftelsesintervall, sving-samsvar, valgt interval, faktisk beslutning, realisert etterfølgende P/L.
- Sammenlign nettoavkastning og drawdown for 12–16. oktober og flere regimeperioder. Walk-forward og ablation: ingen fraktal, kun mikrofrekvens, mikrofrekvens+skalasamsvar.
- Ingen «best-of»-selvvelging på samme historikk som score. En signifikant forskjell mellom kontroll og kandidat er nødvendig før vi vurderer separat LIVE-pilot.

**Ikke automatisk merge/deploy av basis-PR #753, og ingen endring på eksisterende LIVE-kontoer.**
