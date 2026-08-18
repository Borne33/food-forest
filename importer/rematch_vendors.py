#!/usr/bin/env python3
"""Re-run the vendor matcher against the CURRENT plants table.

Nothing else re-checks a vendor listing once it has been filed as unmatched, so
every batch of new plants leaves stale misses behind. This replays the stored
catalogue files (importer/vendors/lists/*.json) plus the live Ernst feed through
the same strict D5 matcher, upserts anything that now resolves, and rebuilds
vendor_plants_unmatched from scratch so it never accumulates duplicates.

Usage:
  python3 rematch_vendors.py --dry-run
  python3 rematch_vendors.py
"""
import argparse, glob, json, os, sys
import vendor_inventory as vi

HERE = os.path.dirname(os.path.abspath(__file__))
LISTS = os.path.join(HERE, "vendors", "lists")

# list-file basename -> vendor slug (they match today; keep the map explicit)
SLUG = {
    "amandas-native-garden": "amandas-native-garden",
    "hgcny-2026-sale":       "wild-ones-hgcny-vendor",
    "mill-street-gardens":   "mill-street-gardens",
    "monroe-county-swcd":    "monroe-county-swcd",
    "prairie-moon-nursery":  "prairie-moon-nursery",
    "white-oak-nursery":     "white-oak-nursery",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = vi.load_env()
    plants = vi.load_plants(env)
    idx = vi.build_index(env, plants)
    print("index: %d plants · %d synonyms · %d ambiguous common names\n"
          % (len(plants), len(idx["syn"]), len(idx["ambiguous"])))

    vendors = {v["slug"]: v for v in
               (vi.supabase(env, "GET", "vendors?select=id,slug,name&limit=500") or [])}
    # PostgREST caps a response at 1000 rows regardless of &limit — page, or
    # every listing past the first 1000 looks "new" on each run.
    existing, _off = set(), 0
    while True:
        page = vi.supabase(env, "GET",
            "vendor_plants?select=vendor_id,plant_id&order=id&limit=1000&offset=%d" % _off) or []
        for r in page:
            existing.add((r["vendor_id"], r["plant_id"]))
        if len(page) < 1000:
            break
        _off += 1000
    print("already linked: %d vendor-plant pairs" % len(existing))

    grand_new, grand_miss = 0, 0
    for path in sorted(glob.glob(os.path.join(LISTS, "*.json"))):
        base = os.path.basename(path)[:-5]
        slug = SLUG.get(base, base)
        v = vendors.get(slug)
        if not v:
            print("!! no vendor row for slug %r (from %s)" % (slug, base))
            continue
        items = json.load(open(path))
        rows, misses, newly = [], [], []
        for it in items:
            cult = vi.CULTIVAR.search(it.get("cultivar_src") or it.get("raw_sci")
                                      or it.get("raw_name") or "")
            pid, reason = vi.match(it.get("raw_sci"), it.get("raw_name"), idx, it.get("code"))
            if not pid:
                misses.append({"vendor_id": v["id"], "raw_name": it.get("raw_name"),
                               "raw_sci": it.get("raw_sci"), "form": it.get("form")})
                continue
            if (v["id"], pid) not in existing:
                newly.append((it.get("raw_sci") or it.get("raw_name"), pid, reason))
            rows.append({
                "vendor_id": v["id"], "plant_id": pid,
                "raw_name": it.get("raw_name"), "raw_sci": it.get("raw_sci"),
                "is_cultivar": bool(cult), "cultivar_name": cult.group(1) if cult else "",
                "form": it.get("form"), "size": it.get("size") or "",
                "price_cents": it.get("price_cents"), "unit": it.get("unit"),
                "stock": it.get("stock") or "unknown",
                "source": it.get("source") or "manual",
                "confidence": "high" if reason in ("sci", "sci_base", "synonym", "sku_code") else "medium",
                "url": it.get("url"),
            })
        seen, dedup = set(), []
        for r in rows:
            k = (r["vendor_id"], r["plant_id"], r["form"], r["cultivar_name"], r["size"])
            if k not in seen:
                seen.add(k); dedup.append(r)
        grand_new += len(newly); grand_miss += len(misses)
        print("%-24s %4d items → %3d matched (%d new), %3d unmatched"
              % (v["name"][:24], len(items), len(dedup), len(newly), len(misses)))
        for raw, pid, reason in newly:
            print("      + %-44s -> plant %s (%s)" % ((raw or "")[:44], pid, reason))
        if args.dry_run:
            continue
        if dedup:
            vi.supabase(env, "POST",
                        "vendor_plants?on_conflict=vendor_id,plant_id,form,cultivar_name,size",
                        dedup, {"Prefer": "resolution=merge-duplicates"})
        # rebuild this vendor's miss list rather than appending to it again
        vi.supabase(env, "DELETE",
                    "vendor_plants_unmatched?vendor_id=eq.%d&resolved_plant_id=is.null" % v["id"],
                    None, {"Prefer": "return=minimal"})
        if misses:
            vi.supabase(env, "POST", "vendor_plants_unmatched", misses,
                        {"Prefer": "return=minimal"})

    print("\n%s%d new vendor↔plant links, %d listings still unmatched"
          % ("[dry run] " if args.dry_run else "", grand_new, grand_miss))


if __name__ == "__main__":
    main()
