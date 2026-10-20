# Product Browser — fritekst, NOK-handelstrinn og kurtasje (20. oktober 2026)

## Bruk
**Produktbrowser → Fritekst + NOK/kurtasje** (første fane).
Søk etter et hvilket som helst Saxo-søkeord, f.eks. `Gold`, `XAUUSD`,
`Silver`, `XAGUSD`. Velg en Saxo-konto, ønsket **maksimal verdi i NOK av
ett minste lovlig handelstrinn**, indikativ kurtasjemodell og antall
kandidater som skal undersøkes (6/12/20). Første søkerunde henter opptil
250 produktreferanser; kun det valgte antallet får dyre detail-, quote-,
FX- og cost-GETs. Treff som overstiger Saxos søkegrense er ikke uttømmende.

## Hva vises
- Presis `UIC + AssetType`-identitet, Saxo-konto-/produkt-kontekst.
- Saxo `IncrementSize` og `MinimumTradeSize` holdes **atskilt**:
  - NOK handelstrinn = Saxo IncrementSize × indikativ pris ×
    Saxo-verifisert contract multiplier ved behov × indikativ Saxo FX.
  - NOK minimumsordre anslås separat. `MinimumOrderValue` rapporteres
    separat fordi denominering og Saxo-precheck kan variere.
- Saxo `cs/v1/tradingconditions/cost/{AccountKey}/{UIC}/{AssetType}`,
  kun GET, for faktisk minimumsordrestørrelse og 2x denne størrelsen:
  - like eksplisitte kommisjoner → **FAST / minimum** (indikasjon)
  - omtrent proporsjonale → **PROSENTVIS / variabel** (indikasjon)
  - mellom disse → **BLANDET** (indikasjon)
  - eksplisitt `Commissions: []` og begge null → **INGEN EKSPLISITT**
  - manglende eller inkonsistent dokumentasjon → **UKJENT** (aldri 0).
  - Modellklassifiseringen er ikke et juridisk gebyrskjema: minimums-
    kommisjon, instrumentspesifikke gebyrer og spreads kan variere.
- Saxo infoPrice spread vises særskilt; 1-dags Saxo total cost
  long/short dersom levert. Finansiering, FX og andre indirekte
  kostnader må vurderes før handel.
- Kurs mot NOK hentes fra eksakt Saxo FxSpot valutakryss (f.eks. USDNOK),
  ellers blir NOK-estimatet ukjent. Futures uten contract multiplier
  får **ikke** fiktivt NOK-beløp.

## Filtrering og grenser
- «Maks. minste handelstrinn (NOK)» filtrerer verdien av **ett tillatt
  inkrement**, ikke kapital/margin ved første ordre eller samlet konto.
- «Ta med ukjent NOK-handelstrinn» står på som standard; slike produkter
  presenteres eksplisitt som uavklarte og kan filtreres bort.
- Kurtasjemodell kan begrenses til «Ingen eksplisitt»,
  «Prosentvis/variabel», «Fast/minimum», «Blandet», «Ukjent» eller «Alle».
  Filtre kjøres bare på de produktene som faktisk er inspisert.
- Generiske ord som `Gold` kan treffe «Goldman Sachs» og gruveaksjer.
  Presise XAU/XAG-aliaser prioriteres, men metadata alene beviser ikke
  at et verdipapir følger spotgull/sølv.

## AutoTrader og Saxo LIVE
Produktbrowser er **read-only research**, selv på en LIVE Saxo-konto.
Ingen ordre / `trade/v2/orders` / ny instrument-admission / endring av
autotrader LIVE authority. At en CFD eller metall-ETF finnes i
katalogen betyr ikke at V3 godtar AssetType eller at kontoen kan legge
inn minstestørrelsen. Neste operasjon før aktivering:
1. Velg eksakt UIC, AssetType, account og bekreft faktisk LONG/SHORT-
   tilgjengelighet med Saxos ikke-handlende `trade/v2/orders/precheck`.
2. Verifiser minimumsordre, margin, spread, overnight-funding, FX,
   kontraktstørrelse og avgifter i NOK.
3. Verifiser Saxo market data/ordrestørrelse i canonical V3 og
   ta produktet eksplisitt inn i live-universet via egen godkjent endring.
4. Evaluer faktiske netto kontotall, særlig med små ordre der
   minstekurtasje kan dominere.

Ingen av disse trinnene hoppes over som følge av søk.
