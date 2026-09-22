from __future__ import annotations

import streamlit as st

st.title("Trading Schemes")
st.caption("Event-driven strategier som kan forskes, måles og senere kobles til AutoTrader med eksplisitt authority.")

st.header("Middle East Reconstruction Fund")
st.info("Status: RESEARCH / MANUAL ONLY · Ingen execution authority")

st.markdown("""
### Tese
En troverdig overgang fra krig til varig normalisering kan utløse en flerårig gjenoppbyggingssyklus. Strategien forsøker å posisjonere seg før kontraktsinntektene er fullt priset, men skalerer bare når politiske, finansielle og operative milepæler faktisk materialiseres.

### Verdikjede
**0 · Normalisering** — finansiering, banker, forsikring og logistikk  
**1 · Rydding** — anleggsmaskiner, rubble removal, gjenvinning og UXO-relaterte tjenester  
**2 · Nødinfrastruktur** — vann, pumper, generatorer, kabler og midlertidig kraft  
**3 · Materialer** — sement, aggregat, stål og glass  
**4 · Infrastruktur** — vei, strømnett, vann/avløp og telekom  
**5 · Bygging** — engineering, EPC og entreprenører  
**6 · Normal økonomi** — bolig, retail, banker, transport og telekom

### Signalmodell
Vi skiller mellom **sannsynlighet** og **økonomisk eksponering**. Et selskap er ikke interessant bare fordi det kan delta i reconstruction; kontraktene må være store nok relativt til selskapets omsetning/markedsverdi til å kunne flytte resultatet.

Foreslått event-stige:

**våpenhvile/rammeverk → finansieringsløfter → material-/grensetilgang → anbud → kontrakt → ordreinngang → inntektsføring**

Tidlige ledd gir potensielt best asymmetri, men størst politisk risiko. Senere ledd gir høyere sikkerhet, men mer av reprisingen kan allerede være tatt.

### Kandidatscore
Hvert selskap skal senere scores på:
- direkte MENA- og lokal produksjonseksponering
- reconstruction-relevant omsetning
- kontraktens potensielle størrelse relativt til selskapet
- kapasitet og geografisk/logistisk nærhet
- dokumentert offentlig/EPC-erfaring
- finansierings- og motpartsrisiko
- sanksjons-/jurisdiksjonsrisiko
- verdsettelse før eventet
- likviditet i aksjen
- bekreftet ordreinngang etter eventet

### Kapitalmodell
Strategien skal støtte **probe → evidence → scale**, ikke binært inn/ut. Tidlig politisk bedring kan åpne liten observasjonseksponering; dokumentert donorfinansiering, tilgang og kontrakter kan øke conviction. Regresjon i fredsprosess, stengt tilgang, finansieringssvikt eller kansellerte kontrakter reduserer tesen.

### Guardrails før AutoTrader
AutoTrader-kobling skal være en separat senere milepæl. Denne siden får ikke ordre-API, Saxo-kall eller execution authority. Før automatisering må strategien ha maskinlesbare signaler, univers, datakilder, backtest/event-study, posisjonsgrenser, invalidasjonsregler og audit-logg.
""")

st.subheader("Forskningspipeline")
st.dataframe(
    {
        "Modul": ["Universe", "Exposure map", "Event engine", "Scoring", "Event study", "Portfolio construction", "AutoTrader adapter"],
        "Neste leveranse": ["30–50 børsnoterte kandidater", "Selskap → land → sektor → reconstruction-fase", "Maskinlesbare milepæler og kilder", "Reconstruction exposure / company size", "Historisk reprising rundt fred/finansiering/kontrakt", "Probe/evidence/scale + risikobudsjett", "Kun etter validering; eksplisitt authority"],
        "Status": ["Planlagt", "Planlagt", "Planlagt", "Planlagt", "Planlagt", "Planlagt", "Låst"],
    },
    use_container_width=True,
    hide_index=True,
)
