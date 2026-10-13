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
