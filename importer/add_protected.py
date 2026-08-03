#!/usr/bin/env python3
"""One-off: add the NY-protected native plants (6 CRR-NY 193.3) that are missing
from the database, as full records with reliable taxonomy.

Sources, most reliable first:
  - family + growth-form (type) from an existing DB row of the SAME GENUS when we
    already have one (same genus => same family, near-always same growth form);
  - otherwise USDA PLANTS (family from the taxonomic Ancestors, type from
    GrowthHabits, lifecycle hint from Durations, common name fallback).

Edibility/use scores are left at 0 / "no evidence" (honest — these are rare
natives, not documented food plants), except a structural Lifecycle score by
growth form. Nativity is set to NY (they are NY natives); backfill fills
hardiness, N-fixation, propagation, etc. Records carry ny_protected_status.

Writes drafts/<slug>.json for the record AND upserts ONLY these rows (POST
on_conflict=sci) so existing plants' hand-edits are never clobbered.

  python3 add_protected.py --dry-run     # build drafts, don't write to DB
  python3 add_protected.py               # build drafts + upsert the new rows
"""
import sys, json, argparse, time
sys.path.insert(0, ".")
import foodforest_import as ff
import usda_enrich as ue

REPORT = "/tmp/nycrr_report.json"
NYSDEC = ["NYSDEC 6 NYCRR 193.3 (protected native plants)",
          "https://dec.ny.gov/nature/animals-fish-plants/plants/state-protected-plants"]
GH2TYPE = {"Tree": "Tree", "Shrub": "Shrub", "Subshrub": "Shrub", "Vine": "Vine",
           "Forb/herb": "Herb", "Graminoid": "Grass"}
FERN_GROUPS = {"Fern", "Lycopod", "Horsetail", "Quillwort", "Whisk-fern", "Spikemoss", "Clubmoss"}
LIFE_SCORE = {"Tree": 10, "Shrub": 10, "Vine": 9, "Fern": 6, "Grass": 6, "Groundcover": 6, "Herb": 6}

def dominant(counter):
    return counter.most_common(1)[0][0] if counter else None

def build_genus_maps(env):
    rows = ff.supabase_request(env, "GET", "plants?select=sci,family,type&limit=2000") or []
    from collections import defaultdict, Counter
    fam = defaultdict(Counter); typ = defaultdict(Counter)
    for r in rows:
        g = r["sci"].split()[0]
        if r.get("family"): fam[g][r["family"]] += 1
        if r.get("type"): typ[g][r["type"]] += 1
    return ({g: dominant(c) for g, c in fam.items()},
            {g: dominant(c) for g, c in typ.items()})

def usda_lookup(sci):
    """(family, type, life_text, common, symbol) from USDA, or Nones on miss."""
    try:
        r = ue.resolve(sci)
    except Exception:
        r = None
    if not r:
        return (None, None, "", None, None)
    sym, cid, nm = r
    prof = ue.api_get("PlantProfile?symbol=%s" % sym) or {}
    fam = None
    for a in prof.get("Ancestors") or []:
        if a.get("Rank") == "Family":
            parts = ue.strip_html(a.get("ScientificName", "")).split()
            fam = parts[0] if parts else None
    habits = prof.get("GrowthHabits") or []
    group = prof.get("Group") or ""
    typ = None
    if group in FERN_GROUPS:
        typ = "Fern"
    else:
        for h in habits:
            if h in GH2TYPE:
                typ = GH2TYPE[h]; break
    durs = prof.get("Durations") or []
    life = " ".join([" / ".join(durs)] + ([habits[0]] if habits else [])).strip()
    common = ue.strip_html(prof.get("CommonName") or "") or None
    return (fam, typ, life, common, sym)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    env = ff.load_env()
    missing = json.load(open(REPORT))["missing"]  # [cat, sci, common]
    fam_map, typ_map = build_genus_maps(env)
    ff.DRAFTS_DIR.mkdir(exist_ok=True)

    rows = []
    src_counts = {"genus": 0, "usda": 0, "fallback": 0}
    for i, (cat, sci, common) in enumerate(missing):
        genus = sci.split()[0]
        family = fam_map.get(genus); typ = typ_map.get(genus); life = ""; symbol = None
        source = "genus"
        if not (family and typ):
            f2, t2, life2, c2, sym = usda_lookup(sci)
            family = family or f2
            typ = typ or t2
            life = life2 or ""
            symbol = sym
            common = common or c2
            source = "usda" if (f2 or t2) else "fallback"
            time.sleep(0.2)
        if not typ:
            typ = "Herb"
        src_counts[source] += 1
        sources = [NYSDEC]
        if symbol:
            sources.append(["USDA PLANTS", "https://plants.usda.gov/plant-profile/%s" % symbol])
        draft = {
            "common": common or sci, "sci": sci, "family": family or "", "type": typ,
            "life": life, "edible_parts": "", "other_uses": "", "prep": "", "harvest": "",
            "sun": "", "soil": "", "risks": "", "buy": "",
            "native_states": ["NY"], "native_regions": [], "native_to_us": True,
            "invasive_states": [], "invasive_everywhere": False, "dec_priority": False,
            "nf": False, "pol": False,
            "scores": {"raw": [0, "N"], "cooked": [0, "N"], "life": [LIFE_SCORE.get(typ, 6), "A"],
                       "eco": [0, "N"], "materials": [0, "N"], "med": [0, "N"]},
            "sources": sources, "hardiness_zones": "", "deer_resistant": False,
            "native_north_america": True, "native_americas": False,
        }
        errs = ff.validate_draft(draft)
        if errs:
            print("SKIP", sci, errs); continue
        (ff.DRAFTS_DIR / (ff.slugify(sci) + ".json")).write_text(json.dumps(draft, indent=2))
        row = ff.clean_row(draft)
        row["ny_protected_status"] = cat        # not a COLUMNS field; set explicitly
        rows.append(row)
        if (i + 1) % 50 == 0:
            print("...processed", i + 1)

    print("built %d rows — sources: %s" % (len(rows), src_counts))
    if a.dry_run:
        print("--dry-run: drafts written, nothing upserted.")
        return
    # upsert only these rows, in batches, on conflict sci
    B = 40
    up = 0
    for i in range(0, len(rows), B):
        chunk = rows[i:i+B]
        for attempt in range(5):
            try:
                res = ff.supabase_request(env, "POST", "plants?on_conflict=sci", body=chunk,
                    extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"})
                up += len(res or []); break
            except Exception as e:
                if attempt == 4: raise
                print("  retry batch %d (%s)" % (i//B, str(e)[:60])); time.sleep(3)
    print("✓ upserted %d rows" % up)

if __name__ == "__main__":
    main()
