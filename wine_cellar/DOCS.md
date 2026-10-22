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
"Or choose from gallery" lets you use an existing photo. You can also paste invoice text and/or enter the barcode, alone or together
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

Smart fill also suggests the wine's **value** (normal price) for one bottle in DKK, excluding shipping (a typical Danish shop
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

## Offers

The **Offers** tab compares how many of today's bottles are at their peak each year with how many bottles you drink
a year (average of the last three years). Years below that are **peak gaps**. It also shows the styles you buy most
(country, area and type, weighted by bottles bought) with your usual price and the wines' value.

**Find offers** asks the web search agent for current offers in Danish wine shops in your top three styles, around
your usual price and with a clear discount, whose peak falls in the gap years. Offers are sorted by how much of the
gaps they fill, then by discount. Check the price at the shop before you buy: the results come from a web search.
**Add to cellar** opens a new wine with the details, price, value and drinking window filled in.

## Review

Suggested changes to values you already have, for example a new drinking window from a bulk review, are listed under
**Review**. Each suggestion shows the current value, the suggested value, the reason and sources. You can adjust a
value before you accept it, take or leave single values with ✓ / ✕, or accept or reject all values of a wine. Empty fields, such as critic scores, are filled in directly and listed at
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
(grand vin, second wine, entry level), the vintage's character, the grapes, the wine's value (normal price, never the discounted price you paid) and the bottle size.
If the web search finds drinking windows published by critics or the producer, those are used instead (the median
of the windows found), with links. **Window based on** says what the window rests on; when the AI only knows general
appellation norms it says so and marks the window as uncertain.

 Your own window (Drink age from/to) is used. If it is
missing, the **auto estimate** is used. It is rule-based on region/appellation, wine type, magnum and value (normal price, not the purchase price)
(`app/estimate.py`).

The wine list shows the **peak period** (the drinking window is shown in small text below) and is sorted by the
end of the peak period, so the wines that are at their best now or soon come first. Wines without a peak get an
estimated peak from their drinking window (about 30–80 % into the window), marked "peak estimated" and shown as a
dashed band, until a real peak is set by **✨ Update with AI** or by hand.

## Barcodes

Type a barcode and press Enter, or scan it with a USB scanner. You do not need to click the search field first:
typing anywhere outside a field goes into the search. A known wine opens in **check-out mode** with the stock first
and **Out** selected, so pressing Enter (or tapping Out) takes a bottle out and closes the wine. Unknown barcodes
start a new wine. **New code** continues your own EAN-13 series (999888777xxx + check digit).

Wines without a barcode are listed first with a **!** marker. Open one and tap **Enter or make one** to type its
code or make your own. If you type or scan (USB scanner) an unknown barcode in the search field, the app first asks
whether it belongs to one of the wines without a barcode, and saves it there.

New wines that were never in stock always show in the list, marked "New · not in stock yet". Wines without a
barcode are sorted with the newest created first.

When you save a barcode that another wine already has (suppliers sometimes use the same code for several vintages),
the app asks first. **Make my own code** gives the wine the next code in your own series (999888777xxx); the code
is shown under Barcode in the wine overview, so you can print a label for the bottle with your label app.

## Home Assistant sensors

The app keeps these sensors updated:

- `sensor.wine_cellar_bottles`: bottles in stock
- `sensor.wine_cellar_drink_this_year`: bottles whose last drinking year is this year or earlier
- `sensor.wine_cellar_ready`: bottles within their drinking window
- `sensor.wine_cellar_at_peak`: bottles in their peak period this year

## Configuration

- `ai_task_entity` (optional): the AI Task entity used by Smart fill, e.g. `ai_task.google_ai_task`.
  Empty means the first AI Task entity found.
- `search_agent_entity` (optional): conversation agent with web search, e.g. `conversation.wine_search`.
  Empty means an agent whose entity ID contains "search"; `none` turns the web search step off.
- `allowed_users` (optional): Home Assistant usernames (the login name, not the display name) that may use
  direct access, see below. Empty means direct access is off.
- `extra_hostnames` (optional): more names or IP addresses for the direct-access certificate.
- `certfile` / `keyfile` (optional): your own certificate in Home Assistant's `/ssl` folder for direct access.

## Direct access for users who should only see Wine Cellar

Home Assistant only shows app panels in the sidebar to administrators, so a normal user cannot open Wine Cellar
from Home Assistant. Instead, the app has its own HTTPS port with a login:

1. Create a normal (non-admin) Home Assistant user for it, or use an existing one.
2. Add that user's username under `allowed_users` in the app configuration and restart the app.
3. Open `https://homeassistant.local:8100` (or the Home Assistant machine's IP address) and log in with the
   user's Home Assistant username and password.

The password is checked by Home Assistant and never stored by the app. The browser stays logged in for 90 days;
**Log out** in the header ends the session, and removing a user from `allowed_users` logs them out at once.
After 5 failed attempts from one address, login is paused for 15 minutes. Plain `http://` addresses are
redirected to `https://`.

### Trust the certificate (once per device)

The app makes its own certificate for the Home Assistant host's names and local IP addresses. Browsers only accept
it once the app's certificate authority is installed on the device:

1. On the login page, click **Download the Wine Cellar certificate** (`/ca.crt`). If the browser warns first,
   choose *Advanced → Continue* to get to the page.
2. **Windows:** open the downloaded file → **Install Certificate** → *Current User* → *Place all certificates in
   the following store* → **Trusted Root Certification Authorities** → Finish, and confirm the warning.
   **macOS:** open it in Keychain Access, then set it to *Always Trust*. **Android:** Settings → Security →
   Encryption & credentials → Install a certificate → CA certificate.
3. Restart the browser and open `https://homeassistant.local:8100` again; the padlock is now shown.

The certificate authority is limited to `.local` names, `homeassistant` and private IP addresses, so trusting it
cannot be used for any public website. The server certificate is renewed automatically. If the device reaches Home
Assistant by another name or address, add it under `extra_hostnames` and restart the app. If you already have a
certificate in Home Assistant's `/ssl` folder, set `certfile` and `keyfile` to use it instead.

### Install as an app in Chrome or Edge

With the padlock showing, use the install button in the address bar (or ⋮ → *Cast, save and share* →
**Install page as app**). Wine Cellar then opens in its own window from the Start menu, taskbar or desktop.

Direct access works on your local network only, not through Nabu Casa.

## Data and backup

The database lives in `/data/wine_cellar.db` and is included in Home Assistant backups. The app is stopped briefly
during backups to guarantee a consistent copy. Under Import & export you can also download CSV or a full JSON backup.
