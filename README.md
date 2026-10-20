# Inatur-varsler – elgjakt i Nordland

Et lite program som sjekker akkurat dette Inatur-søket: **elg + Nordland + bare ledige storvilttilbud**.

Programmet er laget for å:

- Søke etter jaktfelt/tilbud som kommer inn i listen.
- Sjekke kortseksjonen «Kjøp/søk jakt her» også på tilbud som allerede er publisert, slik at nye kort eller endringer i salgsstatus kan oppdages.
- Sende pushvarsel på iPhone gjennom **ntfy**, med jaktfeltnavn, kommune (når stedet kan leses) og trykkbar Inatur-lenke.
- Huske forrige kontroll slik at du ikke får varsel om det samme uforandrede tilbudet igjen.
- Kontrollere ca. hvert 15. minutt med GitHub Actions, også når telefonen er låst.

**Viktig:** Inatur laster søkeresultatene med JavaScript. Løsningen bruker derfor Playwright. Det er ikke mulig å fullteste mot Inaturs levende nettside fra miljøet der filene ble laget. Koden og sammenligningen er lokalt testet med eksempler, men det **må gjennomføres en første ekte kjøring** på GitHub. Eventuelle endringer i Inaturs nettside kan kreve tilpasninger. Ingen kjøp foretas.

## Oppsett: ca. 6 steg

### 1. Installer appen på iPhone

Installer **ntfy** fra App Store (utgiver/appen `ntfy`, se https://ntfy.sh). Tillat varsler.

### 2. Velg et hemmelig emne for varslene

Åpne ntfy-appen, velg **Subscribe / Abonner på emne** (server `ntfy.sh`), og skriv et eget, **langt og tilfeldig navn** på emnet, for eksempel `elgnordland-` etterfulgt av 20 tilfeldige tegn. Ta vare på det nøyaktige navnet.

Dette emnet fungerer som en passordliknende adresse. **Ikke del det offentlig**; folk som kjenner emnenavnet kan sende og lese varsler på en offentlig ntfy-server.

### 3. Lag et GitHub-repositorium

Opprett en gratis konto på https://github.com om du ikke allerede har en.

- Trykk **New repository** og kall det eksempelvis `inatur-varsler`.
- Jeg anbefaler **Public** for dette generiske programmet, fordi GitHub Actions-kjøringer på offentlige repositorier normalt er gratis. Ingen personlig varslingsnøkkel ligger i koden; den blir lagret som en GitHub Secret. Du kan velge **Private** om du foretrekker det, men da kan de mange planlagte kjøringene bruke opp gratisminuttene og koste penger. Kontroller GitHubs gjeldende prisliste og forbruk.
- Last opp filene i denne mappen, **med mappestrukturen bevart**, inkludert den skjulte `.github/workflows/`-mappen. Den enkleste metoden er Git på PC, eller laste opp filene i GitHubs nettleser og bruke riktig sti for workflow-filen.
- Standard branch er vanligvis `main`.

**Merk:** GitHub tillater ikke opplasting av ZIP direkte som et ferdig fungerende repository. Pakk ut ZIP-filen først og last opp filene.

### 4. Legg inn varslingsnavnet som GitHub Secret

I GitHub-repositoriet:

**Settings → Secrets and variables → Actions → New repository secret**

- Name: `NTFY_TOPIC`
- Secret: det lange, tilfeldige emnenavnet du abonnerer på i ntfy-appen.

GitHub Actions må ha lov til å lagre statusfilen:

**Settings → Actions → General → Workflow permissions → Read and write permissions**.

### 5. Test pushvarsel

Under **Actions**, velg **Inatur elgvarsler Nordland** → **Run workflow**.

Velg **Send et testvarsel ... = true**, og kjør. Du skal nå få «Test fra Inatur-varsler» på iPhone. Får du ikke varsel, kontroller at emnenavnene er identiske og at pushvarsler er tillatt.

### 6. Aktiver første kontroll

Kjør **Run workflow** igjen, men nå med testvarsel avslått.

Første kjøring registrerer jaktfeltene og kortene som allerede ligger ute. Derfor kommer det **ikke** jaktkortvarsler første gang. Etter det kjører GitHub Actions omtrent hvert 15. minutt, og sender varsel ved nye/endrede tilbud.

Hvis første kjøring feiler, åpne kjøringen under **Actions** og les feilmeldingen. Ved feil på søkesiden kan et skjermbilde ligge som `inatur-feilsoking`.

## Dette får du på telefonen

Eksempel (kun demonstrasjon, ikke et faktisk nytt tilbud):

> **Endring i jaktkort på Inatur**  
> Jaktkort på elg – Gjømmervatnet i Bodø  
> Område: Bodø  
> Nytt på siden: Dagskort uke 51  
> *(trykk på varselet for å åpne tilbudet)*

## Viktige begrensninger

- GitHub sine planlagte kjøringer kan bli **forsinket eller droppet** i travle perioder. Dette er varsler etter kontroll, ikke øyeblikkelig sanntid.
- I et offentlig GitHub-repositorium kan planlagte workflows bli deaktivert etter **60 dager uten aktivitet**. Sjekk at overvåkingen fortsatt er aktiv, særlig før jaktsesongen. Lag eventuelt en liten oppdatering i repositoriet før ny sesong.
- Detektering av kort inne i et tilbud baserer seg på tekst under «Kjøp/søk jakt her». Andre redigeringer i denne delen kan også gi varsel; noen dynamiske kort kan være vanskelige å lese.
- Søket er avgrenset til **elg / Nordland / ledig=true**. Kort som ikke vises i akkurat dette søket, overvåkes ikke.
- Programmet prøver ikke å handle, logge inn eller omgå tilgangsbegrensninger. Bruk det med et moderat kontrollintervall og respekter nettstedets regler.
- Ved feil i nettsiden eller nettverk vises det i GitHub Actions; du får ikke garanti for å oppdage alle kort.
- ntfy sitt offentlige nettverk har tekniske grenser. Se https://docs.ntfy.sh/.

## Justeringer

Kontrollfrekvens endres i `.github/workflows/inatur-varsler.yml`, på `cron`-linjen. Eksempel hver halvtime: `'7,37 * * * *'`. GitHub støtter minst 5 minutter mellom planlagte kjøringer, men hyppig kontroll kan være unødvendig belastning.

Søket ligger øverst i `monitor.py`, variabelen `FILTERS`. For å overvåke flere fylker bør du lage en separat kopi med eget statusarkiv.

## Kjør på en PC/server

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
export NTFY_TOPIC='ditt-lange-hemmelige-emne'
python monitor.py --test-notification
python monitor.py
```

Kjør `python monitor.py` periodisk med cron/oppgaveplanlegger hvis du ikke ønsker GitHub. PC/server må være på under kontrollene.

## Lokal testing

```bash
python -m unittest discover -s tests -v
```
