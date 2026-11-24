# Wine Cellar

A wine database with stock, search, sorting and drinking windows. It runs as a Home Assistant app (add-on)
and opens from the sidebar, locally, via Nabu Casa and in the companion app.

## Installation

Add the repository `https://github.com/taugusti/ha-wine` under Settings → Apps → App store → ⋮ → Repositories,
install **Wine Cellar**, start it and enable **Show in sidebar**. New versions show up as regular app updates.

## Import from Excel

Under **Import & export**, choose your Excel workbook (.xlsx or .xlsm), press **Preview** and then **Import**.

The workbook needs two sheets:

- A **wine sheet** (default name *Wines*), one row per wine, with a header row. Recognised columns (case does not
  matter): Description, Vintage, Country, Region, Producer, Grapes, Drink age from, Drink age to, Purchase price,
  List price (the wine's value), Barcode, Shop, Note, Link and Stock. Only Description is required.
- A **stock sheet** (default name *Stock*) with stock movements: date, barcode, quantity and action (`In`, `Out`
  or `Status (N)` for a count of N bottles), one movement per row after a header row.

Other sheet names are set with `import_wine_sheet` / `import_stock_sheet`. The legacy Danish names (*Vin*, *Lager*,
*Beskrivelse*, *Årgang* …) are also recognised.


- Wines are matched on barcode (otherwise description + vintage) and updated. Wine type and location, which only exist in the app, are kept.
- All movements from the stock sheet are replaced on every import, so you can import again and again while Excel is your primary database.
- Movements recorded in the app are kept. If you also entered them in Excel they are counted twice, so tick
  "Delete movements recorded in the app" until you switch over completely.
- The import checks that the stock of every wine matches the wine sheet's *Stock* column and reports any differences.
- Columns not listed above are ignored.

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
step: once the wine is identified, the agent searches for shop prices in your search area (one bottle, excl. shipping) and
published Wine Advocate, Wine Spectator and James Suckling scores. Found values replace the AI's guesses, and the
sources are shown as links above the suggestions.

With Google Gemini: Settings → Devices & services → Google Generative AI → **Add conversation agent**, name it e.g.
"Wine search", set "Control Home Assistant" to none, untick "Recommended model settings", choose a model your API
quota allows with search (`gemini-2.5-flash` works on the free tier) and enable **Enable Google Search tool**.
The app finds an agent whose entity ID contains "search" automatically, or set `search_agent_entity`.

Smart fill also suggests the wine's **value** (normal price) for one bottle in your currency, excluding shipping (a
typical shop price in your search area). Enter the **actual purchase price** yourself.

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

**Find offers** asks the web search agent for current offers in wine shops in your search area (`search_area`,
optionally naming your `shops`) in your top three styles, around your usual price, whose peak falls in the gap years.
Offers that meet your criteria — at most `offer_max_price` per bottle and at least `offer_min_saving` % off — are
listed first; the rest are folded under "Other offers". Offers are sorted by how much of the
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
missing, the **auto estimate** is used. It is rule-based on region/appellation, wine type, magnum and value (normal price, not the purchase price):
a value of at least `value_mid` adds 2 years and at least `value_high` adds 4 years (`app/estimate.py`).

The wine list shows the **peak period** (the drinking window is shown in small text below) and is sorted by the
end of the peak period, so the wines that are at their best now or soon come first. Wines without a peak get an
estimated peak from their drinking window (about 30–80 % into the window), marked "peak estimated" and shown as a
dashed band, until a real peak is set by **✨ Update with AI** or by hand.

## Barcodes

Type a barcode and press Enter, or scan it with a USB scanner. You do not need to click the search field first:
typing anywhere outside a field goes into the search. A known wine opens in **check-out mode** with the stock first
and **Out** selected, so pressing Enter (or tapping Out) takes a bottle out and closes the wine. Unknown barcodes
start a new wine. **New code** continues your own EAN-13 series (`own_barcode_prefix` + a running number + check digit).

Wines without a barcode are listed first with a **!** marker. Open one and tap **Enter or make one** to type its
code or make your own. If you type or scan (USB scanner) an unknown barcode in the search field, the app first asks
whether it belongs to one of the wines without a barcode, and saves it there.

New wines that were never in stock always show in the list, marked "New · not in stock yet". Wines without a
barcode are sorted with the newest created first.

When you save a barcode that another wine already has (suppliers sometimes use the same code for several vintages),
the app asks first. **Make my own code** gives the wine the next code in your own series; the code
is shown under Barcode in the wine overview, so you can print a label for the bottle with your label app.

## Home Assistant sensors

The app keeps these sensors updated:

- `sensor.wine_cellar_bottles`: bottles in stock
- `sensor.wine_cellar_drink_this_year`: bottles whose last drinking year is this year or earlier
- `sensor.wine_cellar_ready`: bottles within their drinking window
- `sensor.wine_cellar_at_peak`: bottles in their peak period this year
- `sensor.claude_cost_month` (only with `claude_admin_key`): this month's Claude API cost in USD for your whole
  Anthropic organization, with today's cost (`today`) and the cost per workspace (`workspaces`) as attributes.
  Updated every 15 minutes from Anthropic's cost report; month and day follow UTC. If Anthropic refuses the key,
  the attribute `error` says why.
- `sensor.claude_cost_<workspace>`: the same per Anthropic workspace that has cost this month, e.g.
  `sensor.claude_cost_wine_cellar`. To see features apart, give each its own API key in its own workspace and add
  each key as its own Anthropic integration entry in Home Assistant (each gets its own AI Task entity).

## Configuration

- `ai_task_entity` (optional): the AI Task entity used by Smart fill, e.g. `ai_task.google_ai_task`.
  Empty means the first AI Task entity found.
- `search_agent_entity` (optional): conversation agent with web search, e.g. `conversation.wine_search`.
  Empty means an agent whose entity ID contains "search"; `none` turns the web search step off.
- `allowed_users` (optional): Home Assistant usernames (the login name, not the display name) that may use
  direct access, see below. Empty means direct access is off.
- `api_apps` / `api_apps_write` (optional): other Home Assistant apps that may call the API directly, see
  [API for other apps](#api-for-other-apps).
- `extra_hostnames` (optional): more names or IP addresses for the direct-access certificate.
- `certfile` / `keyfile` (optional): your own certificate in Home Assistant's `/ssl` folder for direct access.
- `claude_admin_key` (optional): an Anthropic Admin API key (`sk-ant-admin01-...`), created by an organization
  admin in the Claude Console under Settings → Admin keys. Turns on `sensor.claude_cost_month`. Individual
  Console accounts have no Admin API; create an organization first.

Market and money (all optional; empty or 0 means the fallback in brackets):

- `currency`: ISO code for all prices, e.g. `EUR`, `DKK`, `SEK`, `USD` (Home Assistant's currency under
  Settings → System → General).
- `number_locale`: how prices are formatted, e.g. `en-GB`, `da-DK`, `de-DE` (the browser's setting).
- `search_area`: where the web search looks for shop prices and offers, in plain words: a country, a region or a
  wider area, e.g. `Denmark`, `Bavaria, Germany`, `Scandinavia`, `the EU` (Home Assistant's country).
- `search_fallback_area`: where to look when no shop in the search area has the wine (neighbouring countries).
- `shops`: shop names or domains the search agent should look at first (none).
- `offer_max_price`: highest offer price per bottle listed first in Offers (a default for your currency, e.g.
  27 EUR / 200 DKK).
- `offer_min_saving`: minimum saving in % for an offer to be listed first (30).
- `offer_small_saving`: savings against other shops from this % are labelled "Small saving" (15).
- `value_mid` / `value_high`: a wine's value from which the rule estimate adds 2 / 4 years to the drinking window
  (a default for your currency, e.g. 40 / 80 EUR or 300 / 600 DKK).
- `own_barcode_prefix`: 3–11 digits that start the barcodes the app makes for wines without one (`290000`, from the
  GS1 range for in-store use).
- `ai_language`: language code sent to the web search agent (`en`).
- `import_wine_sheet` / `import_stock_sheet`: sheet names in the Excel workbook (`Wines` / `Stock`).

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

## API for other apps

Other Home Assistant apps can use the Wine Cellar API directly over the internal Home Assistant network, for example
the **Home Assistant MCP Server** (ha-mcp), so an AI assistant can look up and update the cellar without a browser.

1. Find the other app's slug: Settings → Apps → the app; the slug is the last part of the address
   (e.g. `81f33d0f_ha_mcp`).
2. Add it under `api_apps` in the Wine Cellar configuration. Turn on `api_apps_write` if the app may also add stock
   movements and edit wines; otherwise it can only read.
3. Restart Wine Cellar.

The app is recognised by its address on the internal network, so nothing else on your network gets in. Apps get
the `/api/...` paths only, not the web interface. The app log shows `API: app … connected` the first time an app
calls.

Useful calls (paths relative to the app; with ha-mcp: `ha_manage_app(slug="<wine cellar slug>", path=...)`):

| Call | What it does |
|------|--------------|
| `GET /api/search?q=magrez songes&in_stock=1&limit=25` | Search: every word must occur in name, producer, region, country, grapes, vintage, barcode, location or shop (case and accents ignored). Wines in stock first; compact fields incl. `stock`, drinking window, peak and `status` (over, now, peak, ready, young, unknown). `in_stock` and `limit` are optional. |
| `GET /api/wines/<id>` | One wine with all fields and its stock movements. |
| `GET /api/wines` | All wines with all fields (large). |
| `GET /api/stats` | Bottles, value, and bottles per status, vintage, country and peak year. |
| `GET /api/lookup?barcode=<code>` | Wines with this barcode. |
| `POST /api/movements` `{"wine_id": 1, "kind": "out", "qty": 1}` | Stock movement (needs `api_apps_write`): `kind` is `in`, `out` or `count` (with `"count": n`); optional `date` (YYYY-MM-DD) and `note`. |
| `PUT /api/wines/<id>` `{...fields}` | Change a wine (needs `api_apps_write`). |

## Data and backup

The database lives in `/data/wine_cellar.db` and is included in Home Assistant backups. The app is stopped briefly
during backups to guarantee a consistent copy. Under Import & export you can also download CSV or a full JSON backup.
