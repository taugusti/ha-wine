"""Rule-based estimate of the drinking window (years after vintage).

Rules are matched against region and description. The most specific rule
(first in the list) wins. The result is then adjusted for bottle size and price.
"""
import re
import unicodedata


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ").replace("_x000d_", " ")
    return re.sub(r"\s+", " ", s)


# (keywords, from, to, advice) - keywords are matched against region + description
AREA_RULES = [
    # Bordeaux, left bank
    (("pauillac", "saint estephe", "st estephe", "saint julien", "st julien", "margaux"), 8, 22,
     "Left-bank wine built to age; the tannins need time. Decant when young."),
    (("pessac leognan", "graves"), 6, 18, "Structured Bordeaux; medium to long ageing."),
    (("haut medoc", "listrac", "moulis"), 6, 16, "Medium-term ageing; drink once the tannins have softened."),
    (("medoc",), 5, 14, "Medium-term ageing; drink once the tannins have softened."),
    # Bordeaux, right bank
    (("pomerol",), 7, 20, "Merlot-dominated wine for ageing; broad drinking plateau."),
    (("saint emilion grand cru", "st emilion grand cru"), 7, 18,
     "Right-bank Grand Cru; medium to long ageing."),
    (("lussac", "montagne", "puisseguin", "lalande"), 4, 10, "Satellite appellation; drink while the fruit is fresh."),
    (("saint emilion", "st emilion"), 5, 12, "Merlot-based; ready earlier than the left bank."),
    (("cotes de bordeaux", "blaye", "bourg", "castillon", "fronsac"), 3, 8, "Short to medium-term ageing."),
    (("bordeaux superieur",), 3, 8, "Short to medium-term ageing."),
    (("bordeaux",), 2, 7, "Drink within a few years."),
    # Rhône
    (("hermitage", "cote rotie"), 8, 20, "Northern Rhône Syrah with great ageing potential."),
    (("cornas",), 6, 18, "Powerful Syrah; give it time."),
    (("chateauneuf",), 6, 15, "Grenache blend; broad plateau, decant when young."),
    (("gigondas", "vacqueyras", "rasteau", "cairanne", "lirac"), 4, 12, "Southern Rhône cru; medium-term ageing."),
    (("crozes", "saint joseph", "st joseph"), 3, 8, "Fruit-driven Syrah; drink within 3-8 years."),
    (("cotes du rhone villages",), 2, 7, "Drink within a few years."),
    (("cotes du rhone", "ventoux", "luberon"), 1, 5, "Drink young while the fruit is fresh."),
    # Bourgogne / Beaujolais
    (("grand cru",), 8, 20, "Grand Cru; long ageing."),
    (("1er cru", "premier cru"), 5, 14, "Premier Cru; medium-term ageing."),
    (("cote de nuits villages", "cote de beaune villages", "gevrey", "chambolle", "vosne", "nuits saint georges",
      "pommard", "volnay", "morey", "marsannay", "santenay", "savigny", "aloxe", "corton", "mercurey", "givry"),
     4, 10, "Village Burgundy; drink at 4-10 years."),
    (("hautes cotes",), 3, 8, "Drink relatively early; finesse over age."),
    (("moulin a vent", "morgon", "cote du py", "julienas", "chenas"), 3, 10, "Structured Beaujolais cru; can age."),
    (("fleurie", "chiroubles", "saint amour", "regnie", "brouilly", "cote de brouilly"), 2, 6,
     "Light Beaujolais cru; drink young."),
    (("beaujolais",), 1, 4, "Drink young; serve slightly chilled."),
    (("bourgogne", "burgund", "auxerre"), 2, 6, "Drink relatively early; finesse over age."),
    # Loire / Sydvest / Languedoc
    (("chinon", "bourgueil", "saumur champigny", "saint nicolas"), 4, 15, "Loire Cabernet Franc; surprisingly age-worthy."),
    (("cahors", "madiran"), 5, 15, "Tannic; give it time."),
    (("bandol",), 6, 18, "Mourvèdre-based; long ageing."),
    # Italy
    (("barolo", "barbaresco"), 8, 25, "Nebbiolo; long ageing, decant."),
    (("brunello",), 8, 20, "Sangiovese Grosso; long ageing."),
    (("amarone",), 6, 18, "Concentrated; medium to long ageing."),
    (("chianti classico riserva", "gran selezione"), 5, 12, "Riserva; medium-term ageing."),
    (("vino nobile", "rosso di montalcino", "chianti classico"), 3, 9, "Short to medium-term ageing."),
    (("bolgheri", "super tuscan", "supertoscan"), 5, 15, "Bordeaux-style Tuscan; medium-term ageing."),
    (("primitivo", "nero d avola", "montepulciano d abruzzo", "valpolicella", "ripasso", "chianti"), 2, 6,
     "Drink within a few years."),
    # Spain / Portugal
    (("gran reserva",), 8, 20, "Gran Reserva; aged before release and keeps for a long time."),
    (("ribera del duero", "priorat", "toro"), 4, 12, "Powerful Spanish red; medium-term ageing."),
    (("reserva",), 5, 12, "Reserva; medium-term ageing."),
    (("rioja",), 3, 8, "Short to medium-term ageing."),
    (("douro",), 3, 10, "Short to medium-term ageing."),
    # New World
    (("napa", "sonoma"), 4, 12, "Structured; medium-term ageing."),
    (("barossa", "coonawarra", "margaret river"), 4, 12, "Medium-term ageing."),
]

TYPE_RULES = {
    "white": (1, 4, "Drink fresh; serve chilled."),
    "rosé": (0, 2, "Drink young; serve chilled."),
    "sparkling": (1, 5, "Drink within a few years of purchase."),
    "dessert": (5, 25, "Sweet wine; keeps for a long time."),
    "fortified": (5, 30, "Fortified wine; very long-lived."),
}

DEFAULT = (2, 6, "Drink within a few years of release.")


def estimate(wine):
    """Return a dict with from/to (years after vintage), advice and rationale."""
    wtype = (wine.get("wine_type") or "").strip().lower()
    hay = norm(" ".join(str(wine.get(k) or "") for k in ("region", "description")))
    basis = None
    if wtype in TYPE_RULES:
        f, t, advice = TYPE_RULES[wtype]
        basis = f"wine type: {wtype}"
    else:
        for keys, f, t, advice in AREA_RULES:
            hit = next((k for k in keys if re.search(r"\b" + re.escape(k) + r"\b", hay)), None)
            if hit:
                basis = f"area: {hit}"
                break
        else:
            f, t, advice = DEFAULT
            basis = "default (no area rule matched)"

    notes = [basis]
    desc = norm(wine.get("description"))
    if "magnum" in desc:
        t += 3
        notes.append("magnum +3 years")
    price = wine.get("list_price") or wine.get("purchase_price")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    if price and wtype not in TYPE_RULES and "magnum" not in desc:
        if price >= 600:
            t += 4
            notes.append("price >= 600 DKK +4 years")
        elif price >= 300:
            t += 2
            notes.append("price >= 300 DKK +2 years")
    return {"from": f, "to": t, "advice": advice, "rationale": "Estimated from " + ", ".join(notes) + "."}
