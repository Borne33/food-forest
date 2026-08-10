#!/usr/bin/env python3
"""Upsert the grant catalog into the Supabase `grants` table (the Grant Finder
reads it live behind sign-in). Source of truth: importer/grants/grants_catalog.json
(the same shape as the finder's inlined window.__GRANTS__.grants records).

Each row stores the whole record as `data` (jsonb) plus a few extracted columns
(status, deadline, last_verified, needs_verification) for indexing/queries.

  python3 grant_import.py            # upsert all records
  python3 grant_import.py --dry-run  # show what would upsert
"""
import sys, json, argparse, os
sys.path.insert(0, ".")
import foodforest_import as ff

CATALOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grants", "grants_catalog.json")

def row_of(g):
    dl = g.get("deadline")
    return {
        "id": g["id"], "data": g,
        "status": g.get("status"),
        "deadline": dl if dl else None,
        "last_verified": g.get("last_verified") or None,
        "needs_verification": bool(g.get("needs_verification")),
        "updated_at": "now()",
    }

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cat = json.load(open(CATALOG))
    grants = cat["grants"]
    rows = [row_of(g) for g in grants]
    # updated_at can't be the literal "now()" through PostgREST JSON; drop it and let the default/trigger handle it
    for r in rows: r.pop("updated_at", None)
    print("%d grant records from %s (generated_at %s)" % (len(rows), CATALOG, cat.get("generated_at")))
    if a.dry_run:
        for r in rows: print("  ·", r["id"], "|", r["status"], "|", r["data"]["title"][:60])
        return
    env = ff.load_env()
    res = ff.supabase_request(env, "POST", "grants?on_conflict=id", body=rows,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"})
    print("upserted %d rows into grants" % len(res or []))

if __name__ == "__main__":
    main()
