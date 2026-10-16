# Fraktal#1 · V3 LIVE-selectable multiskala rytmestrategi

Dato: 2026-10-16. Foreløpig versjon **v1 eksperimentell**; dette dokumentet dokumenterer kontrakten for arkitektens merge-review og eventuell separat LIVE-aktivering. Ingen strategi er aktivert på konto ved oppretting/merge av PR.

## Mål

En konservativ, fullt deterministisk Fraktal#1-strategi med tri-skala samsvar. Basert på kanoniske **ferdig lukkede 1-minutts OHLC** som har passert ytterligere 10 sekunder, og på faktiske bekreftede topper/bunner i pris, ikke fraktalkunst eller matematiske illustrasjoner. Gjeldende terskler er 0,05 %, 0,15 %, 0,35 % av **underliggende**, faste i V1; ingen auto-optimaliserte parametre.

Dette er en **hypotese**, ikke en demonstrert lønnsom edge eller prediksjon av menneskelige følelser. En rekursiv fraktal-regimeklassifikator, selvlikhetsscore, adaptive terskler og interaksjon med AI er ikke bygget i denne første live-kapable beslutningsmodellen.

## Beslutningsregler (V1)

- Registre: `fraktal-1` katalog → `fraktal-1-v1` V3-strategy registry.
- Kun konfigurert **1m** signalperiode. Andre perioder, inklusive Adaptiv, blokkeres eksplisitt før LIVE/SIM.
- Hold initialt eksakt kjent Saxo-inventory uten å sende historiske signaler; første fritt handlende evaluering skjer neste 1m candle.
- Inngang LONG ved **nytt bekreftet mikro-trough** i den nettopp avsluttede 1m-baren, og siste bekreftede meso+makro-sving er også trough (opp-bias), ikke eldre enn henholdsvis 60m og 240m. Mikro må være høyst 8m gammel og **ny** i denne baren. SHORT symmetrisk ved tre peaks. Etter gap starter strukturen på ny sesjon, uten arv fra forrige.
- Eksponering maksimum én Saxo-lovlig tranche (på Tech100 normalt 0,01 lot, men instrumentreglene er autoritative). Ingen pyramidering.
- Ny, bekreftet motsving på hvilken som helst av de tre skalaene ⇒ FLAT. Det er ingen direkte LONG→SHORT-flip. Etter at faktisk Saxo-FLAT er observert kan et senere selvstendig ny-signal eventuelt åpne den andre retningen.
- Inngangscooldown minst fire 1m bars siden sist åpne-signal.
- Ufullstendige/gap-baserte data, strategibytte, restart eller faktisk Saxo-inventory som avviker fra lokal target ⇒ ingen ny inngang på denne evalueringen; plasser først state i hold/realign og vent på en senere bekreftet ny bar.
- V3s eksisterende safeguards (account ownership, durable request/ordrelås, precheck, arbeidsordre, posisjon avstemming, cost guard, margin, global eksponeringsbudsjett, LIVE arm og markedsstengt sperre) forblir autoritative.
- Selve strategien er ikke Saxo-klient og kan aldri submitte en ordre: den emitterer kun target inventory.

## Risikomomenter og testsjekkliste til arkitekt

1. **Causality:** `pivot_at` brukes ikke som handelstid; `confirmed_at` avgjør hva som er kjent og kun latest closed 1m kan autorisere inngang. Ønsket ordre går videre til Saxo tidligst etter dette.
2. **Strict activation:** kontroller at ny katalog-registrering **ikke re-armer** eller bytter noen eksisterende instans/konto; brukeren velger `Fraktal#1`, `1m` og godkjenner den eksakte kontoen gjennom eksisterende LIVE-gater.
3. **State reset:** config/context switch eller risk guard alignment sletter Fraktal#1 minne; restarter tar ikke gamle signaler som ordre. SIM state `sim:` er isolert.
4. **Saxo amount:** minimum increment hentes fra `EntryInstrumentRulesV2`, ikke hardkodet til 0,01 for alle instrument.
5. **Full ownership:** V3 kontrollerer eksisterende konkret konto/UIC/AssetType, og separate CLOSE→reconciled FLAT→OPEN ved ny retning.
6. **Staleness:** ingen OPEN fra gammel bar, også når worker har pause, Saxo precheck feilet eller ordren ble risiko-vetoet.
7. **Tests:** bekreft 3-skala samsvar, kontravending gir FLAT, retning symmetrisk, reinngangscooldown, datagap, missing one-minute cadence, no double orders, restart, legal sizing og både SIM/LIVE codepath.
8. **OOS før reell kapital:** en systematisk PAPER-kohort over flere markedsregimer, samme instrument og kostnadsmodell som V3, med nettoavkastning, DD, turnover og capture ratio. Foreløpig er modellen *live-kapabel teknisk*, ikke dokumentert trygg/lønnsom å kjøre med penger.

### Arkitekten bør merke seg

Det er **ingen implementert fraktal faseprediksjon** enda. `Fraktal#1` er det første konkrete tidskausale tri-skala-samsvarsfilteret for bekreftede svingninger, som senere skal sammenlignes med en overordnet fraktal markedsregimeindikator. Ikke omtale modellen som «validert markedsfraktal» eller overlapp med generert motiv-illustrasjon i Markedsrytme.

## Utrulling

- Merge PR etter grønne tester og arkitektgodkjenning.
- Registreringen gjør strategien **valgbart** med eksisterende V3 kontroll, men endrer ikke noen konfigurert LIVE-instans og sender ingen ordre ved deploy.
- Ikke velg/arm LIVE før faktisk kontrollert Saxo-pilot og uttrykkelig tillatelse.
- Fraktalvisualisering/Markedsrytme ligger i separat PR #726, uavhengig av denne LIVE-strategiens kode.
