# V3 LIVE: sikker reset av gammel RESERVED-ordre

## Hvorfor av/på ikke løser det
V3 lagrer ordrelåsen i `autotrader_v3_order_guard` i PostgreSQL, ikke i minnet til worker. En omstart må ikke oppheve en ordre som kan være sendt til Saxo.

## Statuspanelet (PR #698)
1. Åpne den flytende AutoTrader-statusen nederst til høyre.
2. På en bestemt instans vises **Kontroller / reset lås** bare hvis ordren er `RESERVED` eldre enn to minutter, uten Saxo OrderId. Ingen reset for `SUBMITTING`, `SUBMITTED` eller `UNKNOWN`.
3. Bruker skriver operatørkoden (skjult inndata). Koden må være satt i Railway **pricegauger-web** som `PG_V3_ORDER_RECOVERY_PIN` (minst 12 tegn). Ikke legg kode i GitHub, logg eller handoff.
4. Server kontrollerer eksakt instans/konto/UIC, at reservasjonen er gammel, at posisjonen fortsatt er lik den før forsøkt ordre, og at Saxo ikke har aktive ordre på kontoen. Ved manglende eller tvetydig informasjon blir ordren **ikke frigjort**.
5. Dersom alt stemmer, endres kun akkurat denne gamle reserverte forespørselen atomisk til `REJECTED` med revisjonsspor. **Ingen Saxo-ordre sendes fra knappen**.
6. Worker sjekker heretter overgang `RESERVED -> SUBMITTING` atomisk. En samtidig reset kan derfor ikke få den til å sende ordren etterpå.

## Etter reset
Neste nye strategibeslutning kan igjen sette en LIVE-ordre dersom instansen er armert. Å frigjøre låsen betyr IKKE å gå flat og betyr IKKE at strategien skal være deaktivert.

## Hendelse 13. oktober
Tech100-C (`f115f072-036f-5e3b-a61e-459816070186`) hadde `RESERVED` siden 01:58:58 UTC, ingen OrderId, Buy 0.01, faktisk -0.02 / forventet -0.01. Samtidig meldte PostgreSQL `DiskFull`. Det er et plausibelt eksempel på en *før-submit*-reservering, men knappen skal utføre ny Saxo-verifikasjon før frigivelse.

## Kan ikke resettes automatisk
En `SUBMITTING`, `SUBMITTED` eller `UNKNOWN` kan allerede ha nådd Saxo. Operatør må innhente konkret ordre-/fill-historikk og en ny eksakt posisjon før låsen får endres. Ikke bruk generelt SQL-`DELETE`/`UPDATE` for å tømme sperrene.
