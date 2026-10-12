# V3 MACD+Stoch v2 – composite momentum

**Strategi-ID:** `macd-stoch-v2`. Beholder `macd-stoch-v1` uendret.

## Signal og beslutning

MACD-histogrammet er `observation.macd - observation.signal`, normalisert til [-1,+1] som `tanh(2 * histogram / ATR14)`. ATR14 beregnes fra ferdigstilte OHLC-barer for strategiens valgte signaltidsramme. Stochastic beregnes med K14 og D3, og K–D-differansen normaliseres til [-1,+1] som `tanh((K-D) / 20)`.

Samlet signal: `score = 0.70 * macd + 0.30 * stochastic`.

- Fra FLAT: krever **to** ferdige signalbarer med samme retning og score >=+0,22 for LONG eller <=−0,22 for SHORT. Bygger én Saxo-lovlig lot-tranche per ny lukket bar.
- Eksisterende posisjon: ved negativt signal mot en LONG (eller positivt mot SHORT) lukkes målposisjonen direkte til **FLAT**. Ingen direkte LONG↔SHORT-flip; ny retning må kvalifisere på senere lukket bar.
- Svak score |score| <=0,10: målposisjonen settes FLAT, for å motvirke overtrading i retningsløs handel.
- Mellom 0,10 og 0,22: behold eventuell eksisterende posisjon i samme retning; ingen pyramidering.
- Ved sterk bekreftet score og samme retning: maks én tranche ekstra per lukket bar, innenfor `max_inventory`, Saxo minimumslot og gjeldende kontos kapitalgrense/precheck.
- Før ATR/Stochastic er klar, eller ved ikke-endelige observasjoner: gå til FLAT.

**Viktig:** Dette er en enkel vektet modell, ikke Schaff Trend Cycle og ikke en empirisk optimalisert indikator. 70/30-vekter og terskler er foreløpige **testparametere**, ikke dokumentert fordel. Kombinasjonen kan fortsatt handle for mye i konsolidering; whipsaw-filteret er et separat eksperiment og er IKKE aktivt i V3 LIVE.

## Registrering og UI

- V2 ligger som en **egen** strategi i V3-katalogen, felles SIM/LIVE closed-bar driver og Saxo-lovlig instrument-sizingskjede. Ingen eksisterende traderinstans eller LIVE-motor endrer strategi ved deploy.
- Strategivelgeren i den felles V3-kontrollen, brukt både i TradingDesk og Fleet, har et lite `❔`-ikon. Popupen viser navn og definisjon for den **valgte** strategien, også alle eldre katalogstrategier.
- LIVE-modifikatorenes capability contract er **uendret** (kun reset-on-loss er LIVE-klar). Whipsaw kan ikke tvinges gjennom som en LIVE-option.
- Gjenbrukt durable strategy state og duplicate-bar guard. Begge krever fersk bar. Ombytning av strategi oppdaterer fortsatt eksisterende runtime context-guard uten å slette ordreavstemmingslåser.
- Ikke aktivert på eksisterende LIVE-kontoer. Må velges og lagres eksplisitt.

## Kritisk vurdering før bruk med kapital

En samlet score kan være mindre støyfølsom enn et rått MACD-kryss, men begge komponentene er avledet fra samme OHLC-prisserie, ikke uavhengig informasjon. Normalisering, trading-cost og signalbar-latens bør sammenlignes fremoverrettet mot `macd-stoch-v1` og ren MACD 5m. Særlig risiko: whipsaw ved terskelkryss, hyppige flat/åpne-runder, uventet regimebytte og sterk momentum i feil retning. Kontokontroller, Saxo-precheck og eksisterende failsafe beholdes.
