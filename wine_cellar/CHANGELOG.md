# 1.22.0
- **Swipe back / back button** now works inside the app: it closes the open wine, filter, camera or dialog, or goes back to the previous tab, instead of leaving Wine Cellar. Unsaved changes still ask before the wine closes.
- Offers: every shop link is checked by the app. It opens the page and confirms it is the product page for that wine and vintage; if the link points to a category, a search page or another wine, the app looks for the right product on that page or with the shop's own search. Confirmed offers show "✓ Product page found" and come first. When the wine cannot be found on the shop's site the card says so and the button becomes a search on that shop instead of a wrong link. If the shop's page shows another price, it is shown.
- The search agent is told to give only exact product page URLs.
- Results from earlier searches get their links checked once when the Offers tab is opened.
- Offers tab: **Find offers** and the last search are at the top, followed by the offers; "Peak gaps" and "What you buy most" are folded below and open on tap.

# 1.21.0
- Offers: each wine found now says whether you already have it. "You have this vintage: N bottles" when the same vintage is in the cellar, and "You have other vintages" with each vintage and its bottle count (tap one to open it). The match ignores the vintage and words like Château/Domaine, and uses the producer, so a slightly different name from the shop still matches.
- "Open in cellar" is shown only for the same vintage; for another vintage you get "Add to cellar".

# 1.20.0
- **Filter** button next to the search field: filter the wine list on price (value or price paid, with quick ranges), grape, region, country, vintage, wine type, drinking status and wines with 0 bottles. On phones it opens as a sheet from the bottom, so the list keeps the screen; the button shows how many filters are on.
- Active filters are shown as small chips under the search field; tap one to remove it, or "Clear all". Filters are remembered on the device.
- The country and status dropdowns moved into the filter, which gives the search field the full width on phones.

# 1.19.2
- Fixed: direct-access login was refused for every user, because the login check sent the app token in a header the Supervisor reads as the user's credentials.

# 1.19.1
- Refused direct-access logins are written to the app log with the reason (not in `allowed_users`, or refused by Home Assistant).

# 1.19.0
- Direct access (port 8100) now uses **HTTPS**, so Wine Cellar can be installed as an app in Chrome and Edge, and the camera works there too. The app makes its own certificate for the Home Assistant host's names and IP addresses; install its certificate authority once per device from the link on the login page (see the documentation). The authority can only vouch for local names and private addresses. Plain http is redirected to https.
- Your own certificate from the `/ssl` folder can be used instead (`certfile` / `keyfile`), and extra names or addresses can be added with `extra_hostnames`.
- App icons and a web app manifest for installing the app.

# 1.18.0
- **Direct access with login** on the app's own port (8100): open `http://<home-assistant>:8100` and log in with a Home Assistant user listed under the new `allowed_users` option. Such a user only sees Wine Cellar, not the rest of Home Assistant — Home Assistant only shows app panels in the sidebar to administrators, so this is the way to give a normal user access. The login is checked by Home Assistant; you stay logged in for 90 days, and removing a user from `allowed_users` logs them out at once. A **Log out** button is shown when the app is opened this way.
- The ingress port now only accepts requests from Home Assistant itself.

# 1.17.0
- App files are served from a new path (wc/ instead of static/), so the Home Assistant frontend cache can no longer hand out an old app.js. The page also reports to the app log if the app code did not load.

# 1.16.3
- Browser errors and tab rendering problems are written to the app log, to make problems easier to find.

# 1.16.2
- New wine glass icon: in the app header, as the browser icon and as the app icon in Home Assistant.

# 1.16.1
- Statistics, Offers and Review never stay blank: if a page cannot be shown, the error and a Reload button are shown instead.

# 1.16.0
- Scan a barcode with the phone camera from the search field (also in the Home Assistant app): uses the browser's barcode reader or, where there is none, a built-in reader (ZXing). Frame guide, light button on phones with a torch.
- A scanned wine opens in check-out mode: the stock is shown first and **Out** takes the bottle out and closes the wine.

# 1.15.1
- Offers: a clear message when the Google AI quota is used up.

# 1.15.0
- New **Offers** tab: shows your peak gaps (years where fewer bottles are at peak than you drink in a year) and the styles you buy most. **Find offers** searches Danish wine shops for current offers in your top three styles with a peak in the gap years, sorted by how well they fill the gaps and by discount. "Add to cellar" opens a new wine with the details filled in.

# 1.14.0
- Statistics are based on the peak period: bottles at peak now and past their peak, bottles at peak per year (the coming years), bottles by end of peak (replaces last drinking year) and bottles by status, as in the list.
- New Home Assistant sensor `sensor.wine_cellar_at_peak`.

# 1.13.1
- Drinking windows use the wine's value (normal price) instead of the purchase price, which is often a steep discount. This applies to the rule estimate and to the AI, which is told to ignore the price paid. The "Estimated price" field is now called "Value (DKK, normal price)".

# 1.13.0
- Cleaner wine view, especially on phones: an overview at the top (peak and drinking window, key facts, scores, notes), a compact stock row with − / + and Out / In, and the form folded away under "Edit details". Movements are folded too.
- Unsaved changes show a save bar at the bottom (Discard / Save). Closing with unsaved changes asks Save, Discard or Keep editing.
- Stock changes no longer throw away unsaved edits in the form.
- AI review pauses when the Google AI quota is used up, instead of failing wine after wine. Start it again later to continue.

# 1.12.0
- Review: each suggested value has its own ✓ / ✕, so you can take the peak but keep your own drinking window (or the other way round). "Accept all" / "Reject all" per wine still work.

# 1.11.1
- AI review: resumes where it stopped after a restart; ignores one-year "windows" and peaks that cover the whole drinking window.

# 1.11.0
- New "✨ AI review of the cellar" on the Review page: looks up all wines in stock without a peak in the background and adds drinking window and peak suggestions for review (and fills empty critic scores). Shows progress, can be stopped, and waits and retries when the AI quota is used up.

# 1.10.0
- The wine list shows the peak period instead of the drinking window (the window is shown in small text below) and is sorted by the end of the peak period by default.
- Wines without a peak get an estimated peak from their drinking window (about 30–80 % into the window), marked "peak estimated" and shown as a dashed band, until a real peak is set.

# 1.9.0
- Closing a wine with unsaved changes (or a new wine with data or photos) asks for confirmation.
- Drinking windows are based on the specific wine: producer style and track record, the cuvée level, the vintage character and bottle size. "Window based on" explains what the window rests on.
- The web search looks for published drinking windows from critics and producers; these are used instead of the AI estimate (median of the windows found), with sources.
- New peak window (Peak from/until), shown as a darker band in the list, and a new "At peak" status and filter.

# 1.8.1
- Suggestions are shown as soon as the wine is identified; the web search (prices, critic scores) continues in the background and its results are added when they arrive. Your accept/reject decisions are kept.
- Cancel during the web search keeps the suggestions and only stops the search. Web search time limit 100 s.

# 1.8.0
- Lookups run in the background with live progress (step and seconds), so slow lookups no longer end in "Bad Gateway".
- Cancel a running lookup and fill in the fields yourself; failed lookups show a Retry button.
- "✨ Update with AI" on existing wines: looks the wine up again (using the saved label photo).
- Suggestions are accepted (✓) or rejected (✕) one by one, or all at once; on existing wines accepted values are saved right away.
- Suggestion table fits on phones.

# 1.7.0
- Front/back label buttons open a camera view inside the app (the Home Assistant Android app opened the gallery instead of the camera). "Or choose from gallery" is still available, and the gallery is used automatically if the camera cannot be opened.

# 1.6.2
- The app checks for a new version when it becomes visible (and every 2 minutes) and reloads itself, so an update is picked up even if the Home Assistant app keeps the page open.

# 1.6.1
- Fixed: Smart fill (photo buttons) could show as "not available" if the drawer was opened before the AI status was loaded.
- Static files are cache-busted per version, and the version is shown next to the app name.

# 1.6.0
- Web search step: after the wine is identified, a Home Assistant conversation agent with web search (e.g. a Gemini
  agent with "Enable Google Search tool") looks up Danish prices for one bottle and published critic scores, with links.
  Found prices and scores replace the AI's own guesses; sources are shown with the suggestions.
- New option `search_agent_entity` (default: a conversation agent whose entity ID contains "search"; "none" turns it off).

# 1.5.0
- Two photo buttons: front label (starts the lookup) and back label (updates the lookup with grapes, barcode etc.).
- Smart fill suggests an estimated price for one bottle (DKK, excl. shipping) in "Estimated price".
  The actual purchase price is no longer filled in automatically; you enter it yourself.

# 1.4.0
- Smart fill from a photo: take one or more photos of the bottle and the lookup starts by itself. Invoice text and
  barcode are optional.
- The AI marks the fields it is unsure about (⚠) and explains why; a banner warns when it is not sure it found the
  right wine.
- The first photo is kept as the wine's label photo (stored in Home Assistant's media folder, `wine_cellar`).

# 1.3.0
- New Review tab: suggested changes to existing values (e.g. drinking windows) wait for your approval and can be
  adjusted before you accept them. Empty fields (e.g. critic scores) can be filled in directly, with sources.
- The "Show sold out" filter is now "Show wines with 0 bottles".
- Rule estimate recognises "Burgundy".

# 1.2.1
- Critic links that only point to a front page are dropped, so the Search link is shown instead.

# 1.2.0
- Smart fill: paste invoice text and/or scan a barcode, and the wine is looked up with Home Assistant's AI Task
  (and Open Food Facts for the barcode). Suggestions are reviewed field by field before they are applied.
- Warning when a wine looks like one that is already in the cellar.
- Country dropdown with "Add new", autocomplete for region, producer and shop, grapes as tags.
- Values are normalized on save and import; "Clean up values" lets you merge duplicates, and merges are remembered.
- Critic scores (Robert Parker / Wine Advocate, Wine Spectator, James Suckling) with review links and search links.
- New fields: bottle size and "About the wine".
- Fixed: mobile list layout and the "own" label under the drinking window.

# 1.1.1
- Fixed untranslated "All countries" filter label.

# 1.1.0
- Everything translated to English (code, UI and documentation).
- Renamed the app to Wine Cellar (slug `wine_cellar`); sensors renamed to `sensor.wine_cellar_*`.

# 1.0.1
- Columns U–AA (estimates and drinking advice) are no longer imported from Excel.

# 1.0.0
- First version: wine list with search/sort, stock (in/out/count), drinking windows with auto estimate,
  statistics, Excel import (Vin + Lager sheets) and export. Home Assistant sensors.
