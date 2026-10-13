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
