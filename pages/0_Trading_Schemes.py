from __future__ import annotations

import streamlit as st

st.title("Trading Schemes")
st.caption("Event-driven strategier og forskningshypoteser. Ingen automatisk execution authority i denne versjonen.")

st.header("Middle East Reconstruction Fund")
st.markdown("""
**Tese:** Bygg en liten, regional kurv før gjenoppbyggingskapitalen blir fullt priset inn, og la senere kontraktstildelinger avgjøre hvilke selskaper som beholdes og skaleres.

Dette er en **scheme**, ikke et statisk fond: universet skal utvikle seg fra bred forhåndsposisjonering til en konsentrert kurv av dokumenterte vinnere.

### Kapitalflyt
**Politisk normalisering → donor/finansiering → materialtilgang → anbud → kontrakter → omsetning → marginer**

### Fase 1 · Discovery
Kartlegg 5–15 børsnoterte, fortrinnsvis regionale selskaper med høy **reconstruction operating leverage**:
- sement, aggregat, stål og glass
- kabler, transformatorer, strømnett og sol/nødstrøm
- vannrensing, pumper og avløp
- maskiner, rubble removal og resirkulering
- lokal logistikk, havner og transport
- engineering/EPC og bygg
- telecom og annen kritisk infrastruktur

Prioriter kandidater der en stor regional kontrakt faktisk kan flytte omsetning og resultat.

### Fase 2 · Pre-position
Start med en diversifisert kurv før kontraktsvinnerne er kjent. Hver kandidat må ha dokumentert regional kapasitet eller plausibel tilgang til forsyningskjeden.

### Fase 3 · Confirmation
Score nye datapunkter fortløpende:
1. troverdig politisk avtale / normalisering
2. finansiering eller donorforpliktelser
3. åpning for materialer, maskiner og logistikk
4. prekvalifisering / anbud
5. MoU eller foreløpig tildeling
6. signert kontrakt
7. faktisk ordreinngang / omsetning

Kapital flyttes gradvis fra tematisk eksponering til dokumentert kommersiell eksponering.

### Fase 4 · Concentration
Når kontraktene materialiseres, behold de faktiske vinnerne og reduser kandidater som ikke får ordre. Et lite regionalt selskap med stor kontrakt relativt til eksisterende omsetning kan ha langt større resultatbeta enn en global entreprenør med samme kontraktsverdi.

### Kandidatscore
- **Locality** – lokal/regional produksjon og arbeidskraft
- **Capacity** – ledig/skalerbar kapasitet
- **Contract probability** – dokumentert tilgang til anbud/oppdragsgivere
- **Revenue leverage** – mulig kontraktsverdi relativt til dagens omsetning
- **Supply-chain criticality** – hvor vanskelig innsatsfaktoren er å erstatte
- **Funding quality** – styrken på finansieringskilden bak prosjektet
- **Execution risk** – sikkerhet, logistikk, sanksjoner, valuta og betalingsrisiko
- **Valuation/price response** – hvor mye av tesen markedet allerede har priset inn

Hold **sannsynlighet** og **payoff** separat.

### Autotrader-grensesnitt (senere)
Denne siden har **ingen execution authority**. En senere adapter kan konsumere strukturerte scheme-signaler, men må ligge bak eksplisitte risikorammer og egen aktivering.

Planlagt state machine:

**DISCOVERY → WATCH → PREPOSITION → CONFIRM → SCALE → HOLD → CONTRACT_LOST/EXIT**

Planlagte eventer: PEACE_PROGRESS, FUNDING_COMMITTED, ACCESS_OPENED, TENDER, AWARD, BACKLOG_CONFIRMED, PROJECT_DELAY, CONTRACT_LOST.

### Første forskningsunivers
Neste trinn er en 5–15-navns watchlist basert på **faktisk børsnotering + regional kapasitet + revenue leverage**, koblet mot offentlige anbud, kontrakter og selskapsmeldinger.
""")

st.info("Status: Research scheme. Neste milepæl er et verifisert selskapsunivers og en event/contract tracker.")
