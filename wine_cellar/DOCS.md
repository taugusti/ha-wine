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

When you create a wine, press **Front label** under **Smart fill** and take a photo; the lookup starts by itself.
Press **Back label** to add the back label (grapes, barcode); the lookup is then updated.
The buttons open a camera view inside the app. This needs a secure (https) connection, e.g. via Nabu Casa;
on a plain http connection, or if camera access is refused, the photo picker opens instead.
"Or choose from gallery" lets you use an existing photo. You can also paste invoice text and/or scan the barcode, alone or together
with the photos. The app:

1. looks the barcode up in Open Food Facts (free, often unknown for wine),
2. asks your Home Assistant **AI Task** (e.g. Google Gemini) to identify the wine from the photos, the invoice text,
   the barcode result and your existing countries, regions, grapes, producers and shops,
3. shows the suggestions field by field (the lookup runs in the background; you see which step it is on, and
   you can **Cancel** it and fill in the fields yourself, or **Retry** if it fails). Fields the AI is unsure about are marked ⚠ with an explanation, and a banner
   warns you when it is not sure it found the right wine. Accept (✓) or reject (✕) each suggestion, or press
   **Accept all**, then save.

### Web search (prices and critic scores)

The AI Task cannot search the web. If you add a conversation agent with web search, Smart fill uses it as a second
step: once the wine is identified, the agent searches for Danish shop prices (one bottle, excl. shipping) and
published Wine Advocate, Wine Spectator and James Suckling scores. Found values replace the AI's guesses, and the
sources are shown as links above the suggestions.

With Google Gemini: Settings → Devices & services → Google Generative AI → **Add conversation agent**, name it e.g.
"Wine search", set "Control Home Assistant" to none, untick "Recommended model settings", choose a model your API
quota allows with search (`gemini-2.5-flash` works on the free tier) and enable **Enable Google Search tool**.
The app finds an agent whose entity ID contains "search" automatically, or set `search_agent_entity`.

Smart fill also suggests an **estimated price** for one bottle in DKK, excluding shipping (a typical Danish shop
price). Enter the **actual purchase price** yourself.

Photos are resized in the browser and stored in Home Assistant's media folder under `wine_cellar`. The first photo
is kept as the wine's label photo and shown in the wine's details.

It also warns you if the wine seems to exist already. On an existing wine, press **✨ Update with AI** to look it up again (with
the saved label photo and the current description); accepted suggestions are saved right away.

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

**✨ AI review of the cellar** (on the Review page) looks up every wine in stock that has no peak of its own, using the
AI and the web search (about a minute per wine). It runs inside Home Assistant, so you can close the app meanwhile, and
waits and retries when the AI's free quota is used up. Drinking window and peak suggestions are added for review; a
window that only differs by a year from yours is kept, and only the peak is suggested. Empty critic scores with a link
to the review are filled in directly.

## Drinking window

The window is given in years after vintage, as in Excel. A wine can also have a **peak** window (when it is at its
best), shown as a darker band in the list; wines in their peak period get the status **At peak**.

Smart fill estimates the window for the specific wine: the producer's style and track record, the cuvée's level
(grand vin, second wine, entry level), the vintage's character, the grapes, the price level and the bottle size.
If the web search finds drinking windows published by critics or the producer, those are used instead (the median
of the windows found), with links. **Window based on** says what the window rests on; when the AI only knows general
appellation norms it says so and marks the window as uncertain.

 Your own window (Drink age from/to) is used. If it is
missing, the **auto estimate** is used. It is rule-based on region/appellation, wine type, magnum and price
(`app/estimate.py`).

The wine list shows the **peak period** (the drinking window is shown in small text below) and is sorted by the
end of the peak period, so the wines that are at their best now or soon come first. Wines without a peak get an
estimated peak from their drinking window (about 30–80 % into the window), marked "peak estimated" and shown as a
dashed band, until a real peak is set by **✨ Update with AI** or by hand.

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
- `search_agent_entity` (optional): conversation agent with web search, e.g. `conversation.wine_search`.
  Empty means an agent whose entity ID contains "search"; `none` turns the web search step off.

## Data and backup

The database lives in `/data/wine_cellar.db` and is included in Home Assistant backups. The app is stopped briefly
during backups to guarantee a consistent copy. Under Import & export you can also download CSV or a full JSON backup.
