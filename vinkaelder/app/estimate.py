"""Regelbaseret estimat af drikkevindue (år efter høst).

Reglerne matches mod distrikt, beskrivelse og druer. Den mest specifikke
regel (først i listen) vinder. Bagefter justeres for flaskestørrelse og pris.
"""
import re
import unicodedata


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ").replace("_x000d_", " ")
    return re.sub(r"\s+", " ", s)


# (nøgleord, fra, til, råd)  — nøgleord matches mod distrikt + beskrivelse
AREA_RULES = [
    # Bordeaux, venstre bred
    (("pauillac", "saint estephe", "st estephe", "saint julien", "st julien", "margaux"), 8, 22,
     "Lagringsvin fra venstre bred; tanninerne skal have tid. Dekantér når den er ung."),
    (("pessac leognan", "graves"), 6, 18, "Struktureret Bordeaux; mellemlang til lang lagring."),
    (("haut medoc", "listrac", "moulis"), 6, 16, "Mellemlang lagring; drik når tanninerne er blevet bløde."),
    (("medoc",), 5, 14, "Mellemlang lagring; drik når tanninerne er blevet bløde."),
    # Bordeaux, højre bred
    (("pomerol",), 7, 20, "Merlot-domineret lagringsvin; bred drikkeplateau."),
    (("saint emilion grand cru", "st emilion grand cru"), 7, 18,
     "Grand Cru fra højre bred; mellemlang til lang lagring."),
    (("lussac", "montagne", "puisseguin", "lalande"), 4, 10, "Satellit-appellation; drik mens frugten er frisk."),
    (("saint emilion", "st emilion"), 5, 12, "Merlot-baseret; tidligere drikkeklar end venstre bred."),
    (("cotes de bordeaux", "blaye", "bourg", "castillon", "fronsac"), 3, 8, "Kort til mellemlang lagring."),
    (("bordeaux superieur",), 3, 8, "Kort til mellemlang lagring."),
    (("bordeaux",), 2, 7, "Drik inden for få år."),
    # Rhône
    (("hermitage", "cote rotie"), 8, 20, "Nordrhône-syrah med stort lagringspotentiale."),
    (("cornas",), 6, 18, "Kraftig syrah; giv den tid."),
    (("chateauneuf",), 6, 15, "Grenache-blend; bredt plateau, dekantér når den er ung."),
    (("gigondas", "vacqueyras", "rasteau", "cairanne", "lirac"), 4, 12, "Sydrhône-cru; mellemlang lagring."),
    (("crozes", "saint joseph", "st joseph"), 3, 8, "Frugtdrevet syrah; drik inden for 3–8 år."),
    (("cotes du rhone villages",), 2, 7, "Drik inden for få år."),
    (("cotes du rhone", "ventoux", "luberon"), 1, 5, "Drik ung, mens frugten er frisk."),
    # Bourgogne / Beaujolais
    (("grand cru",), 8, 20, "Grand Cru; lang lagring."),
    (("1er cru", "premier cru"), 5, 14, "Premier Cru; mellemlang lagring."),
    (("cote de nuits villages", "cote de beaune villages", "gevrey", "chambolle", "vosne", "nuits saint georges",
      "pommard", "volnay", "morey", "marsannay", "santenay", "savigny", "aloxe", "corton", "mercurey", "givry"),
     4, 10, "Village-Bourgogne; drik i perioden 4–10 år."),
    (("hautes cotes",), 3, 8, "Drik relativt tidligt; finesse frem for alder."),
    (("moulin a vent", "morgon", "cote du py", "julienas", "chenas"), 3, 10, "Struktureret Beaujolais-cru; kan lagres."),
    (("fleurie", "chiroubles", "saint amour", "regnie", "brouilly", "cote de brouilly"), 2, 6,
     "Let Beaujolais-cru; drik ung."),
    (("beaujolais",), 1, 4, "Drik ung; server let afkølet."),
    (("bourgogne", "burgund", "auxerre"), 2, 6, "Drik relativt tidligt; finesse frem for alder."),
    # Loire / Sydvest / Languedoc
    (("chinon", "bourgueil", "saumur champigny", "saint nicolas"), 4, 15, "Cabernet Franc fra Loire; overraskende lagringsdygtig."),
    (("cahors", "madiran"), 5, 15, "Tanninrig; giv den tid."),
    (("bandol",), 6, 18, "Mourvèdre-baseret; lang lagring."),
    # Italien
    (("barolo", "barbaresco"), 8, 25, "Nebbiolo; lang lagring, dekantér."),
    (("brunello",), 8, 20, "Sangiovese Grosso; lang lagring."),
    (("amarone",), 6, 18, "Koncentreret; mellemlang til lang lagring."),
    (("chianti classico riserva", "gran selezione"), 5, 12, "Riserva; mellemlang lagring."),
    (("vino nobile", "rosso di montalcino", "chianti classico"), 3, 9, "Kort til mellemlang lagring."),
    (("bolgheri", "super tuscan", "supertoscan"), 5, 15, "Bordeaux-stil fra Toscana; mellemlang lagring."),
    (("primitivo", "nero d avola", "montepulciano d abruzzo", "valpolicella", "ripasso", "chianti"), 2, 6,
     "Drik inden for få år."),
    # Spanien / Portugal
    (("gran reserva",), 8, 20, "Gran Reserva; lagret før frigivelse og holder længe."),
    (("ribera del duero", "priorat", "toro"), 4, 12, "Kraftig spansk; mellemlang lagring."),
    (("reserva",), 5, 12, "Reserva; mellemlang lagring."),
    (("rioja",), 3, 8, "Kort til mellemlang lagring."),
    (("douro",), 3, 10, "Kort til mellemlang lagring."),
    # Nye verden
    (("napa", "sonoma"), 4, 12, "Struktureret; mellemlang lagring."),
    (("barossa", "coonawarra", "margaret river"), 4, 12, "Mellemlang lagring."),
]

TYPE_RULES = {
    "hvid": (1, 4, "Drik frisk; server køligt."),
    "rosé": (0, 2, "Drik ung; server køligt."),
    "mousserende": (1, 5, "Drik inden for få år efter køb."),
    "dessert": (5, 25, "Sød vin; holder længe."),
    "hedvin": (5, 30, "Hedvin; meget holdbar."),
}

DEFAULT = (2, 6, "Drik inden for få år efter frigivelse.")


def estimate(wine):
    """Returnér dict med from/to (år efter høst), advice og rationale."""
    wtype = (wine.get("wine_type") or "").strip().lower()
    hay = norm(" ".join(str(wine.get(k) or "") for k in ("region", "description")))
    basis = None
    if wtype in TYPE_RULES:
        f, t, advice = TYPE_RULES[wtype]
        basis = f"vintype: {wtype}"
    else:
        for keys, f, t, advice in AREA_RULES:
            hit = next((k for k in keys if re.search(r"\b" + re.escape(k) + r"\b", hay)), None)
            if hit:
                basis = f"område: {hit}"
                break
        else:
            f, t, advice = DEFAULT
            basis = "standard (ingen områderegel matchede)"

    notes = [basis]
    desc = norm(wine.get("description"))
    if "magnum" in desc:
        t += 3
        notes.append("magnum +3 år")
    price = wine.get("list_price") or wine.get("purchase_price")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    if price and wtype not in TYPE_RULES and "magnum" not in desc:
        if price >= 600:
            t += 4
            notes.append("pris ≥ 600 kr +4 år")
        elif price >= 300:
            t += 2
            notes.append("pris ≥ 300 kr +2 år")
    return {"from": f, "to": t, "advice": advice, "rationale": "Estimat ud fra " + ", ".join(notes) + "."}
