# MACD+Stoch — versjonert forbedringsløp

Status: 15. oktober 2026. Bruker ønsker å videreutvikle **MACD+Stoch V2** med små, kontrollerte forbedringer til en velprøvd **V3**.

## Uforandret referanse: V2

- Én momentumscore: 70 % ATR-normalisert MACD-histogram + 30 % normalisert Stochastic K−D.
- Første inngang krever to ferdige candles med samme sterke signal, |score| >= 0,22.
- Oppbygging av posisjon med én Saxo-lovlig tranche per ferdig candle (under eksisterende V3-kapitalramme).
- Svakt signal |score| <= 0,10 eller motsatt fortegn mot posisjonen ⇒ FLAT umiddelbart på neste ferdige candle; mellom 0,10 og 0,22 ⇒ HOLD.
- Ingen endringer i V2-koden eller eksisterende LIVE-instansers strategi/konto/arming.

## Hypotese V2.1: Styrkende momentum kreves for BUILD

- **Én eneste strategiendring**: bare når original-V2 vil gjøre `BUILD`, krev
  `abs(score_now) > abs(score_previous) + 0.02`.
- Hvis scoren fortsatt er sterk, men svekkes, er lik, eller styrkes mindre enn 0,02: **HOLD** eksisterende posisjon, ikke øk.
- Eksisterende første `OPEN`, øyeblikkelig `OPPOSITE_FLAT`, `WEAK_FLAT`, inngangsbekreftelse og øvrige `HOLD`-tilfeller forblir **identiske med V2**.
- Har ikke innebygd ny profit-taking eller ekstra cooldown. Komposittvekter, terskler og ATR/Stoch-parametre endres ikke.
- Implementasjon: `autotrader_v3_macd_stoch_v21.py`. V3-katalog: `MACD+Stoch V2.1`; teknisk strategi-id `macd-stoch-v2-1`.
- Samme Saxo instrumentspesifikke lot/minimum og samme V3-utførelsesgrensesnitt: posisjonsbekreftelse, beskyttet CLOSE → FLAT før motsatt side, kostnadskontroll, kapitalramme, kontoeksklusivitet, LIVE-autorisasjon.
- Ingen deploy vil slå på/endre eksisterende LIVE-kontoer. Strategien er *valgbart* i LIVE og SIM.

## Hvorfor denne endringen?

Tech100-A på MACD+Stoch V2 1m (15. oktober 08:42–20:59 UTC, Railway-posisjonsreconciliation):
- 59 avsluttede FLAT→posisjon→FLAT-runder, median 4,5 minutter, 31 av 59 under fem minutter.
- Antall endringer er høyt; det er mulig at automatisk ekstra tranche under allerede avtagende score svekker faktisk utgangspris og øker risikotid.
- Bruker observerer positiv bedring, men loggene alene gir ikke korrekt Saxo fillbasert netto-P/L. Vi skal ikke påstå gevinstforbedring før dokumentert.

## Målekontrakt for progresjon V2 → V2.1 → V2.2 → V3

1. Samme Tech100-instrument, identiske inngangsbar-tidsstempler, samme 1m periode og kapitalkvote. Første test skal isolere **bare add-gating**, ikke samtidig cooldown, stop-loss eller nytt signal.
2. Først sammenlign signaler og eksponering på samme ferdige prisdata. Deretter må faktisk LIVE-evidens vurdere Saxo-fills, kostnader, antall endringer, netto kontoverdi, MFE/MAE og hvor mye opparbeidet gevinst som mistes ved exit.
3. Skill `SIM`, historisk replay og faktiske Saxo-handler. Bruk aldri sammenligning av rebased, kostnadsfri kontrollkurve og gammel konto-total som bevis for edge.
4. Etter én testperiode: vurder separat **V2.2** med kort cooldown på nye innganger etter FLAT, eller en annen *enkeltstående*, dokumentert forbedring.
5. **V3 er navnet på den empirisk beste, robuste varianten** først når netto fillbasert resultat er positivt etter samtlige kostnader på forhåndsdefinerte evaluerings- og holdoutperioder, drawdown er akseptabel og signal→faktisk broker-posisjon har stabil paritet. Ikke omdøp bare fordi en kort testperiode var lønnsom.

### Operasjonell sikkerhet

- Brukeren velger selv når og på hvilken konto en variant skal kjøres LIVE.
- Ikke øk budsjett eller gearing på grunnlag av uverifisert sim.
- Dokumentér endringer med regresjonstester og PR-er. V2 skal alltid være reversibelt sammenligningsgrunnlag.
