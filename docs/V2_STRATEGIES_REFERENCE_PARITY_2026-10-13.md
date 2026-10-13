# V2 strategies · MACD Flip referanse (2026-10-13)

## Beslutning

V2 skal **ikke** bare reaktiveres. Den eksisterende enkle MACD Flip-motoren har historisk korrekt binær LONG/SHORT-kontroll på ferdige 1/2/5/15/30m-signaler, men Railway starter nå bare V3-ordreløkken. Det er sikkerhetsmessig bedre å bevare V2 som lesbar referanse, verifisere paritet og portere ren beslutningslogikk til NextGen V3. Manuell V2-reaktivering krever separat brukerbeslutning og kontroll av Saxo-konto-eierskap/ordresikkerhet.

## Ny tredje nedtrekksboks

Live-Sim Lab har tre skarpt adskilte universer:

1. **Nye strategier · MACD** — ny bryterbasert, kostnadsjustert PAPER-replay.
2. **V2 strategies** — full read-only strategioversikt + kontrollmodell mot NextGen for 1/2/5/15/30m MACD Flip.
3. **Legacy strategies** — eksisterende LiveSim-forsøk med tidligere resultater, AI, whipsaw og rapporter. Ingen historikk slettes.

V2-fanen gjenbruker `_crosses_by_action_v1` fra V2-kontrollmodellen, som bygger på samme `closed_bars_v2`/`macd_observations_v2` som `_timeframe_clock_v1` i V2 LIVE-dispatcher. Denne likheten dekker MACD **signalbeslutning på ferdig bar**, ikke garantert faktisk Saxo-fylling.

## Forskjeller som fortsatt må undersøkes

- V2 LIVE bootstrap baserer seg på faktisk Saxo-retning, men kontrollmodellen starter FLAT ved analysetidspunkt; derfor kan første intervallet avvike selv med identiske kryss.
- V2 LIVE utfører alltid reversering som CLOSE -> bekreftet FLAT -> OPEN; PAPER-replay bruker neste canonical 1m open som optimistisk fill, uten nettverksforsinkelse, partially fills eller likviditetsslippage.
- Backtest viser både brutto og estimert netto (initialt 0,08% per side + halv full antatt spread per handlet side). **Satsene er antakelser**, ikke Saxo-prisliste. Finansiering og virkelig margin er ikke inkludert.
- Ikke-forhåndskjent fremtid er sperret: signals beregnes på historiske, ferdig lukkede barer og oppnås tidligst på neste 1m open.
- V2, NextGen og TradingDesk-mål har ulike strategikoder, og rapporten beholder motor-ID.
- V2-samlekatalogen inneholder flere eksperimentelle og SHADOW-only varianter: kun 1/2/5/15/30 MACD Flip behandles som støttet referanse; resten vises som "Ikke paritetsverifisert".

## Før enhver faktisk LIVE-port

- Bygg golden-vector test på hundrevis av historiske candles: V2 `_timeframe_clock_v1` og ny V3 signalbeslutning skal gi samme handlingstidspunkt/retning; ingen framtidsinformasjon.
- Kjør simulator med faktisk markedsåpent, broker round-trip på ordre i en miljøsikker testkonto, faktisk spread, gebyr, financing og reelle parsielle fills.
- Kontrakten må ha én autorisert konto per motor; live-aktivering må være eksplisitt og skilt fra valget i SIM.
- Bekreft next-bar delay, idempotent durable request og fail-closed ved uavklart Saxo-order.
- Først deretter gjennomfør valgfri minimal LIVE-pilot. Aktive V3-strategier beholdes uendret.

## Ingen LIVE-sideeffekter i denne PR

Kun nye Python-moduler for read-only replay og UI, samt en ny menygren. Ingen ordresending, V2-loopoppstart, enable/disable, databaseendring, bytte av Saxo-konto eller eksisterende konfigurasjoner.
