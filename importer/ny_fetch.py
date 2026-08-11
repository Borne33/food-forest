#!/usr/bin/env python3
"""Refresh the NY-state side of importer/grants/grants_catalog.json from the
**NYS Funding Finder** — the public ArcGIS feature layer behind DEC's "Funding
Finder Tool" (environmentalbondact.ny.gov). No key, no session, one GET.

  https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/
      NYS_Funding_Finder/FeatureServer/0/query?where=1=1&outFields=*&f=json

It is NY-curated (DEC, NYSERDA, EFC, Ag & Markets, ESD, plus the federal programs
that actually apply in NY), which is why it is worth a second importer alongside
grant_fetch.py — Grants.gov carries none of it.

Same shape as grant_fetch.py: one budget per run (default 25 records), split
between refreshing records already sourced from here and capturing new ones.

  python3 ny_fetch.py                  # refresh + capture, up to 25 records
  python3 ny_fetch.py --dry-run        # show the plan, write nothing
  python3 ny_fetch.py --limit 40
  python3 ny_fetch.py --refresh-only / --new-only
  python3 ny_fetch.py --all-regions    # keep Long Island / Hudson / Champlain too

Then push to Supabase with:  python3 grant_import.py
"""
import os, re, sys, json, time, difflib, argparse, urllib.request, urllib.parse
from datetime import datetime, date, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grant_fetch import CATALOG, detag, slug, num  # shared helpers / same catalog

LAYER = ("https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/"
         "NYS_Funding_Finder/FeatureServer/0")
UA = "food-forest-ny-fetch/1.0 (+https://borne33.github.io/food-forest/)"
# The layer uses a year-2100 close date as its "rolling / continuous" sentinel.
ROLLING_YEAR = 2099

# ---------- NY vocab -> catalog vocab (catalog side mirrors grants.html) ----------
APPLICANTS = {
    "local government entity": ["town", "county"],
    "non-profit 501c3 organizations": ["nonprofit"],
    "state government entity": ["state_agency"],
    "academic institutions": ["nonprofit"],
    "private entities": ["for_profit"],
    "agriculture producer": ["for_profit", "individual"],
    "landowners": ["individual"],
    "citizen of the united states": ["individual"],
    "any organization/partnership": ["town", "county", "state_agency", "nonprofit",
                                     "individual", "for_profit"],
    "public school district": ["town"],
    "public school districts serving disadvantaged communities": ["town"],
    "high needs public schools": ["town"],
    "soil and water conservation districts": ["county"],
    "water authority": ["town"],
    "regional water pollution control agencies and entities": ["town"],
    "land trusts": ["nonprofit"],
    "regional planning organizations": ["nonprofit"],
    "interstate organizations": ["nonprofit"],
    "public benefit corporation": ["state_agency"],
    "state coastal zone management agencies": ["state_agency"],
    "public entities that provide pupil transportation services": ["town"],
    "third-party bus operators": ["for_profit"],
    # Deliberately unmapped (surfaced in applicant_notes instead):
    # "indian nations", "other", "suffolk county residents", "nassau county residents"
}

PROJECTS = {
    # land
    "habitat restoration": "habitat_restoration", "ecological restoration": "habitat_restoration",
    "restoration": "habitat_restoration", "coastal restoration": "habitat_restoration",
    "buffer restoration": "habitat_restoration", "riparian buffers": "habitat_restoration",
    "wetlands": "habitat_restoration", "wildlife": "habitat_restoration",
    "habitat connectivity": "habitat_restoration", "habitat loss": "habitat_restoration",
    "aquatic connectivity": "habitat_restoration", "fish passage": "habitat_restoration",
    "dam removal": "habitat_restoration", "invasive species": "habitat_restoration",
    "conservation": "habitat_restoration", "conservation easements": "habitat_restoration",
    "land acquisition": "habitat_restoration", "preservation": "habitat_restoration",
    "land stewardship": "habitat_restoration", "forestry": "habitat_restoration",
    "trees": "habitat_restoration", "reforestation": "habitat_restoration",
    "plants": "native_plants",
    "agriculture": "community_gardens", "crops": "community_gardens", "soils": "community_gardens",
    # water
    "green infrastructure": "rain_gardens_bioretention", "stormwater": "rain_gardens_bioretention",
    "runoff reduction": "rain_gardens_bioretention", "nonpoint source": "rain_gardens_bioretention",
    "nature-based solutions": "rain_gardens_bioretention",
    # waste
    "food diversion or composting": "organic_composting",
    "waste reduction": "zero_waste", "hazardous waste": "zero_waste",
    # energy & climate
    "carbon sequestration": "carbon_offsetting", "emissions reductions": "carbon_offsetting",
    "decarbonization": "carbon_offsetting", "climate change": "carbon_offsetting",
    "renewable energy": "solar_renewables",
    "energy efficiency": "energy_efficiency", "retrofitting": "energy_efficiency",
    "ev charging infrastructure": "fleet_electrification", "electric vehicle": "fleet_electrification",
    # community & operational
    "transportation": "active_transportation",
    "education": "community_education", "education and outreach": "community_education",
    "outreach": "community_education", "training": "community_education",
    "capacity building": "community_education", "environmental justice": "community_education",
    "grant writing": "community_education", "research": "community_education",
    "sustainability": "green_building_design",
}
# Explicit wording that earns the food_forest tag; the layer has no equivalent term.
FOOD_FOREST = ("food forest", "agroforestry", "orchard", "silvopasture", "perennial",
               "community garden", "edible", "urban agriculture", "farmland protection")

# This catalog's scope is Finger Lakes + Western NY. A record limited to another
# part of the state is dropped unless --all-regions.
IN_SCOPE = ("finger lakes", "western ny", "great lakes basin", "new york inland waterways")
OUT_SCOPE = ("long island", "suffolk", "nassau", "new york city", "hudson river estuary",
             "lake champlain", "chesapeake", "long island sound", "new york coastal areas")


def fetch_rows():
    p = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "f": "json",
                                "resultRecordCount": 2000})
    req = urllib.request.Request(LAYER + "/query?" + p, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if "error" in d:
        raise RuntimeError(d["error"])
    return [f["attributes"] for f in d.get("features", [])]


def parts(s):
    return [t.strip() for t in re.split(r",", s or "") if t.strip()]


def epoch_date(ms):
    """Layer stores midnight Eastern as epoch ms; we only trust the date part."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def et_offset(d):
    """Rough US Eastern offset for a date — good enough for a day-precision deadline."""
    return "-04:00" if 3 <= d.month <= 10 else "-05:00"


def region_of(a):
    if (a.get("Statewide") or "").strip().lower() == "yes":
        return ["statewide_ny"], "Statewide."
    cov = (a.get("Regional_Coverage") or a.get("RegionalFilters") or "")
    low = cov.lower()
    regions = []
    if "finger lakes" in low:
        regions.append("finger_lakes")
    if "western ny" in low:
        regions.append("western_ny")
    if not regions and any(k in low for k in IN_SCOPE):
        regions = ["finger_lakes", "western_ny"]  # Great Lakes basin covers both
    return regions, cov.strip()


def in_scope(a):
    if (a.get("Statewide") or "").strip().lower() == "yes":
        return True
    low = (a.get("Regional_Coverage") or a.get("RegionalFilters") or "").lower()
    if any(k in low for k in IN_SCOPE):
        return True
    return not any(k in low for k in OUT_SCOPE) and not low.strip()


def level_of(src):
    s = (src or "").lower()
    if s.startswith("nys") or "new york state" in s or s.startswith("ny "):
        return "state"
    if any(k in s for k in ("united states", "u.s. ", "usda", "environmental protection agency",
                            "noaa", "national oceanic", "federal")):
        return "federal"
    return "private"


def to_record(a, prev=None):
    title = (a.get("Funding_Program") or "").strip()
    funder = re.sub(r"\s+", " ", (a.get("Funding_Source") or "").strip())
    ptypes, unmapped = [], []
    for t in parts(a.get("Project_Type")):
        v = PROJECTS.get(t.lower())
        if v and v not in ptypes:
            ptypes.append(v)
        elif not v:
            unmapped.append(t)
    if any(k in title.lower() for k in FOOD_FOREST) and "food_forest" not in ptypes:
        ptypes.insert(0, "food_forest")
    if not ptypes:
        ptypes = ["other"]

    elig, notes = [], {}
    raw_app = parts(a.get("Eligible_Applicants"))
    for t in raw_app:
        for v in APPLICANTS.get(t.lower(), []):
            if v not in elig:
                elig.append(v)
    for v in ("town", "county", "state_agency", "nonprofit", "individual", "for_profit"):
        if v not in elig:
            notes[v] = "Not listed in the NYS Funding Finder eligibility for this program."
    extra = [t for t in raw_app if t.lower() not in APPLICANTS]
    if extra:
        notes["_other"] = "Also eligible per the source: " + ", ".join(extra)

    close, open_ = epoch_date(a.get("CloseDate2")), epoch_date(a.get("OpenDate2"))
    rolling = bool(close and close.year >= ROLLING_YEAR)
    status = (a.get("Status") or "").strip().lower()
    if status == "open":
        status = "rolling" if rolling else "open"
        if close and not rolling and close < date.today():
            status = "closed"
    else:
        status = "closed"
    deadline = None
    if close and not rolling:
        deadline = "%sT23:59:00%s" % (close.isoformat(), et_offset(close))

    regions, geo_note = region_of(a)
    reqs = ["Confirm the exact closing time in the RFP — the NYS Funding Finder publishes a "
            "closing date but not a time of day"]
    if a.get("Project_Phase"):
        reqs.append("Eligible project phases: " + a["Project_Phase"])
    if level_of(funder) == "state":
        reqs.append("NYS grants generally require SFS registration, and prequalification for "
                    "not-for-profits — check the RFP")

    tags = ["nys-funding-finder", "bond-act-tool"]
    if rolling:
        tags.append("rolling")
    if unmapped:
        tags += ["src:" + slug(t) for t in unmapped[:6]]

    oid = a.get("ObjectId")
    rec = {
        "id": "nysff-" + slug(title),
        "title": title,
        "funder": funder,
        "funder_level": level_of(funder),
        "program_url": (a.get("Links") or "").strip() or None,
        "source_url": "https://environmentalbondact.ny.gov/pages/funding-opportunities",
        "summary": detag(
            "%s, offered by %s. Source project types: %s. Eligible applicants per the source: %s.%s"
            % (title, funder or "the funding agency",
               a.get("Project_Type") or "not stated",
               a.get("Eligible_Applicants") or "not stated",
               (" Regional coverage: %s." % geo_note) if geo_note else ""), 900),
        "eligible_applicants": elig,
        "applicant_notes": notes,
        "project_types": ptypes,
        "geography": {"regions": regions, "counties": [],
                      "notes": geo_note or "Regional coverage not stated in the source."},
        "award_min": None, "award_max": None, "cost_share_pct": None, "expected_awards": None,
        "status": status,
        "opens_on": open_.isoformat() if open_ and open_.year < ROLLING_YEAR else None,
        "deadline": deadline,
        "award_notice_est": None, "funds_available_est": None, "disbursement": None,
        "requirements": reqs,
        "tags": tags,
        "last_verified": date.today().isoformat(),
        "verified_by": "nys_funding_finder",
        "needs_verification": True,
        "verification_note": (
            "Imported from the NYS Funding Finder (ArcGIS layer behind DEC's Funding Finder Tool) "
            "on %s. The source publishes no award floor/ceiling, cost share, or number of awards — "
            "those stay null rather than being estimated. Deadline is the source's closing DATE at "
            "23:59 ET; the real cut-off time is in the RFP. Project-type tags are mapped from the "
            "source's own taxonomy." % date.today().isoformat()),
        "source_ref": {"api": "nys_funding_finder", "object_id": oid, "layer": LAYER},
        "raw_hash": None,
    }
    import hashlib
    rec["raw_hash"] = hashlib.sha256(json.dumps(
        {k: rec[k] for k in ("title", "funder", "status", "deadline", "project_types",
                             "eligible_applicants", "program_url")},
        sort_keys=True).encode()).hexdigest()[:16]
    if prev:
        for k in ("award_min", "award_max", "cost_share_pct", "expected_awards",
                  "funds_available_est", "disbursement"):
            if prev.get(k) is not None:      # a human filled a figure the source lacks
                rec[k] = prev[k]
        if prev.get("needs_verification") is False and prev.get("raw_hash") == rec["raw_hash"]:
            rec["needs_verification"] = False
            rec["verified_by"] = prev.get("verified_by", rec["verified_by"])
    return rec


STOP = {"the", "and", "for", "with", "program", "programs", "grant", "grants", "fund", "funding",
        "project", "projects", "round", "initiative", "new", "york", "nys", "state"}


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()


def keywords(s):
    """Significant words, crudely de-pluralised."""
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w
            for w in norm(s) if len(w) > 3 and w not in STOP}


def dup_of(rec, grants):
    """Match against records already in the catalog — seeded ones word things differently
    ('Urban and Community Forestry Grant Program, Round 17' vs 'Urban and Community
    Development Forestry Grants' are the same DEC round)."""
    a, ka = " ".join(norm(rec["title"])), keywords(rec["title"])
    dl = (rec.get("deadline") or "")[:10]
    for g in grants:
        b, kb = " ".join(norm(g.get("title"))), keywords(g.get("title"))
        if not (a and b):
            continue
        if difflib.SequenceMatcher(None, a, b).ratio() > 0.80:
            return g["id"], "near-identical title"
        if (a in b or b in a) and min(len(a), len(b)) > 18:
            return g["id"], "title contained in the other"
        if ka and kb:
            jac = len(ka & kb) / float(len(ka | kb))
            if jac >= 0.6:
                return g["id"], "shared wording (%.0f%%)" % (jac * 100)
            # same closing date + real topical overlap = the same round, worded differently
            if dl and dl == (g.get("deadline") or "")[:10] and jac >= 0.3:
                return g["id"], "same deadline %s + shared wording" % dl
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--refresh-only", action="store_true")
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--all-regions", action="store_true")
    ap.add_argument("--include-closed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CATALOG))
    grants = cat["grants"]
    before = json.dumps(grants, sort_keys=True)
    print("catalog: %d records (generated_at %s)" % (len(grants), cat.get("generated_at")))

    rows = fetch_rows()
    print("NYS Funding Finder: %d rows" % len(rows))
    rows = [r for r in rows if (r.get("ShowHide") or "Show").strip().lower() != "hide"]
    if not a.include_closed:
        rows = [r for r in rows if (r.get("Status") or "").strip().lower() == "open"]
    if not a.all_regions:
        rows = [r for r in rows if in_scope(r)]
    print("  after ShowHide / status / region filters: %d" % len(rows))

    by_oid = {g["id"]: g for g in grants
              if (g.get("source_ref") or {}).get("api") == "nys_funding_finder"}
    oid_map = {(g.get("source_ref") or {}).get("object_id"): g for g in by_oid.values()}

    r_budget = 0 if a.new_only else (a.limit if a.refresh_only else min(len(oid_map), a.limit // 2))
    c_budget = 0 if a.refresh_only else a.limit - r_budget
    print("plan: refresh up to %d (%d held), capture up to %d" % (r_budget, len(oid_map), c_budget))

    # ---- refresh ----
    changed = []
    stale = sorted(oid_map.items(), key=lambda kv: kv[1].get("last_verified") or "")
    for oid, g in stale[:r_budget]:
        src = next((r for r in rows if r.get("ObjectId") == oid), None)
        if src is None:
            if g.get("status") != "closed":
                g["status"] = "closed"
                g["last_verified"] = date.today().isoformat()
                changed.append((g["id"], "gone from the source → closed"))
            continue
        new = to_record(src, prev=g)
        if new["raw_hash"] == g.get("raw_hash"):
            g["last_verified"] = date.today().isoformat()
            changed.append((g["id"], "unchanged, re-verified"))
        else:
            was = g.get("status")
            g.clear(); g.update(new)
            changed.append((g["id"], "updated (%s → %s)" % (was, new["status"])))

    # ---- capture ----
    added, skipped = [], {}
    for src in rows:
        if len(added) >= c_budget:
            break
        if src.get("ObjectId") in oid_map:
            continue
        rec = to_record(src)
        if rec["project_types"] == ["other"]:
            skipped["no mapped project type"] = skipped.get("no mapped project type", 0) + 1
            continue
        if not rec["eligible_applicants"]:
            skipped["no eligible applicant we track"] = skipped.get("no eligible applicant we track", 0) + 1
            continue
        d, why = dup_of(rec, grants)
        if d:
            skipped["already in catalog"] = skipped.get("already in catalog", 0) + 1
            print("  ~ skip dup: %s → %s (%s)" % (rec["title"][:46], d, why))
            continue
        if any(g["id"] == rec["id"] for g in grants):
            continue
        grants.append(rec)
        oid_map[src.get("ObjectId")] = rec
        added.append((rec["id"], "%-7s | %s | %s" % (
            rec["status"], (rec["deadline"] or "rolling")[:10], rec["title"][:55])))

    print("\nrefreshed %d:" % len(changed))
    for i, why in changed:
        print("  ·", i, "—", why)
    print("captured %d new:" % len(added))
    for i, why in added:
        print("  +", i, "—", why)
    if skipped:
        print("  skipped:", ", ".join("%s×%d" % (k, v) for k, v in skipped.items()))

    if a.dry_run:
        print("\n--dry-run: catalog not written")
        return
    if json.dumps(grants, sort_keys=True) == before:
        print("\nno changes; catalog left as-is")
        return
    cat["generated_at"] = date.today().isoformat()
    tmp = CATALOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cat, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, CATALOG)
    print("\nwrote %s — %d records total" % (CATALOG, len(grants)))
    print("next: python3 grant_import.py")


if __name__ == "__main__":
    main()
