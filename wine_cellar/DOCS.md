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

## Data and backup

The database lives in `/data/wine_cellar.db` and is included in Home Assistant backups. The app is stopped briefly
during backups to guarantee a consistent copy. Under Import & export you can also download CSV or a full JSON backup.
