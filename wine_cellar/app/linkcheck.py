"""Check that an offer's link really points at that wine's product page.

The web search agent often returns plausible but wrong URLs (a shop's front page, a category, another wine, or a
URL that does not exist). For each offer this module:
1. opens the URL and checks that the page is the product page for this wine and vintage (product name from
   JSON-LD / og:title / <title> / <h1> must contain the producer and wine name, and the vintage);
2. if the page is a listing (or the wrong wine), looks for a link on that page to the right wine and checks that;
3. if the URL does not work, tries the shop's own search page and picks the matching product from the results.
Only a page that passes the check is used as the link. Otherwise the offer gets a Google search limited to the
shop's site, and is marked as not confirmed.
"""
import gzip
import html as htmlmod
import json
import re
import unicodedata
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
MAX_BYTES = 2_000_000
SEARCH_PATHS = ["/search?q={q}", "/?s={q}&post_type=product", "/catalogsearch/result/?q={q}", "/soeg?q={q}",
                "/search?query={q}", "/shop/search?q={q}"]
STOP = {"chateau", "domaine", "dom", "the", "and", "les", "des", "del", "della", "von", "und", "vin", "vine", "wine",
        "rouge", "red", "rod", "rodvin", "aoc", "aop", "doc", "docg", "igt", "cl", "flaske", "bottle", "tilbud", "kob",
        "saint", "sainte", "st", "ste", "mis", "bouteille", "estate", "cuvee", "hvidvin", "rosevin", "magnum", "nyhed",
        "udsalg", "kasse", "stk", "pris", "spar", "fra", "med"}
YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")


def fold(s):
    s = str(s or "").translate(str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss"}))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tokens(s):
    return {t for t in fold(s).split() if len(t) >= 3 and t not in STOP and not YEAR.fullmatch(t)}


def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                               "Accept-Language": "da,en;q=0.8", "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(MAX_BYTES)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        charset = r.headers.get_content_charset() or "utf-8"
        ctype = r.headers.get("Content-Type") or ""
        if "html" not in ctype and "xml" not in ctype:
            raise ValueError("not an html page")
        return r.geturl(), raw.decode(charset, "replace")


def _ld_products(page):
    out = []

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            t = x.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                offers = x.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = None
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                out.append({"name": str(x.get("name") or ""), "price": price, "url": x.get("url")})
            for k in ("@graph", "itemListElement", "item", "mainEntity"):
                if k in x:
                    walk(x[k])

    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            walk(json.loads(m.group(1).strip()))
        except ValueError:
            continue
    return out


def _meta(page, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(prop), page, re.I) \
        or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(prop), page, re.I)
    return htmlmod.unescape(m.group(1)) if m else ""


def _tag(page, tag):
    m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), page, re.S | re.I)
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""


def page_info(url, page):
    prods = _ld_products(page)
    names = [p["name"] for p in prods if p["name"]]
    title = _meta(page, "og:title") or _tag(page, "title")
    h1 = _tag(page, "h1")
    canon = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', page, re.I)
    price = None
    if len(prods) == 1 and prods[0]["price"] not in (None, ""):
        price = prods[0]["price"]
    price = price or _meta(page, "product:price:amount") or _meta(page, "og:price:amount") or None
    try:
        price = float(str(price).replace(",", ".")) if price not in (None, "") else None
    except ValueError:
        price = None
    anchors = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page, re.S | re.I):
        href = urllib.parse.urljoin(url, htmlmod.unescape(m.group(1)))
        text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        title_attr = re.search(r'title=["\']([^"\']+)', m.group(0))
        anchors.append((href, f"{text} {title_attr.group(1) if title_attr else ''}"))
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    body_years = set(YEAR.findall(re.sub(r"<[^>]+>", " ", body)))
    return {"body_years": body_years, "products": prods, "names": names, "title": title, "h1": h1, "price": price, "anchors": anchors,
            "canonical": urllib.parse.urljoin(url, canon.group(1)) if canon else None}


def _want(o):
    prod, name = tokens(o.get("producer")), tokens(o.get("wine"))
    return prod | name, prod, name


def name_score(o, text):
    """Share of the wine's distinctive words found in text, and whether the vintage matches."""
    want, prod, _ = _want(o)
    if not want:
        return 0, "none"
    words = fold(text).split()
    have = set(words)
    score = len(want & have) / len(want)
    if prod and not (prod & have):          # the producer must be there
        score = min(score, 0.4)
    # a distinctive word right before the name means another wine (Gruaud Larose is not Larose)
    ok = want | tokens(o.get("region")) | tokens(o.get("country")) | tokens(o.get("grapes")) | tokens(o.get("shop"))
    first = next((i for i, w in enumerate(words) if w in want), None)
    if first is not None and any(len(w) >= 3 and w not in STOP and w not in ok and not w.isdigit()
                                 for w in words[max(0, first - 2):first]):
        score -= 0.5
    v = o.get("vintage")
    years = set(YEAR.findall(text))
    if not v:
        year = "yes"
    else:
        year = "yes" if str(v) in years else ("other" if years else "none")
    return score, year


def is_product_page(o, info):
    """The page is this wine's product page (right name; right vintage in the name, or in the page when the
    name has no year)."""
    if len(info["products"]) > 1:            # a list of products: a category or search page
        cands = []
    else:
        cands = info["names"] + [info["h1"], info["title"]]
    for text in cands:
        if not text.strip():
            continue
        s, y = name_score(o, text)
        if s >= 0.7 and (y == "yes" or (y == "none" and str(o.get("vintage")) in info["body_years"])):
            return True
    return False


def best_anchor(o, url, info, tried):
    host = urllib.parse.urlparse(url).hostname
    best, best_s = None, 0
    for href, text in info["anchors"]:
        p = urllib.parse.urlparse(href)
        if p.hostname != host or href in tried or p.path.strip("/") == "":
            continue
        s, y = name_score(o, f"{text} {urllib.parse.unquote(p.path).replace('-', ' ').replace('_', ' ')}")
        if y == "other":
            continue
        s += 0.05 if y == "yes" else 0
        if s > best_s:
            best, best_s = href, s
    return best if best_s >= 0.7 else None


def _try(o, url, tried, depth=0):
    """Return (product_url, info) when url is, or links to, the product page."""
    if url in tried or len(tried) >= 8:
        return None
    tried.add(url)
    try:
        final, page = fetch(url)
    except Exception:  # noqa: BLE001
        return None
    tried.add(final)
    info = page_info(final, page)
    if is_product_page(o, info):
        return info["canonical"] or final, info
    if depth == 0:
        nxt = best_anchor(o, final, info, tried)
        if nxt:
            return _try(o, nxt, tried, 1)
    return None


def _name(o):
    """Producer + wine name, without the producer twice."""
    prod, wine = str(o.get("producer") or ""), str(o.get("wine") or "")
    return wine if not prod or fold(prod) in fold(wine) else f"{prod} {wine}"


def site_search(o, host):
    q = " ".join(str(x) for x in (_name(o), o.get("vintage")) if x)
    return "https://www.google.com/search?q=" + urllib.parse.quote(f"site:{host} {q}" if host else q)


def check(o):
    url = str(o.get("url") or "")
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").removeprefix("www.") or None
    tried, found = set(), None
    if url.startswith("http"):
        found = _try(o, url, tried)
        if not found and host:
            q = urllib.parse.quote_plus(_name(o))
            for path in SEARCH_PATHS:
                if len(tried) >= 8:
                    break
                found = _try(o, f"{p.scheme}://{p.netloc}{path.format(q=q)}", tried)
                if found:
                    break
    res = {"checked": True, "agent_url": url}
    if found:
        link, info = found
        res.update(url=link, link_ok=True, page_price=round(info["price"]) if info["price"] else None)
    else:
        res.update(url=site_search(o, host), link_ok=False, page_price=None)
    return res


def check_all(offers, workers=4):
    def one(o):
        try:
            o.update(check(o))
        except Exception:  # noqa: BLE001
            o.update(checked=True, link_ok=False, url=site_search(o, None), agent_url=o.get("url"))
        pp, price, before = o.get("page_price"), o.get("price_dkk"), o.get("normal_price_dkk")
        near = lambda a, b: a and b and abs(a - b) / b <= 0.03  # noqa: E731
        if pp and price and not near(pp, price) and not near(pp, before):
            # a multi-buy offer often shows the single-bottle price on the page; just show it, do not change the offer
            o["price_note"] = f"The shop's page shows {pp} DKK"
        return o
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, offers))
