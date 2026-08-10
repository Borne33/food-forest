#!/usr/bin/env python3
"""Refresh importer/grants/grants_catalog.json from the Grants.gov public API.

Each run does two things, inside one budget (default 25 records):
  1. REFRESH — re-fetch records already sourced from Grants.gov (oldest
     last_verified first) and update status/deadline/award figures. Records that
     were hand-seeded (verified_by="seed") are not re-fetched, but their status
     is flipped to "closed" when their deadline has passed.
  2. CAPTURE — search Grants.gov for opportunities matching this site's topics
     (forestry, native plants, habitat, urban ag, stormwater, composting, ...),
     keep the relevant ones, and add them as new records.

Grants.gov API (no key required):
  POST https://api.grants.gov/v1/api/search2          {keyword, oppStatuses, rows}
  POST https://api.grants.gov/v1/api/fetchOpportunity {opportunityId}

  python3 grant_fetch.py                  # refresh + capture, up to 25 records
  python3 grant_fetch.py --limit 40
  python3 grant_fetch.py --dry-run        # show the plan, write nothing
  python3 grant_fetch.py --refresh-only   # only re-verify what is already in
  python3 grant_fetch.py --new-only       # only look for new opportunities
  python3 grant_fetch.py --stale-days 30  # what counts as needing a refresh

Then push to Supabase with:  python3 grant_import.py
"""
import sys, os, re, json, time, html, hashlib, argparse, urllib.request, urllib.error
from datetime import datetime, date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "grants", "grants_catalog.json")
API = "https://api.grants.gov/v1/api/"
UA = "food-forest-grant-fetch/1.0 (+https://borne33.github.io/food-forest/)"

# ---------- taxonomy (mirrors grants.html — keep in sync) ----------
APPLICANT_TYPES = ["town", "county", "state_agency", "nonprofit", "individual", "for_profit"]

# Grants.gov applicantTypes id -> our vocab. Ids are stable in their API.
APPLICANT_MAP = {
    "00": ["state_agency"],                  # State governments
    "01": ["county"],                        # County governments
    "02": ["town"],                          # City or township governments
    "04": ["town"],                          # Special district governments
    "05": ["town"],                          # Independent school districts
    "06": ["nonprofit"],                     # Public/state institutions of higher ed
    "07": [],                                # Federally recognized tribal governments
    "08": ["nonprofit"],                     # Public housing authorities
    "11": ["nonprofit"],                     # Native American tribal organizations
    "12": ["nonprofit"],                     # Nonprofits w/ 501(c)(3)
    "13": ["nonprofit"],                     # Nonprofits w/o 501(c)(3)
    "20": ["individual"],                    # Private institutions of higher ed
    "21": ["individual"],                    # Individuals
    "22": ["for_profit"],                    # For-profit orgs other than small business
    "23": ["for_profit"],                    # Small businesses
    "25": [],                                # Others (see text field)
    "99": APPLICANT_TYPES,                   # Unrestricted
}

# project_type -> phrases that imply it. Order matters only for readability.
PROJECT_RULES = {
    "food_forest": ["food forest", "agroforestry", "silvopasture", "orchard", "fruit tree",
                    "perennial crop", "perennial food", "edible landscape"],
    "community_gardens": ["community garden", "urban agriculture", "urban farm", "school garden",
                          "market garden", "community farm", "local food system", "food security",
                          "farmers market"],
    "native_plants": ["native plant", "native seed", "pollinator", "milkweed", "monarch",
                      "wildflower", "seed collection", "native species"],
    "habitat_restoration": ["habitat", "urban forest", "community forest", "tree planting",
                            "reforestation", "afforestation", "riparian", "wetland restoration",
                            "ecosystem restoration", "invasive species", "land conservation",
                            "forest health", "forest stewardship", "watershed restoration",
                            "urban tree", "tree canopy"],
    "rain_gardens_bioretention": ["green infrastructure", "bioretention", "rain garden",
                                  "stormwater", "green stormwater"],
    "rainwater_harvesting": ["rainwater", "rainwater harvest", "cistern", "water reuse"],
    "water_fixture_retrofits": ["water efficiency", "fixture retrofit", "water conservation"],
    "organic_composting": ["compost", "food waste", "organic waste", "food scrap", "anaerobic digest"],
    "zero_waste": ["zero waste", "waste reduction", "waste diversion", "recycling"],
    "carbon_offsetting": ["carbon sequestration", "carbon storage", "greenhouse gas reduction",
                          "climate mitigation", "climate resilience"],
    "solar_renewables": ["solar", "renewable energy", "photovoltaic"],
    "energy_efficiency": ["energy efficiency", "weatherization", "building retrofit"],
    "green_building_design": ["green building", "sustainable design"],
    "active_transportation": ["bicycle", "pedestrian", "trail", "active transportation"],
    "community_education": ["environmental education", "outreach and education", "technical assistance",
                            "environmental justice", "workforce development", "capacity building",
                            "community engagement", "public outreach"],
}
# Relevance scoring. A candidate needs SCORE_MIN points to be captured; a phrase
# counts once. STRONG phrases are what this site is actually about, WEAK ones are
# common to any natural-resources notice and only support a strong hit.
STRONG = ("food forest", "agroforestry", "silvopasture", "orchard", "fruit tree", "edible landscape",
          "perennial crop", "community garden", "urban agriculture", "urban farm", "school garden",
          "local food system", "food security", "native plant", "native seed", "pollinator",
          "milkweed", "monarch", "urban forest", "community forest", "urban tree", "tree canopy",
          "tree planting", "reforestation", "afforestation", "forest stewardship", "forest health",
          "rain garden", "green infrastructure", "green stormwater", "rainwater harvest",
          "compost", "food waste", "food scrap", "organic waste", "seed collection",
          "land conservation", "conservation easement", "working forest")
WEAK = ("habitat", "restoration", "riparian", "wetland", "stormwater", "watershed", "invasive species",
        "native species", "environmental education", "environmental justice", "climate resilience",
        "carbon sequestration", "water conservation", "waste reduction", "recycling", "trail")
SCORE_MIN = 3
W_STRONG, W_WEAK = 3, 1
# Cheap title gate before spending a detail fetch — deliberately generous.
PRESCREEN = ("forest", "tree", "plant", "garden", "habitat", "conserv", "restor", "water", "soil",
             "agricultur", "farm", "food", "compost", "waste", "recycl", "pollinat", "native",
             "land", "nature", "environment", "climat", "green", "wetland", "watershed", "seed",
             "park", "urban", "communit", "steward", "nurser", "canopy", "carbon", "botan")

# Off-topic funders for a municipal / land-steward audience in New York.
AGENCY_BLOCK = ("HHS", "DOD", "USDOD", "ED", "DOJ", "DOS", "VA", "NASA", "SSA", "DHS",
                "NRC", "NSF", "ONDCP", "IAF", "PAMS", "DOEPAMS")
# Sub-agencies whose programs are western public land / tribal-trust only.
AGENCY_BLOCK_SUB = ("BLM", "BOR", "USBR", "BIA", "RECLAMATION")
# Phrases that mean "biomedical / lab research", not a fundable community project.
NEGATIVE = ("clinical", "biomedical", "cancer", "vaccine", "epidemiolog", "occupational safety",
            "drug abuse", "mental health", "nursing", "fellowship program for scientists")
# Programs bound to a region or resource that Western/Finger Lakes NY is not part of.
GEO_BLOCK = ("southwest border", "gulf coast", "gulf of mexico", "restore act", "alaska", "hawaii",
             "pacific island", "puerto rico", "u.s. virgin islands", "caribbean", "coral reef",
             "everglades", "chesapeake bay", "colorado river", "columbia river", "sagebrush",
             "rangeland", "abandoned mine", "battlefield", "feral swine", "fisheries",
             "aquatic invasive", "marine", "coastal zone", "puget sound", "delaware river basin")
# Many "federal" notices are actually scoped to named states or a single basin. If
# the opening text names two or more states and New York is not one of them — and it
# carries no nationwide marker — it is not an opportunity for this site's audience.
OTHER_STATES = ("alabama", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
                "florida", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
                "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
                "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
                "new mexico", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
                "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee",
                "texas", "utah", "vermont", "virginia", "west virginia", "wisconsin", "wyoming")
NATIONWIDE = ("nationwide", "all states", "all 50", "50 states", "any state", "each state",
              "states and territories", "throughout the united states", "across the united states",
              "national in scope")

# Grants.gov funding categories worth sweeping in full: Agriculture, Community
# Development, Environment, Food & Nutrition, Natural Resources, Regional Development.
CATEGORIES = "AG|CD|ENV|FN|NR|RD"
# Keyword sweeps on top of the category sweep, for notices filed elsewhere.
QUERIES = [
    "urban forestry", "community forest", "tree planting", "agroforestry",
    "native plants pollinator", "habitat restoration", "urban agriculture",
    "community garden", "green infrastructure stormwater", "composting food waste",
    "watershed protection", "conservation innovation", "local food", "environmental education",
]
CACHE = os.path.join(HERE, "cache", "grantsgov")

# ---------- small helpers ----------
def api(path, body, tries=3):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.load(r)
            if d.get("errorcode") not in (0, None):
                raise RuntimeError("%s: %s" % (path, d.get("msg")))
            return d["data"]
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))

def fetch_opp(oid, max_age_h=24):
    """fetchOpportunity with an on-disk cache, so re-runs don't re-hit the API."""
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, "%s.json" % oid)
    if os.path.exists(fp) and (time.time() - os.path.getmtime(fp)) < max_age_h * 3600:
        try:
            return json.load(open(fp))
        except ValueError:
            pass
    d = api("fetchOpportunity", {"opportunityId": int(oid)})
    with open(fp, "w") as f:
        json.dump(d, f)
    time.sleep(0.35)
    return d

def search_all(params, cap=400):
    """Page search2 until cap or exhaustion; returns [{id,title}, ...]."""
    out, start = [], 0
    while start < cap:
        d = api("search2", dict(params, rows=100, startRecordNum=start))
        hits = d.get("oppHits") or []
        out += hits
        total = d.get("hitCount") or 0
        start += len(hits)
        if not hits or start >= total:
            break
        time.sleep(0.3)
    return out

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

def detag(s, limit=800):
    if not s:
        return ""
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = WS_RE.sub(" ", s).strip()
    if len(s) > limit:
        cut = s[:limit].rsplit(". ", 1)[0]
        s = (cut + ".") if len(cut) > limit * 0.5 else s[:limit].rstrip() + "…"
    return s

TZ = {"EDT": "-04:00", "EST": "-05:00", "CDT": "-05:00", "CST": "-06:00",
      "MDT": "-06:00", "MST": "-07:00", "PDT": "-07:00", "PST": "-08:00", "UTC": "+00:00"}

def parse_dt(s):
    """'Sep 11, 2026 12:00:00 AM EDT' -> ('2026-09-11', '2026-09-11T00:00:00-04:00')."""
    if not s:
        return None, None
    s = s.strip()
    off = "-05:00"
    for k, v in TZ.items():
        if s.endswith(" " + k):
            off, s = v, s[: -(len(k) + 1)].strip()
            break
    for fmt in ("%b %d, %Y %I:%M:%S %p", "%b %d, %Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat(), dt.strftime("%Y-%m-%dT%H:%M:%S") + off
        except ValueError:
            pass
    return None, None

def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:60]

def num(v):
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None

def classify(text):
    t = " " + text.lower() + " "
    hits = []
    for pt, phrases in PROJECT_RULES.items():
        if any(p in t for p in phrases):
            hits.append(pt)
    return hits

# ---------- mapping a Grants.gov opportunity to a catalog record ----------
def to_record(opp, prev=None):
    oid = str(opp.get("id"))
    onum = opp.get("opportunityNumber") or oid
    body = opp.get("synopsis") or opp.get("forecast") or {}
    is_forecast = not opp.get("synopsis")

    title = html.unescape(opp.get("opportunityTitle") or "").strip()
    desc = detag(body.get("synopsisDesc") or body.get("forecastDesc"))
    types = classify(title + " " + desc)
    if not types:
        types = ["other"]

    ag = opp.get("agencyDetails") or {}
    top = opp.get("topAgencyDetails") or {}
    funder = (top.get("agencyName") or ag.get("agencyName") or opp.get("agency") or "").strip()
    if ag.get("agencyName") and top.get("agencyName") and ag["agencyName"] != top["agencyName"]:
        funder = "%s — %s" % (top["agencyName"], ag["agencyName"])

    elig, seen = [], set()
    for a in body.get("applicantTypes") or []:
        for v in APPLICANT_MAP.get(str(a.get("id")), []):
            if v not in seen:
                seen.add(v); elig.append(v)
    notes = {}
    for a in APPLICANT_TYPES:
        if a not in seen:
            notes[a] = "Not listed in the Grants.gov eligibility for this opportunity."
    other = [a.get("description") for a in (body.get("applicantTypes") or [])
             if str(a.get("id")) in ("07", "25")]
    if other:
        notes["_other"] = "; ".join(d for d in other if d)

    close_d, close_iso = parse_dt(body.get("responseDate") or body.get("estApplicationResponseDate"))
    open_d, _ = parse_dt(body.get("postingDate") or body.get("estSynopsisPostingDate"))
    award_d, _ = parse_dt(body.get("estAwardDate"))

    status = "forecast" if is_forecast else "open"
    if close_d and close_d < date.today().isoformat():
        status = "closed"

    reqs = []
    if body.get("costSharing"):
        reqs.append("Cost sharing or matching is required (see the notice for the ratio)")
    rdd = detag(body.get("responseDateDesc"), 200)
    if rdd:
        reqs.append(rdd if len(rdd) > 30 else "Applications close at " + rdd)
    if body.get("applicantEligibilityDesc"):
        reqs.append(detag(body["applicantEligibilityDesc"], 300))
    reqs.append("Applicant must have an active SAM.gov registration and UEI to apply on Grants.gov")

    tags = ["grants-gov", slug(onum)]
    for c in opp.get("cfdas") or []:
        if c.get("cfdaNumber"):
            tags.append("cfda-" + c["cfdaNumber"])
    if is_forecast:
        tags.append("forecast")

    url = "https://www.grants.gov/search-results-detail/" + oid
    rec = {
        "id": "grantsgov-" + slug(onum),
        "title": title,
        "funder": funder,
        "funder_level": "federal",
        "program_url": body.get("fundingDescLinkUrl") or url,
        "source_url": url,
        "summary": desc or "No description published on Grants.gov yet.",
        "eligible_applicants": elig,
        "applicant_notes": notes,
        "project_types": types,
        "geography": {"regions": ["federal"], "counties": [],
                      "notes": "Listed on Grants.gov as a federal opportunity. Confirm the eligible "
                               "geography in the notice — some federal programs are limited to named "
                               "states, basins, or designated areas."},
        "award_min": num(body.get("awardFloor")),
        "award_max": num(body.get("awardCeiling")),
        "cost_share_pct": None,
        "expected_awards": num(body.get("numberOfAwards")),
        "status": status,
        "opens_on": open_d,
        "deadline": close_iso,
        "award_notice_est": award_d[:7] if award_d else None,
        "funds_available_est": num(body.get("estimatedFunding")),
        "disbursement": None,
        "requirements": reqs,
        "tags": tags,
        "last_verified": date.today().isoformat(),
        "verified_by": "grants_gov_api",
        "needs_verification": True,
        "verification_note": ("Imported from the Grants.gov API on %s. Award figures, eligibility and "
                              "cost share come from the Grants.gov record, not the funder's own notice — "
                              "read the NOFO before relying on a number. Project-type tags are "
                              "keyword-assigned and worth a look." % date.today().isoformat()),
        "source_ref": {"api": "grants.gov", "opportunity_id": oid, "opportunity_number": onum,
                       "doc_type": "forecast" if is_forecast else "synopsis"},
    }
    rec["raw_hash"] = hashlib.sha256(
        json.dumps({k: rec[k] for k in ("title", "status", "deadline", "award_min", "award_max",
                                        "expected_awards", "funds_available_est", "summary")},
                   sort_keys=True).encode()).hexdigest()[:16]
    if prev:  # keep hand edits that the API cannot know about
        for k in ("project_types", "cost_share_pct", "disbursement", "geography"):
            if prev.get(k) and prev.get(k) != rec.get(k) and prev.get("verified_by") != "grants_gov_api":
                rec[k] = prev[k]
        if prev.get("needs_verification") is False and prev.get("raw_hash") == rec["raw_hash"]:
            rec["needs_verification"] = False
            rec["verified_by"] = prev.get("verified_by", rec["verified_by"])
    return rec

def score(text):
    t = " " + text.lower() + " "
    s = W_STRONG * sum(1 for p in STRONG if p in t) + W_WEAK * sum(1 for p in WEAK if p in t)
    return s

def relevant(opp):
    body = opp.get("synopsis") or opp.get("forecast") or {}
    owning = (opp.get("owningAgencyCode") or "").upper()
    top = ((opp.get("topAgencyDetails") or {}).get("agencyCode") or owning).split("-")[0].upper()
    if top in AGENCY_BLOCK:
        return False, "agency %s" % top
    if any(sub in owning for sub in AGENCY_BLOCK_SUB):
        return False, "sub-agency %s" % owning
    title = html.unescape(opp.get("opportunityTitle") or "")
    desc = detag(body.get("synopsisDesc") or body.get("forecastDesc"), 4000)
    text = (title + " " + desc).lower()
    # Geo/topic exclusions look at the TITLE and opening lines only — nationwide
    # notices routinely list Alaska, Puerto Rico, "marine", etc. deep in the body.
    head = (title + " " + desc[:400]).lower()
    n = next((p for p in NEGATIVE if p in head), None)
    if n:
        return False, "off-topic wording (%s)" % n
    g = next((p for p in GEO_BLOCK if p in head), None)
    if g:
        return False, "out-of-region (%s)" % g
    scope = (title + " " + desc[:800]).lower()
    if "new york" not in scope and not any(m in scope for m in NATIONWIDE):
        named = [s for s in OTHER_STATES if s in scope]
        if len(named) >= 2:
            return False, "state-scoped (%s)" % ", ".join(named[:3])
    s = score(text)
    if s < SCORE_MIN:
        return False, "score %d" % s
    return True, s

# ---------- catalog passes ----------
def refresh_pass(grants, budget, dry):
    """Re-fetch Grants.gov-sourced records; roll seeded records past deadline to closed."""
    changed = []
    today = date.today().isoformat()
    for g in grants:  # free, source-independent: a passed deadline means closed
        dl = (g.get("deadline") or "")[:10]
        if dl and dl < today and g.get("status") in ("open", "forecast"):
            g["status"] = "closed"
            changed.append((g["id"], "deadline passed → closed"))

    srcd = [g for g in grants if (g.get("source_ref") or {}).get("api") == "grants.gov"]
    srcd.sort(key=lambda g: g.get("last_verified") or "")
    for g in srcd[:budget]:
        oid = g["source_ref"]["opportunity_id"]
        try:
            opp = api("fetchOpportunity", {"opportunityId": int(oid)})
        except Exception as e:
            changed.append((g["id"], "fetch failed: %s" % e)); continue
        new = to_record(opp, prev=g)
        if new["raw_hash"] == g.get("raw_hash"):
            g["last_verified"] = today
            changed.append((g["id"], "unchanged, re-verified"))
        else:
            was = g.get("status")
            g.clear(); g.update(new)
            changed.append((g["id"], "updated (%s → %s)" % (was, new["status"])))
        time.sleep(0.4)
    return changed

def capture_pass(grants, budget, dry, statuses, verbose=False):
    """Search every query, keep the relevant hits, then add the BEST `budget` of them."""
    have_ids = {g["id"] for g in grants}
    have_opps = {(g.get("source_ref") or {}).get("opportunity_id") for g in grants}
    seen, cands, skipped, rejects = set(), [], 0, {}

    # 1. build the candidate pool: a full sweep of the relevant funding categories,
    #    plus keyword sweeps for notices filed under other categories.
    titles, sweeps = {}, [{"keyword": "", "fundingCategories": CATEGORIES, "oppStatuses": statuses}]
    sweeps += [{"keyword": q, "oppStatuses": statuses} for q in QUERIES]
    for sw in sweeps:
        try:
            hits = search_all(sw, cap=400 if sw.get("fundingCategories") else 50)
        except Exception as e:
            print("  ! search %r failed: %s" % (sw.get("fundingCategories") or sw["keyword"], e)); continue
        for hit in hits:
            oid = str(hit.get("id"))
            if oid in seen or oid in have_opps:
                continue
            seen.add(oid)
            titles[oid] = html.unescape(hit.get("title") or "")
    print("  pool: %d unique opportunities" % len(titles))

    # 2. detail-fetch and score the plausible ones
    for oid, title in titles.items():
        if not any(p in title.lower() for p in PRESCREEN):
            skipped += 1; continue
        try:
            opp = fetch_opp(oid)
        except Exception:
            continue
        ok, why = relevant(opp)
        if not ok:
            skipped += 1
            rejects[re.sub(r"\d+", "N", str(why))] = rejects.get(re.sub(r"\d+", "N", str(why)), 0) + 1
            continue
        cands.append((why, oid, opp))

    # 3. best-scoring first, up to the budget
    cands.sort(key=lambda c: -c[0])
    added = []
    for s, oid, opp in cands:
        if len(added) >= budget:
            break
        rec = to_record(opp)
        if rec["id"] in have_ids:
            continue
        have_ids.add(rec["id"]); have_opps.add(oid)
        grants.append(rec)
        added.append((rec["id"], "score %2d | %s | %s | %s" % (
            s, rec["status"], (rec["deadline"] or "no deadline")[:10], rec["title"][:58])))
    if len(cands) > budget:
        print("  (%d relevant candidates, capped at %d — re-run to take the rest)" % (len(cands), budget))
    if verbose and rejects:
        print("  rejects:", ", ".join("%s×%d" % (k, v) for k, v in
              sorted(rejects.items(), key=lambda kv: -kv[1])[:12]))
    return added, skipped

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25, help="max records touched per run (default 25)")
    ap.add_argument("--stale-days", type=int, default=14)
    ap.add_argument("--refresh-only", action="store_true")
    ap.add_argument("--new-only", action="store_true")
    ap.add_argument("--include-closed", action="store_true",
                    help="also capture closed opportunities (default: posted + forecasted only)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CATALOG))
    grants = cat["grants"]
    before = json.dumps(grants, sort_keys=True)
    print("catalog: %d records (generated_at %s)" % (len(grants), cat.get("generated_at")))

    stale_before = (date.today() - timedelta(days=a.stale_days)).isoformat()
    n_stale = sum(1 for g in grants
                  if (g.get("source_ref") or {}).get("api") == "grants.gov"
                  and (g.get("last_verified") or "") < stale_before)

    r_budget = 0 if a.new_only else (a.limit if a.refresh_only else min(n_stale, a.limit // 2))
    c_budget = 0 if a.refresh_only else a.limit - r_budget

    print("plan: refresh up to %d (%d stale), capture up to %d" % (r_budget, n_stale, c_budget))
    changed = refresh_pass(grants, r_budget, a.dry_run) if not a.new_only else []
    statuses = "posted|forecasted" + ("|closed" if a.include_closed else "")
    added, skipped = capture_pass(grants, c_budget, a.dry_run, statuses, verbose=True) if c_budget else ([], 0)

    print("\nrefreshed %d:" % len(changed))
    for i, why in changed:
        print("  ·", i, "—", why)
    print("captured %d new (%d searched hits rejected as off-topic):" % (len(added), skipped))
    for i, why in added:
        print("  +", i, "—", why)

    if a.dry_run:
        print("\n--dry-run: catalog not written")
        return
    if json.dumps(grants, sort_keys=True) == before:
        print("\nno changes; catalog left as-is")
        return
    cat["generated_at"] = date.today().isoformat()
    cat["provenance_note"] = (cat.get("provenance_note", "").split(" Records sourced from")[0].strip() +
        " Records sourced from the Grants.gov API (verified_by=\"grants_gov_api\") are machine-imported: "
        "their figures come from the Grants.gov record rather than the funder's own notice, and their "
        "project-type tags are keyword-assigned, so they stay needs_verification=true until a human "
        "confirms them.")
    tmp = CATALOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cat, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, CATALOG)
    print("\nwrote %s — %d records total" % (CATALOG, len(grants)))
    print("next: python3 grant_import.py")

if __name__ == "__main__":
    main()
