# Vinkælder

Vindatabase med lager, søgning, sortering og drikkevinduer. Den kører som app (add-on) i Home Assistant,
og du åbner den fra sidebjælken lokalt, via Nabu Casa og i mobilappen.

## Installation

Tilføj repoet `https://github.com/taugusti/ha-wine` under Indstillinger → Apps → App-butik → ⋮ → Repositories,
installér **Vinkælder**, start den og slå **Vis i sidebjælke** til. Nye versioner dukker op som almindelige app-opdateringer.

## Import fra Excel

Under **Import & eksport** vælger du `vindatabase.xlsm`. Tryk **Forhåndsvis** og derefter **Importér**.

- Vine matches på stregkode (ellers beskrivelse + årgang) og opdateres. Vintype og placering, som kun findes i appen, bevares.
- Alle bevægelser fra fanen *Lager* erstattes ved hver import. Du kan derfor importere igen og igen, så længe Excel er din primære database.
- Bevægelser registreret i appen bevares. Har du også ført dem i Excel, tælles de dobbelt. Brug derfor fluebenet
  "Slet bevægelser registreret i appen", indtil du skifter helt over.
- Importen kontrollerer, at lagertallet for hver vin stemmer med Excel-kolonnen *Lager*, og viser afvigelser.

## Drikkevindue

Vinduet angives i år efter høst, som i Excel. Dit eget vindue (Drink age from/to) bruges. Mangler det, bruges
**auto-estimatet**, som er regelbaseret ud fra område/appellation, vintype, magnum og pris (`app/estimate.py`).
Kolonne U–AA i Excel importeres ikke.

Standardvisningen er sorteret efter sidste drikkeår, med de vine der skal drikkes først øverst.

## Stregkoder

Indtast eller scan en stregkode i søgefeltet og tryk Enter. Det virker også med en USB-scanner. Kendte vine åbnes, og ukendte stregkoder
starter en ny vin. **Ny kode** fortsætter din egen EAN-13-serie (999888777xxx + kontrolciffer).
På Android (Chrome/HA-appen) vises en kameraknap til scanning.

## Sensorer i Home Assistant

Appen opdaterer disse sensorer:

- `sensor.vinkaelder_flasker`: flasker på lager
- `sensor.vinkaelder_drik_i_aar`: flasker hvis sidste drikkeår er i år eller tidligere
- `sensor.vinkaelder_klar`: flasker inden for drikkevinduet

## Data og backup

Databasen ligger i `/data/vinkaelder.db` og er med i Home Assistants backups. Appen stoppes kort under backup
for at sikre en konsistent kopi. Under Import & eksport kan du også hente CSV eller fuld JSON.
