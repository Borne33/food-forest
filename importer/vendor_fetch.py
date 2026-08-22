#!/usr/bin/env python3
"""
Automated inventory refresh (SHOPS_PLAN.md Phase 7, STAGE_GATES.md S9).

Re-reads a vendor's published product feed, diffs it against what
`vendor_plants` already holds, and — only when asked — applies the change.

WHAT THE AUGUST 2026 PROBE FOUND, because it shapes this whole file:
  3 of 44 vendors expose a public product feed, and only ONE of them
  (Ernst Conservation Seeds, 205 rows) is a native-plant source. The two
  biggest catalogues in the database have no public feed and will not get
  one by this route — Prairie Moon is Magento (catalogue API needs a token)
  and the HGCNY list is a PDF. See importer/vendors/feed_probe.json.

So this is deliberately NOT a platform-adapter framework. It is a refresh
loop that takes items from a feed OR from a file, and the file path is the
one that scales here — vendor-supplied CSVs, per SHOPS_PLAN D4.

SAFETY, which is the actual point (S9 item 1: "a feed that fails should
leave rows alone, not mark them out"):
  · --dry-run is the DEFAULT. Writing needs --apply.
  · A fetch that raises, or returns nothing, touches NOTHING for that vendor.
  · A feed that comes back suspiciously short (< SHRINK_FLOOR of the rows we
    already hold) still applies prices and additions, but REFUSES to mark
    anything out of stock, and says so. A half-loaded catalogue reporting
    "out of stock" on a nursery's whole range is the worst thing this could do.
  · Rows are never deleted. A row the feed stops mentioning goes to
    stock='unknown' — an explicit state, per D4 — not 'out'.
  · Requests are paced and capped; --max-pages bounds a runaway feed.

Usage:
  python3 vendor_fetch.py                                  # dry-run, every feed vendor
  python3 vendor_fetch.py --vendor ernst-conservation-seeds
  python3 vendor_fetch.py --vendor ernst-conservation-seeds --apply
  python3 vendor_fetch.py --vendor mill-street-gardens --file vendors/lists/mill.json
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vendors_seed import load_env, supabase                      # noqa: E402
from vendor_inventory import (build_index, load_plants, match,    # noqa: E402
                              CULTIVAR, LEAD_BINOMIAL, STRIP_TAGS)

# A seed MIX is not a species, and filing one against a single plant is exactly
# the wrong "where to buy" that the strict D5 matcher exists to prevent. The old
# hand-written Ernst adapter dropped these by SKU prefix (ERNMX); the name is the
# signal that generalises.
MIX = re.compile(r"\b(mix|mixes|mixture|blend)\b", re.I)

# vendor_inventory's ECOTYPE only catches a trailing bare state code (", NY
# Ecotype"). Ernst's real listings are "Long Island-NY Ecotype", "NY4 Ecotype",
# "Coastal Plain GA Ecotype", "Fort Indiantown Gap-PA Ecotype" — and losing them
# collapsed 13 named Switchgrass selections onto one row. A regional ecotype is
# not a packaging variant to a native-plant buyer; it is the product. Kept local
# rather than widened in vendor_inventory, whose adapter upper-cases the capture
# and would render "LONG ISLAND-NY".
ECOTYPE_ANY = re.compile(r",\s*(.+?)\s+Ecotype\s*$", re.I)

PROBE = HERE / "vendors" / "feed_probe.json"
UA = ("native-food-forest-planner/1.0 "
      "(+https://borne33.github.io/food-forest/; contact via site)")
PAUSE = 1.5
SHRINK_FLOOR = 0.60      # below this share of known rows, do not mark anything out


# ── fetching ──────────────────────────────────────────────────────────────
def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def money_cents(v):
    """Feeds disagree: Woo Store API sends integer cents, Shopify sends '12.00'."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(round(float(s) * 100)) if "." in s else int(s)
    except (TypeError, ValueError):
        return None


def read_woocommerce(base, max_pages):
    """WooCommerce Store API — public, paginated, documented."""
    out, page = [], 1
    while page <= max_pages:
        batch = get_json("%s?per_page=50&page=%d" % (base, page))
        if not batch:
            break
        for p in batch:
            name = html.unescape(p.get("name") or "")
            desc = html.unescape(STRIP_TAGS.sub("", p.get("description") or ""))
            m = LEAD_BINOMIAL.match(desc)
            eco = ECOTYPE_ANY.search(name)
            prices = p.get("prices") or {}
            out.append({
                # raw_name keeps the ecotype for display; match_name drops it, or
                # the common-name lookup fails on every regional selection
                "raw_name": name,
                "match_name": ECOTYPE_ANY.sub("", name).strip() or name,
                "raw_sci": m.group(1) if m else None,
                "code": p.get("sku") or "",
                "size": (eco.group(1) + " ecotype") if eco else None,
                "price_cents": money_cents(prices.get("price")),
                "stock": "in_stock" if p.get("is_in_stock") else "out",
                "url": p.get("permalink"),
            })
        page += 1
        time.sleep(PAUSE)
    return out


def read_shopify(base, max_pages):
    """Shopify products.json — public, paginated, documented."""
    out, page = [], 1
    while page <= max_pages:
        data = get_json("%s?limit=250&page=%d" % (base, page))
        items = data.get("products") if isinstance(data, dict) else data
        if not items:
            break
        for p in items:
            variants = p.get("variants") or [{}]
            v = variants[0]
            body = html.unescape(STRIP_TAGS.sub("", p.get("body_html") or ""))
            m = LEAD_BINOMIAL.match(body)
            avail = any(x.get("available") for x in variants)
            title = html.unescape(p.get("title") or "")
            out.append({
                "raw_name": title,
                "match_name": ECOTYPE_ANY.sub("", title).strip() or title,
                "raw_sci": m.group(1) if m else None,
                "code": v.get("sku") or "",
                "size": (v.get("title") or "").strip() if (v.get("title") or "") != "Default Title" else None,
                "price_cents": money_cents(v.get("price")),
                "stock": "in_stock" if avail else "out",
                "url": None,
            })
        page += 1
        time.sleep(PAUSE)
    return out


READERS = {"woocommerce": read_woocommerce,
           "shopify_root": read_shopify, "shopify_all": read_shopify}


# ── diffing ───────────────────────────────────────────────────────────────
def key_of(row):
    return (row.get("plant_id"), (row.get("form") or ""),
            (row.get("cultivar_name") or ""), (row.get("size") or ""))


def build_rows(items, vendor_id, idx, default_form, default_unit):
    """Feed items -> vendor_plants shape, with the strict D5 matcher."""
    rows, misses, how = [], [], {}
    for it in items:
        if MIX.search(it.get("raw_name") or ""):
            how["mix_skipped"] = how.get("mix_skipped", 0) + 1
            continue
        cult = CULTIVAR.search(it.get("raw_sci") or it.get("raw_name") or "")
        pid, reason = match(it.get("raw_sci"),
                            it.get("match_name") or it.get("raw_name"),
                            idx, it.get("code"))
        how[reason] = how.get(reason, 0) + 1
        if not pid:
            misses.append({"vendor_id": vendor_id, "raw_name": it.get("raw_name"),
                           "raw_sci": it.get("raw_sci"), "form": default_form})
            continue
        rows.append({
            "vendor_id": vendor_id, "plant_id": pid,
            "raw_name": it.get("raw_name"), "raw_sci": it.get("raw_sci"),
            "is_cultivar": bool(cult), "cultivar_name": cult.group(1) if cult else "",
            "form": default_form, "size": it.get("size") or "",
            "price_cents": it.get("price_cents"), "unit": default_unit,
            "stock": it.get("stock") or "unknown", "source": "feed",
            "confidence": "high" if reason in ("sci", "sci_base", "synonym", "sku_code") else "medium",
            "url": it.get("url"),
        })
    # (vendor_id, plant_id, form, cultivar_name, size) is a UNIQUE index, so a
    # feed listing the same plant twice at the same size would make PostgREST
    # refuse the whole batch: "ON CONFLICT DO UPDATE cannot affect row a second
    # time". Collapse them here, keeping the first, and say how many.
    seen, deduped, dupes = set(), [], []
    for r in rows:
        k = key_of(r)
        if k in seen:
            dupes.append(r)
            continue
        seen.add(k)
        deduped.append(r)
    if dupes:
        how["duplicate_key"] = len(dupes)
        for r in dupes[:6]:
            print("    ! duplicate key, kept the first: %s" % (r.get("raw_name") or "")[:60])
    return deduped, misses, how


def diff(existing, fresh):
    have = {key_of(r): r for r in existing}
    seen = set()
    added, price, stock, same = [], [], [], []
    for r in fresh:
        k = key_of(r)
        seen.add(k)
        old = have.get(k)
        if not old:
            added.append(r)
            continue
        changed = False
        if (old.get("price_cents") or None) != (r.get("price_cents") or None):
            price.append((old, r)); changed = True
        if (old.get("stock") or "unknown") != (r.get("stock") or "unknown"):
            stock.append((old, r)); changed = True
        if not changed:
            same.append(r)
    vanished = [r for k, r in have.items() if k not in seen]
    return {"added": added, "price": price, "stock": stock,
            "same": same, "vanished": vanished}


def money(c):
    return "—" if c is None else "$%.2f" % (c / 100.0)


# ── per-vendor run ────────────────────────────────────────────────────────
def refresh(env, vendor, items_fn, idx, args, note):
    name = vendor["name"]
    print("\n" + "=" * 72)
    print("%s  (%s)" % (name, vendor["slug"]))
    print("source: %s" % note)

    existing = supabase(env, "GET",
                        "vendor_plants?select=*&vendor_id=eq.%d" % vendor["id"]) or []
    print("holding %d rows" % len(existing))

    try:
        items = items_fn()
    except urllib.error.HTTPError as e:
        print("  FETCH FAILED — HTTP %s. Nothing touched." % e.code)
        return "failed"
    except Exception as e:                                   # noqa: BLE001
        print("  FETCH FAILED — %s: %s. Nothing touched." % (type(e).__name__, e))
        return "failed"
    if not items:
        print("  Feed returned no items. Nothing touched.")
        return "empty"
    print("fetched %d items" % len(items))

    rows, misses, how = build_rows(items, vendor["id"], idx,
                                   args.form, args.unit)
    print("matched %d, unmatched %d  %s"
          % (len(rows), len(misses), json.dumps(how, sort_keys=True)))

    d = diff(existing, rows)
    # The guard. A partially-loaded catalogue that reports every missing row as
    # "out of stock" would empty a nursery's shelves on the site overnight.
    share = (len(rows) / len(existing)) if existing else 1.0
    thin = bool(existing) and share < SHRINK_FLOOR
    if thin:
        print("  ⚠ feed covers only %.0f%% of the %d rows already held — "
              "below the %.0f%% floor." % (share * 100, len(existing), SHRINK_FLOOR * 100))
        print("    Prices and additions still apply; NOTHING will be marked out of stock.")

    print("\n  new            %d" % len(d["added"]))
    print("  price changed  %d" % len(d["price"]))
    print("  stock changed  %d" % len(d["stock"]))
    print("  unchanged      %d" % len(d["same"]))
    print("  not in feed    %d%s" % (len(d["vanished"]),
                                     "  (left alone — thin feed)" if thin else "  -> stock=unknown"))

    for old, new in d["price"][: args.show]:
        print("    price  %-42s %s -> %s"
              % ((old.get("raw_name") or "")[:42], money(old.get("price_cents")),
                 money(new.get("price_cents"))))
    for old, new in d["stock"][: args.show]:
        print("    stock  %-42s %s -> %s"
              % ((old.get("raw_name") or "")[:42], old.get("stock"), new.get("stock")))
    for r in d["added"][: args.show]:
        print("    new    %-42s %s" % ((r.get("raw_name") or "")[:42], money(r.get("price_cents"))))

    if d["vanished"] and not thin and len(d["vanished"]) > 5:
        print("\n  Heads-up: %d rows are no longer in the feed and would go to"
              " stock='unknown'." % len(d["vanished"]))
        print("    They are NOT deleted. If a batch of them look like the same"
              " products under a")
        print("    different size string, that is a re-key, not a delisting —"
              " check a few by name")
        print("    against the 'new' list before applying.")
        for r in d["vanished"][: args.show]:
            print("    gone   %-42s %s"
                  % ((r.get("raw_name") or "")[:42], r.get("size") or ""))

    if not args.apply:
        print("\n  DRY RUN — nothing written. Re-run with --apply to keep this.")
        return "dry"

    today = time.strftime("%Y-%m-%d")
    write = [dict(r, last_seen=today) for r in rows]
    if write:
        supabase(env, "POST",
                 "vendor_plants?on_conflict=vendor_id,plant_id,form,cultivar_name,size",
                 write, {"Prefer": "resolution=merge-duplicates,return=minimal"})
        print("  wrote %d rows" % len(write))
    # A row the feed stopped mentioning is UNKNOWN, not gone and not out — and
    # only when the feed looked complete enough to be believed.
    if d["vanished"] and not thin:
        for r in d["vanished"]:
            supabase(env, "PATCH", "vendor_plants?id=eq.%d" % r["id"],
                     {"stock": "unknown", "last_seen": r.get("last_seen")},
                     {"Prefer": "return=minimal"})
        print("  marked %d absent rows stock=unknown" % len(d["vanished"]))
    if misses:
        supabase(env, "POST", "vendor_plants_unmatched", misses,
                 {"Prefer": "return=minimal"})
        print("  filed %d unmatched for review" % len(misses))
    return "applied"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", help="slug; default is every vendor with a known feed")
    ap.add_argument("--file", help="a JSON list instead of the live feed")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--show", type=int, default=8, help="sample lines per change kind")
    ap.add_argument("--form", default="seed", help="form recorded on every row")
    ap.add_argument("--unit", default=None, help="unit recorded on every row")
    args = ap.parse_args()

    env = load_env()
    probe = json.loads(PROBE.read_text()) if PROBE.exists() else {}

    if args.vendor:
        slugs = [args.vendor]
    else:
        slugs = sorted(k for k, v in probe.items() if v.get("feed"))
        if not slugs:
            sys.exit("No vendor in feed_probe.json has a feed. Run probe_feeds.py first.")
        print("vendors with a public feed: %s" % ", ".join(slugs))

    plants = load_plants(env)
    idx = build_index(env, plants)
    print("index: %d plants · %d ambiguous common names · %d synonyms"
          % (len(plants), len(idx["ambiguous"]), len(idx["syn"])))

    results = {}
    for slug in slugs:
        got = supabase(env, "GET", "vendors?select=id,slug,name&slug=eq." + slug)
        if not got:
            print("\nno vendor with slug %r — skipped" % slug)
            results[slug] = "missing"
            continue
        vendor = got[0]

        if args.file:
            path = Path(args.file)
            results[slug] = refresh(env, vendor,
                                    lambda p=path: json.loads(p.read_text()),
                                    idx, args, "file %s" % path.name)
            continue

        p = probe.get(slug) or {}
        reader = READERS.get(p.get("kind"))
        if not p.get("feed") or not reader:
            print("\n%s — no known feed (%s). Pass --file with a supplied list."
                  % (slug, p.get("platform") or "platform unknown"))
            results[slug] = "no-feed"
            continue
        results[slug] = refresh(env, vendor,
                                lambda f=p["feed"], r=reader: r(f, args.max_pages),
                                idx, args, "%s %s" % (p["kind"], p["feed"]))

    print("\n" + "=" * 72)
    for k, v in results.items():
        print("  %-34s %s" % (k, v))
    if not args.apply:
        print("\nDry run. Read the diff above, then re-run with --apply.")


if __name__ == "__main__":
    main()
