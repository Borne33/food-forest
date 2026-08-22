#!/usr/bin/env python3
"""
Vendor inventory: turn a vendor's published plant list into vendor_plants rows
(SHOPS_PLAN.md Phase 4 / STAGE_GATES.md S5).

MATCHING POLICY (decision D5 — deliberately strict):
  1. exact scientific name         -> link
  2. exact plant_synonyms hit      -> link
  3. exact common name, and ONLY if that common name is unambiguous across the
     whole plants table            -> link
  anything else                    -> vendor_plants_unmatched, for a human

No fuzzy matching. At ~2,500 plants a fuzzy matcher quietly mis-files cultivars
and near-homonyms, and a wrong "where to buy" link is worse than a missing one.

Cultivars keep their raw string, link to the straight species and are flagged
is_cultivar, because the site's whole posture favours straight species.

Sources:
  --vendor ernst-conservation-seeds   WooCommerce Store API (public feed)
  --vendor <slug> --file list.json    a hand-built list (see vendors/lists/)

Usage:
  python3 vendor_inventory.py --vendor ernst-conservation-seeds --limit 60 --dry-run
  python3 vendor_inventory.py --vendor ernst-conservation-seeds --limit 60
  python3 vendor_inventory.py --vendor mill-street-gardens --file vendors/lists/mill-street.json
"""
import argparse
import json
import html
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vendors_seed import load_env, supabase  # noqa: E402  (shared helpers)

UA = "native-food-forest-planner/1.0 (+https://borne33.github.io/food-forest/)"

# "Eryngium yuccifolium (Rattlesnake Master) is an erect-growing..."
# The trailing "(" is REQUIRED. Without it this happily matched prose like
# "Used for", "Cool season" and "Attractive rhizomatous" as scientific names.
LEAD_BINOMIAL = re.compile(
    r"^\s*([A-Z][a-z]{2,}\s+[a-z][a-z\-]{2,}"
    r"(?:\s+(?:var\.|ssp\.|subsp\.)\s+[a-z\-]+)?)\s*\(")
CULTIVAR = re.compile(r"['‘’\"]([^'‘’\"]{2,40})['‘’\"]")
# Ernst names carry provenance, not cultivar: "Rattlesnake Master, SC Ecotype"
ECOTYPE = re.compile(r",\s*([A-Z]{2}(?:[ /-][A-Z]{2})*)\s+Ecotype\s*$", re.I)
STRIP_TAGS = re.compile(r"<[^>]+>")


# ── reference data ────────────────────────────────────────────────────────
def load_plants(env):
    rows, frm = [], 0
    while True:
        page = supabase(env, "GET",
                        "plants?select=id,common,sci&order=id&limit=1000&offset=%d" % frm) or []
        rows += page
        if len(page) < 1000:
            break
        frm += 1000
    return rows


def sku_code(sci):
    """Ernst's SKU convention: first 3 letters of genus + first 3 of species.
    ERYYUC = Eryngium yuccifolium, ANDGER = Andropogon gerardi. Vendor-specific,
    but a precise key — and it survives spelling variance our names disagree on
    (we hold 'gerardi', Ernst 'gerardii'; the code matches either way)."""
    w = (sci or "").split()
    return (w[0][:3] + w[1][:3]).upper() if len(w) >= 2 else None


def norm(t):
    """Lower-case, and fold the typographic apostrophes to a plain one.

    Not fuzzy matching — the same characters, written the way a typesetter does.
    Ernst writes "Culver’s Root" with U+2019; the plants table has "Culver's
    Root" with U+0027, and an exact string match calls those different plants.
    That silently lost Culver's Root, Gray's Sedge and Riddell's Goldenrod. 145
    common names here use a straight apostrophe and 116 use a curly one, so this
    cuts both ways."""
    return (t or "").strip().lower().replace("’", "'").replace("‘", "'")


def build_index(env, plants):
    by_sci, by_common, common_counts = {}, {}, {}
    code_hits = {}
    for p in plants:
        if p.get("sci"):
            by_sci[p["sci"].strip().lower()] = p["id"]
            c6 = sku_code(p["sci"])
            if c6:
                code_hits.setdefault(c6, []).append(p["id"])
        c = norm(p.get("common"))
        if c:
            common_counts[c] = common_counts.get(c, 0) + 1
            by_common[c] = p["id"]
    # a name/code shared by two plants can never be matched safely
    ambiguous = {c for c, n in common_counts.items() if n > 1}
    by_code = {k: v[0] for k, v in code_hits.items() if len(v) == 1}
    amb_code = {k for k, v in code_hits.items() if len(v) > 1}
    syn = {}
    for r in supabase(env, "GET", "plant_synonyms?select=plant_id,name,kind&limit=10000") or []:
        syn[norm(r["name"])] = r["plant_id"]
    return {"sci": by_sci, "common": by_common, "ambiguous": ambiguous,
            "syn": syn, "code": by_code, "amb_code": amb_code}


def match(raw_sci, raw_common, idx, code=None):
    """Return (plant_id, how) or (None, reason). Strict — see D5."""
    s = norm(raw_sci)
    if s:
        if s in idx["sci"]:
            return idx["sci"][s], "sci"
        base = " ".join(s.split()[:2])          # drop infraspecific rank
        if base in idx["sci"]:
            return idx["sci"][base], "sci_base"
        if s in idx["syn"]:
            return idx["syn"][s], "synonym"
        # A synonym was only ever tested against the WHOLE string, so a listing
        # like "Sambucus nigra Syn: S. canadensis" missed even though
        # "Sambucus nigra" is a recorded synonym. Still exact, still D5-strict —
        # just applied to the base binomial as well.
        if base in idx["syn"]:
            return idx["syn"][base], "synonym_base"
    if code:
        c6 = code[:6].upper()
        if c6 in idx["amb_code"]:
            return None, "code_ambiguous"
        if c6 in idx["code"]:
            return idx["code"][c6], "sku_code"
    c = norm(raw_common)
    if c:
        if c in idx["ambiguous"]:
            return None, "common_ambiguous"
        if c in idx["common"]:
            return idx["common"][c], "common"
    return None, "no_match" if (s or c or code) else "no_name"


# ── adapters ──────────────────────────────────────────────────────────────
def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def adapter_ernst(limit):
    """Ernst Conservation Seeds — public WooCommerce Store API."""
    out, page = [], 1
    while len(out) < limit:
        batch = fetch_json("https://www.ernstseed.com/wp-json/wc/store/products"
                           "?per_page=50&page=%d" % page)
        if not batch:
            break
        for p in batch:
            sku = p.get("sku") or ""
            if sku.startswith("ERNMX"):     # seed MIXES are not a single species
                continue
            name = html.unescape(p.get("name") or "")
            desc = html.unescape(STRIP_TAGS.sub("", p.get("description") or ""))
            m = LEAD_BINOMIAL.match(desc)
            sci = m.group(1) if m else None
            eco = ECOTYPE.search(name)
            common = ECOTYPE.sub("", name).strip()
            price = p.get("prices") or {}
            cents = None
            try:
                cents = int(price.get("price")) if price.get("price") is not None else None
            except (TypeError, ValueError):
                cents = None
            out.append({
                "raw_name": name, "raw_sci": sci, "code": sku,
                "form": "seed",
                "size": (eco.group(1).upper() + " ecotype") if eco else None,
                "price_cents": cents, "unit": "per pound (bulk seed)",
                "stock": "in_stock" if p.get("is_in_stock") else "out",
                "url": p.get("permalink"),
                "source": "feed",
            })
            if len(out) >= limit:
                break
        page += 1
        time.sleep(1.5)
    return out


def adapter_file(path):
    return json.loads(Path(path).read_text())


# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True, help="vendor slug")
    ap.add_argument("--file", help="JSON list instead of a live adapter")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    vend = supabase(env, "GET", "vendors?select=id,slug,name&slug=eq." + args.vendor)
    if not vend:
        sys.exit("no vendor with slug %r" % args.vendor)
    vendor = vend[0]

    if args.file:
        items = adapter_file(args.file)[: args.limit]
    elif args.vendor == "ernst-conservation-seeds":
        items = adapter_ernst(args.limit)
    else:
        sys.exit("no adapter for %r — pass --file with a hand-built list" % args.vendor)
    print("fetched %d items for %s" % (len(items), vendor["name"]))

    plants = load_plants(env)
    idx = build_index(env, plants)
    print("index: %d plants · %d ambiguous common names · %d synonyms · "
          "%d unique SKU codes (%d ambiguous)"
          % (len(plants), len(idx["ambiguous"]), len(idx["syn"]),
             len(idx["code"]), len(idx["amb_code"])))

    rows, misses, how = [], [], {}
    for it in items:
        # a cultivar is named in the scientific string, not the common name
        cult = CULTIVAR.search(it.get("cultivar_src") or it.get("raw_sci") or it.get("raw_name") or "")
        pid, reason = match(it.get("raw_sci"), it.get("raw_name"), idx, it.get("code"))
        how[reason] = how.get(reason, 0) + 1
        if pid:
            rows.append({
                "vendor_id": vendor["id"], "plant_id": pid,
                "raw_name": it.get("raw_name"), "raw_sci": it.get("raw_sci"),
                "is_cultivar": bool(cult), "cultivar_name": cult.group(1) if cult else "",
                "form": it.get("form"), "size": it.get("size") or "",
                "price_cents": it.get("price_cents"), "unit": it.get("unit"),
                "stock": it.get("stock") or "unknown",
                "source": it.get("source") or "manual",
                "confidence": "high" if reason in ("sci", "sci_base", "synonym", "sku_code") else "medium",
                "url": it.get("url"),
            })
        else:
            misses.append({"vendor_id": vendor["id"], "raw_name": it.get("raw_name"),
                           "raw_sci": it.get("raw_sci"), "form": it.get("form")})

    print("\nmatch breakdown: %s" % json.dumps(how, sort_keys=True))
    print("matched %d, unmatched %d" % (len(rows), len(misses)))
    priced = [r for r in rows if r["price_cents"]]
    print("price present on %d/%d matched rows" % (len(priced), len(rows)))
    if args.dry_run:
        for r in rows[:12]:
            print("  + %-42s -> plant %s (%s)" % ((r["raw_sci"] or r["raw_name"])[:42], r["plant_id"], r["confidence"]))
        for m in misses[:12]:
            print("  ? %-42s unmatched" % ((m["raw_sci"] or m["raw_name"] or "")[:42]))
        print("\nDry run — nothing written.")
        return

    seen, deduped = set(), []
    for r in rows:
        k = (r["vendor_id"], r["plant_id"], r["form"], r["cultivar_name"], r["size"])
        if k in seen:
            continue
        seen.add(k); deduped.append(r)
    if len(deduped) != len(rows):
        print("collapsed %d duplicate keys within the batch" % (len(rows) - len(deduped)))
    rows = deduped
    if rows:
        supabase(env, "POST", "vendor_plants?on_conflict=vendor_id,plant_id,form,cultivar_name,size", rows,
                 {"Prefer": "resolution=merge-duplicates"})
    if misses:
        supabase(env, "POST", "vendor_plants_unmatched", misses, {"Prefer": "return=minimal"})
    print("wrote %d vendor_plants, %d unmatched" % (len(rows), len(misses)))


if __name__ == "__main__":
    main()
