# Wine Cellar

A wine database with stock, search, sorting and drinking windows. It runs as a Home Assistant app (add-on)
and opens from the sidebar, locally, via Nabu Casa and in the companion app.

## Installation

Add the repository `https://github.com/taugusti/ha-wine` under Settings → Apps → App store → ⋮ → Repositories,
install **Wine Cellar**, start it and enable **Show in sidebar**. New versions show up as regular app updates.

## Import from Excel

Under **Import & export**, choose `vindatabase.xlsm`, press **Preview** and then **Import**.

- Wines are matched on barcode (otherwise description + vintage) and updated. Wine type and location, which only exist in the app, are kept.
- All movements from the *Lager* sheet are replaced on every import, so you can import again and again while Excel is your primary database.
- Movements recorded in the app are kept. If you also entered them in Excel they are counted twice, so tick
  "Delete movements recorded in the app" until you switch over completely.
- The import checks that the stock of every wine matches the Excel column *Lager* and reports any differences.
- The workbook's Danish sheet and column names (Vin, Lager, Beskrivelse, Årgang, …) are read as-is.
  Columns U–AA are not imported.

## Smart fill (AI lookup)

When you create a wine, paste the invoice text and/or scan the barcode under **Smart fill** and press **Look up**.
The app:

1. looks the barcode up in Open Food Facts (free, often unknown for wine),
2. asks your Home Assistant **AI Task** (e.g. Google Gemini) to identify the wine, using the invoice text,
   the barcode result and your existing countries, regions, grapes, producers and shops,
3. shows the suggestions field by field. Tick the ones you want and press **Apply selected**, then save.

It also warns you if the wine seems to exist already. On an existing wine, Smart fill can complete missing data
(e.g. critic scores) from the current description.

The AI Task entity is detected automatically. To choose a specific one, set `ai_task_entity` in the app
configuration. No API key is stored in the app.

## Consistent values

Country is a dropdown with **+ Add new…**. Region, producer and shop suggest existing values while you type, and
grapes are entered as tags. Every value is normalized when it is saved or imported: spellings that only differ in
case, accents, spaces or hyphens become the most used spelling, and English country names map to the name you use
(e.g. "Frankrig" → "France" once France is the name in use).

Under **Import & export → Clean up values** you can merge likely duplicates (e.g. "Grernache" → "Grenache") and rename
any value. Merges are remembered, so the old spelling is corrected automatically next time, also on Excel import.

## Critic scores

Each wine has fields for **Robert Parker (Wine Advocate)**, **Wine Spectator** and **James Suckling**, each with
a link to the review and a **Search** link (a Google search on the critic's site). The AI only fills in a score when it
knows a published score for that exact vintage; check it with the link. Scores are shown as badges in the wine list.
The critics' own sites require a subscription, so scores cannot be fetched from them automatically.

## Review

Suggested changes to values you already have, for example a new drinking window from a bulk review, are listed under
**Review**. Each suggestion shows the current value, the suggested value, the reason and sources. You can adjust the
value before you accept it, or reject it. Empty fields, such as critic scores, are filled in directly and listed at
the bottom of the page with their source.

## Drinking window

The window is given in years after vintage, as in Excel. Your own window (Drink age from/to) is used. If it is
missing, the **auto estimate** is used. It is rule-based on region/appellation, wine type, magnum and price
(`app/estimate.py`).

The default view is sorted by last drinking year, with the wines to drink first at the top.

## Barcodes

Type or scan a barcode in the search field and press Enter. A USB scanner works too. Known wines open directly,
and unknown barcodes start a new wine. **New code** continues your own EAN-13 series (999888777xxx + check digit).
On Android (Chrome or the HA app) a camera button appears for scanning.

## Home Assistant sensors

The app keeps these sensors updated:

- `sensor.wine_cellar_bottles`: bottles in stock
- `sensor.wine_cellar_drink_this_year`: bottles whose last drinking year is this year or earlier
- `sensor.wine_cellar_ready`: bottles within their drinking window

## Configuration

- `ai_task_entity` (optional): the AI Task entity used by Smart fill, e.g. `ai_task.google_ai_task`.
  Empty means the first AI Task entity found.

## Data and backup

The database lives in `/data/wine_cellar.db` and is included in Home Assistant backups. The app is stopped briefly
during backups to guarantee a consistent copy. Under Import & export you can also download CSV or a full JSON backup.
