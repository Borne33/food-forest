#!/usr/bin/env python3
"""Research one plant from reliable public sources and build a draft with
EVIDENCE-BASED scores (never fabricated):

  - PFAF (pfaf.org): edibility & medicinal star ratings (0-5, counted from the
    filled-apple images), edible parts, edible/medicinal/other-uses prose, and
    known hazards. PFAF is ethnobotanical -> scores get tier "E".
  - Wikipedia REST summary: a short description + common-name confirmation.
  - NYFA row (passed in): family, growth habit -> type, duration -> lifecycle,
    NY nativity, habitat, state rarity/protection.

Scores map straight from the sourced ratings; a plant with no PFAF entry keeps
0/"N" (no evidence) for the use categories — honest, and flagged for later.
Used by the batched NYFA influx (batch_research.py).
"""
import urllib.request, urllib.parse, re, time, html, os, hashlib, random

UA = {"User-Agent": "Mozilla/5.0 (native-food-forest research; abornemann33@gmail.com)"}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
PFAF_DELAY = 3.0   # seconds between real PFAF network fetches (cache hits are free)
WIKI_DELAY = 0.3
PFAF_NETWORK = True   # bulk build sets this False (cache-only); the slow trickle sets it True

def _cache_path(kind, key):
    d = os.path.join(CACHE, kind); os.makedirs(d, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    return os.path.join(d, slug + ".html")

# Disk-cached GET: every URL is fetched from the network at most once, ever.
# A missing/failed page is cached as the sentinel "__MISS__" so it is never
# re-requested. `delay` is applied ONLY on a real network fetch, not a cache hit.
def _get_cached(kind, key, url, delay=0.0, tries=3):
    p = _cache_path(kind, key)
    if os.path.exists(p):
        s = open(p, encoding="utf-8").read()
        return None if s == "__MISS__" else s
    if kind == "pfaf" and not PFAF_NETWORK:
        return None            # bulk build: never touch PFAF network, cache-only
    body = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                body = r.read().decode("utf-8", "replace"); break
        except Exception:
            if a == tries - 1: body = None
            else: time.sleep(1.5 * (a + 1))
    if delay: time.sleep(delay + random.uniform(0, 0.8))
    # Only cache a SUCCESSFUL fetch. Failures (404s, rate-limit blocks, timeouts)
    # are NOT cached, so a transient block never becomes a permanent "miss".
    if body is not None:
        open(p, "w", encoding="utf-8").write(body)
    return body

def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\[[\d,\s]+\]", "", s)      # drop PFAF citation markers like [1, 2]
    return re.sub(r"\s+", " ", s).strip()

# ---------------- PFAF ----------------
def pfaf(sci):
    url = "https://pfaf.org/user/Plant.aspx?LatinName=" + urllib.parse.quote(sci)
    h = _get_cached("pfaf", sci, url, delay=PFAF_DELAY)
    if not h or "Edibility Rating" not in h:
        return None
    # star ratings: 5 named images each; count the filled (non-grey) ones
    def rating(prefix):
        n = 0
        for k in range(1, 6):
            m = re.search(r'id="ContentPlaceHolder1_%s%d"[^>]*src="([^"]+)"' % (prefix, k), h)
            if m and "grey" not in m.group(1).lower():
                n += 1
        return n
    er, mr, our = rating("imgEdrating"), rating("imgMedRating"), rating("imgOtherUseRating")
    # text fields: capture from a control's id to the next control id, then clean
    def field(cid):
        m = re.search(r'id="ContentPlaceHolder1_%s"' % cid, h)
        if not m:
            return ""
        seg = h[m.end(): m.end() + 3000]
        seg = re.split(r'id="ContentPlaceHolder1_', seg)[0]
        return _clean(seg)
    edible = field("txtEdibleUses")            # "Edible Parts: X  Edible Uses: <prose>"
    ep = prose = ""
    me = re.search(r"Edible Parts?:?\s*(.*?)\s*Edible Uses?:?\s*(.*)$", edible, re.S | re.I)
    if me:
        ep, prose = me.group(1).strip(" .;"), me.group(2).strip()
    else:
        prose = edible
    return dict(url=url, er=er, mr=mr, our=our, edible_parts=ep, edible_uses=prose,
                medicinal_uses=field("txtMedicinalUses"), other_uses=field("txtOtherUses"),
                hazards=field("lblKnownHazards"), cultivation=field("txtCultivationDetails"),
                habitats=field("txtHabitats"))

# ---------------- Wikipedia ----------------
def wiki(sci):
    # MediaWiki extracts API: full-article plain text, with redirects=1 so
    # synonyms resolve to the accepted page. Far better than the intro-only REST
    # summary for detecting documented edible/medicinal uses.
    import json as _j
    url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
           "&prop=extracts&explaintext=1&titles=" + urllib.parse.quote(sci.replace(" ", "_")))
    h = _get_cached("wiki", sci, url, delay=WIKI_DELAY)
    if not h: return None
    try:
        d = _j.loads(h)
    except Exception:
        return None
    pages = (d.get("query", {}) or {}).get("pages", {}) or {}
    for pid, pg in pages.items():
        if pid == "-1": return None
        ex = pg.get("extract") or ""
        if len(ex) < 60: return None
        title = pg.get("title", "")
        return dict(url="https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                    extract=ex, title=title)
    return None

# ---------------- score mapping (evidence -> 0-10 + tier) ----------------
WOODY = {"Tree", "Shrub", "Vine"}
def life_score(typ, duration):
    d = (duration or "").lower()
    if "annual" in d: return [0, "A"]
    if "biennial" in d: return [2, "A"]
    if typ in WOODY: return [10, "A"]
    return [8, "A"]                          # herbaceous perennial

def build(sci, common, family, typ, duration, native, habitat, pf, wk):
    N = [0, "N"]
    scores = {"raw": N[:], "cooked": N[:], "life": life_score(typ, duration),
              "eco": N[:], "materials": N[:], "med": N[:]}
    edible_parts = prep = risks = other = sun = soil = ""
    if pf:
        eu = (pf["edible_uses"] or "").lower()
        base = min(10, pf["er"] * 2)
        has_raw = "raw" in eu
        has_cooked = any(w in eu for w in ("cook", "boil", "roast", "fried", "steam", "baked", "sauté", "saute"))
        if pf["er"] > 0:
            if has_raw: scores["raw"] = [base, "E"]
            if has_cooked: scores["cooked"] = [base, "E"]
            if not has_raw and not has_cooked:      # edible but prep unstated -> credit cooked
                scores["cooked"] = [max(2, base - 2), "E"]
        if pf["mr"] > 0: scores["med"] = [min(10, pf["mr"] * 2), "E"]
        if pf.get("our", 0) > 0: scores["materials"] = [min(10, pf["our"] * 2), "A"]
        edible_parts = pf["edible_parts"]
        prep = pf["edible_uses"]
        risks = pf["hazards"]
        other = pf["other_uses"]
        # sun / soil from PFAF cultivation prose
        cult = pf.get("cultivation", "")
        lights = [x for x in ("full sun", "semi-shade", "part shade", "full shade", "dappled shade") if x in cult.lower()]
        if lights: sun = "; ".join(dict.fromkeys(l.capitalize() for l in lights))
        for s in re.split(r"(?<=[.])\s+", cult):
            if "soil" in s.lower(): soil = s.strip(); break
    # If PFAF gave no use data, credit CONSERVATIVE scores from an explicit
    # Wikipedia statement (tier A = anecdotal/encyclopedic). Only when the text
    # clearly says so — otherwise leave 0/"N" for the later PFAF trickle to fill.
    # HIGH-PRECISION Wikipedia signal only (recall is filled later by the PFAF
    # trickle, which has structured ratings + hazards). Never credit any use if
    # the article mentions toxicity anywhere — safety over coverage.
    if (not pf or pf["er"] == 0) and wk:
        ex = wk["extract"].lower()
        toxic = bool(re.search(r"poison|toxic|inedible|not edible|do not eat|harmful if", ex))
        if not toxic:
            parts = r"(?:fruit|berr|leaf|leaves|seed|nut|root|tuber|shoot|stem|flower|greens?|bulb|sap|grain)"
            edible = bool(re.search(r"\bedible\b[^.]{0,60}\b" + parts, ex)
                          or re.search(parts + r"[^.]{0,40}\bedible\b", ex)
                          or re.search(r"eaten (?:raw|cooked)|leaf vegetable|used as a (?:vegetable|potherb)|\bpotherb\b|cooked green", ex))
            if edible:
                if re.search(r"eaten raw|raw in salad|\bsalads?\b|eaten fresh|out of hand", ex): scores["raw"] = [5, "A"]
                if re.search(r"\bcook|boil|roast|steam|baked|fried|blanch|potherb|leaf vegetable|cooked green", ex): scores["cooked"] = [5, "A"]
                if scores["raw"][0] == 0 and scores["cooked"][0] == 0: scores["cooked"] = [4, "A"]
            # medicinal only on an explicit, strong phrase (not bare "astringent")
            if re.search(r"traditional medicine|used medicinally|medicinal (?:plant|herb|uses?)|herbal medicine|folk medicine", ex):
                scores["med"] = [4, "A"]
    # ecological value: native habitat baseline (structural), tier A
    if native == "Y" and scores["eco"][0] == 0:
        scores["eco"] = [4, "A"]
    sources = []
    if pf: sources.append(["Plants For A Future (PFAF)", pf["url"]])
    if wk: sources.append(["Wikipedia", wk["url"]])
    sources.append(["New York Flora Atlas", "https://newyork.plantatlas.usf.edu/"])
    life = (duration or "").strip() + ((" " + typ.lower()) if duration else typ.lower())
    draft = dict(common=common or sci, sci=sci, family=family or "", type=typ,
        life=life, edible_parts=edible_parts, other_uses=other, prep=prep, harvest="",
        sun=sun, soil=soil, risks=risks, buy="",
        native_states=["NY"] if native == "Y" else [], native_regions=[],
        native_to_us=True, invasive_states=[], invasive_everywhere=False, dec_priority=False,
        nf=(family == "Fabaceae"), pol=False, scores=scores, sources=sources,
        hardiness_zones="", deer_resistant=False, native_north_america=True, native_americas=False)
    # provenance flags (not COLUMNS; used by the runner for reporting/enrichment)
    draft["_meta"] = dict(pfaf=bool(pf), wiki=bool(wk), er=(pf["er"] if pf else None),
                          mr=(pf["mr"] if pf else None), habitat=habitat)
    return draft

def research(sci, common, family, typ, duration, native, habitat):
    pf = pfaf(sci)   # pacing/caching handled inside _get_cached
    wk = wiki(sci)
    return build(sci, common, family, typ, duration, native, habitat, pf, wk)
