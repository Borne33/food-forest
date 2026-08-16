#!/usr/bin/env python3
"""
Seed & Plant Shop database — S1 seeder.

Upserts importer/vendors/seed_orgs.json, seed_vendors.json and seed_sales.json
into Supabase (organizations / vendors / sales), on conflict `slug` so re-runs
update instead of duplicating. Geocodes vendor and sale addresses once via
Nominatim, cached under importer/cache/geo/.

Pure stdlib, Python 3.9. See SHOPS_PLAN.md §4 (Phase 1) and STAGE_GATES.md S1.

Usage:
    python3 vendors_seed.py --dry-run
    python3 vendors_seed.py
    python3 vendors_seed.py --no-geocode
    python3 vendors_seed.py --csv ~/Downloads/shops_review.csv
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "vendors"
GEO_CACHE = HERE / "cache" / "geo"
UA = "native-food-forest-planner/1.0 (https://borne33.github.io/food-forest/)"

# helper keys that are not columns
ORG_DROP = set()
VENDOR_DROP = {"org_slug", "venue_hint"}
SALE_DROP = {"vendor_slug", "org_slug"}

# ── NY sub-regions = the 10 Empire State Development / REDC regions ────────
# Source: https://esd.ny.gov/regions  (county rosters via the regional councils)
# Derived from `county` so a hand-typed subregion can never drift out of sync.
# NOTE: Tompkins (Ithaca) is SOUTHERN TIER under ESD, not Finger Lakes.
ESD_REGION = {
    "Western NY":     ["Allegany", "Cattaraugus", "Chautauqua", "Erie", "Niagara"],
    "Finger Lakes":   ["Genesee", "Livingston", "Monroe", "Ontario", "Orleans",
                       "Seneca", "Wayne", "Wyoming", "Yates"],
    "Southern Tier":  ["Broome", "Chemung", "Chenango", "Delaware", "Schuyler",
                       "Steuben", "Tioga", "Tompkins"],
    "Central NY":     ["Cayuga", "Cortland", "Madison", "Onondaga", "Oswego"],
    "Mohawk Valley":  ["Fulton", "Herkimer", "Montgomery", "Oneida", "Otsego", "Schoharie"],
    "North Country":  ["Clinton", "Essex", "Franklin", "Hamilton", "Jefferson",
                       "Lewis", "St. Lawrence"],
    "Capital Region": ["Albany", "Columbia", "Greene", "Rensselaer", "Saratoga",
                       "Schenectady", "Warren", "Washington"],
    "Mid-Hudson":     ["Dutchess", "Orange", "Putnam", "Rockland", "Sullivan",
                       "Ulster", "Westchester"],
    "New York City":  ["Bronx", "Kings", "New York", "Queens", "Richmond"],
    "Long Island":    ["Nassau", "Suffolk"],
}
COUNTY_TO_SUBREGION = {c: r for r, cs in ESD_REGION.items() for c in cs}


def derive_subregion(rows, label):
    """NY rows get their subregion from the county via the ESD roster."""
    for r in rows:
        if r.get("state") != "NY":
            continue
        county = r.get("county")
        if not county:
            if r.get("subregion"):
                print("   %s %s: no county — keeping hand-set subregion %r"
                      % (label, r["slug"], r["subregion"]))
            continue
        want = COUNTY_TO_SUBREGION.get(county)
        if not want:
            print("!! %s %s: county %r not in the ESD roster" % (label, r["slug"], county))
            continue
        if r.get("subregion") and r["subregion"] != want:
            print("   %s %s: subregion %r -> %r (%s County)"
                  % (label, r["slug"], r["subregion"], want, county))
        r["subregion"] = want


def load_env():
    env = {}
    envfile = HERE / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def supabase(env, method, path, body=None, extra_headers=None):
    base = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        sys.exit("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from importer/.env")
    url = base + "/rest/v1/" + path.lstrip("/")
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit("Supabase error %s on %s %s:\n%s"
                 % (e.code, method, path, e.read().decode("utf-8")))


def upsert(env, table, rows):
    """POST with merge-duplicates on slug; returns the written rows.

    PostgREST requires every object in a bulk POST to have identical keys
    ("All object keys must match"), so rows are grouped by key-set and sent as
    separate batches. Grouping rather than null-filling keeps column defaults
    (sells, needs_verification, ...) intact for rows that omit a field."""
    if not rows:
        return []
    groups = {}
    for r in rows:
        groups.setdefault(tuple(sorted(r.keys())), []).append(r)
    out = []
    for batch in groups.values():
        out += supabase(env, "POST", "%s?on_conflict=slug" % table, batch,
                        {"Prefer": "resolution=merge-duplicates,return=representation"}) or []
    return out


# ── geocoding ──────────────────────────────────────────────────────────────
def geocode(query):
    """Nominatim, cached forever. One request per second, honest User-Agent."""
    GEO_CACHE.mkdir(parents=True, exist_ok=True)
    key = "".join(c if c.isalnum() else "_" for c in query.lower())[:120]
    cached = GEO_CACHE / (key + ".json")
    if cached.exists():
        d = json.loads(cached.read_text())
        return (d.get("lat"), d.get("lon"))
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
           + urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — degrade gracefully, geocoding is optional
        print("   geocode failed (%s): %s" % (query, e))
        res = []
    time.sleep(1.1)
    out = {}
    if res:
        out = {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"])}
    cached.write_text(json.dumps(out))
    return (out.get("lat"), out.get("lon"))


def addr_query(r):
    bits = [r.get("street"), r.get("city"), r.get("state"), r.get("postal")]
    bits = [b for b in bits if b]
    if not r.get("city") and not r.get("postal"):
        return None          # too vague to geocode usefully
    return ", ".join(bits) + ", USA"


def add_latlon(rows, do_geocode):
    if not do_geocode:
        return
    for r in rows:
        if r.get("lat") is not None:
            continue
        q = addr_query(r)
        if not q:
            continue
        lat, lon = geocode(q)
        if lat is not None:
            r["lat"], r["lon"] = lat, lon


# ── csv export (the S1 review artifact) ────────────────────────────────────
VCOLS = ["slug", "name", "kind", "street", "city", "county", "state", "postal",
         "subregion", "region", "lat", "lon", "url", "phone", "email",
         "sells", "gives_free", "ships", "pickup_only", "membership_required",
         "forms", "order_window", "season_note", "hours", "address_note",
         "inventory_mode", "notes", "needs_verification"]
SCOLS = ["slug", "vendor_slug", "name", "kind", "starts_on", "ends_on",
         "starts_at", "ends_at", "order_opens_on", "order_closes_on", "pickup_on",
         "recurs", "venue_name", "street", "city", "county", "state",
         "url", "price_note", "notes", "source_url"]
OCOLS = ["slug", "name", "kind", "scope", "state", "county", "subregion",
         "url", "events_url", "mission", "needs_verification"]


def flat(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if v is None:
        return ""
    return v


def write_csv(path, orgs, vendors, sales):
    path = Path(path).expanduser()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SECTION: VENDORS"])
        w.writerow(VCOLS)
        for r in sorted(vendors, key=lambda x: (x.get("state", ""), x.get("subregion") or "", x["name"])):
            w.writerow([flat(r.get(c)) for c in VCOLS])
        w.writerow([])
        w.writerow(["SECTION: SALES"])
        w.writerow(SCOLS)
        for r in sales:
            w.writerow([flat(r.get(c)) for c in SCOLS])
        w.writerow([])
        w.writerow(["SECTION: ORGANIZATIONS"])
        w.writerow(OCOLS)
        for r in orgs:
            w.writerow([flat(r.get(c)) for c in OCOLS])
    print("Wrote %s" % path)


# ── main ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--csv", metavar="PATH", help="write a review CSV of everything seeded")
    args = ap.parse_args()

    orgs = json.loads((DATA / "seed_orgs.json").read_text())
    vendors = json.loads((DATA / "seed_vendors.json").read_text())
    sales = json.loads((DATA / "seed_sales.json").read_text())

    # vendors: fold venue_hint into address_note so nothing is lost
    for v in vendors:
        if v.get("venue_hint") and not v.get("address_note"):
            v["address_note"] = v["venue_hint"]

    print("Loaded %d organizations, %d vendors, %d sales" % (len(orgs), len(vendors), len(sales)))

    # sales carry no subregion column — they inherit their vendor's
    for rows, label in ((orgs, "org"), (vendors, "vendor")):
        derive_subregion(rows, label)

    bad_kind = [v["slug"] for v in vendors if v.get("kind") in ("plant_sale", "seed_swap")]
    if bad_kind:
        sys.exit("A sale is never a vendor — the host organization is. Offending rows: %s" % bad_kind)

    add_latlon(vendors, not args.no_geocode)
    add_latlon(sales, not args.no_geocode)
    got = sum(1 for v in vendors if v.get("lat") is not None)
    print("Geocoded %d/%d vendors" % (got, len(vendors)))

    if args.csv:
        write_csv(args.csv, orgs, vendors, sales)

    if args.dry_run:
        missing_org = {v.get("org_slug") for v in vendors if v.get("org_slug")} - {o["slug"] for o in orgs}
        missing_ven = {s["vendor_slug"] for s in sales} - {v["slug"] for v in vendors}
        if missing_org:
            print("!! vendors reference unknown org slugs: %s" % sorted(missing_org))
        if missing_ven:
            print("!! sales reference unknown vendor slugs: %s" % sorted(missing_ven))
        print("Dry run — nothing written.")
        return

    env = load_env()

    org_rows = [{k: v for k, v in o.items() if k not in ORG_DROP} for o in orgs]
    written = upsert(env, "organizations", org_rows)
    org_id = {r["slug"]: r["id"] for r in written}
    print("organizations: upserted %d" % len(written))

    ven_rows = []
    for v in vendors:
        row = {k: val for k, val in v.items() if k not in VENDOR_DROP}
        if v.get("org_slug"):
            if v["org_slug"] not in org_id:
                sys.exit("vendor %s references unknown org %s" % (v["slug"], v["org_slug"]))
            row["org_id"] = org_id[v["org_slug"]]
        ven_rows.append(row)
    written = upsert(env, "vendors", ven_rows)
    ven_id = {r["slug"]: r["id"] for r in written}
    print("vendors: upserted %d" % len(written))

    sale_rows = []
    for s in sales:
        row = {k: val for k, val in s.items() if k not in SALE_DROP}
        if s["vendor_slug"] not in ven_id:
            sys.exit("sale %s references unknown vendor %s" % (s["slug"], s["vendor_slug"]))
        row["vendor_id"] = ven_id[s["vendor_slug"]]
        if s.get("org_slug"):
            row["org_id"] = org_id.get(s["org_slug"])
        sale_rows.append(row)
    written = upsert(env, "sales", sale_rows)
    print("sales: upserted %d" % len(written))
    print("Done. Everything is needs_verification=true until a human clears it (STAGE_GATES.md S1).")


if __name__ == "__main__":
    main()
