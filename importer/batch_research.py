#!/usr/bin/env python3
"""Add one layer-ordered batch of the NYFA native influx (ground cover -> canopy).

Builds records from friendly sources only (Wikipedia + NYFA row; PFAF is read
CACHE-ONLY here so this never hits pfaf.org). Edibility/medicinal scores come
from an explicit Wikipedia statement (tier A) when present, else stay 0/"N" for
the slow PFAF trickle (pfaf_trickle.py) to fill later. Writes drafts and upserts
ONLY the new species (on_conflict=sci), so existing rows are never clobbered.

  python3 batch_research.py 1 --dry-run     # preview batch 1 (no writes)
  python3 batch_research.py 1               # build + upsert batch 1
Then:  python3 backfill.py                  # hardiness/propagation/lifecycle/USDA
"""
import sys, json, argparse, os
sys.path.insert(0, ".")
import foodforest_import as ff
import research_plant as rp

BATCH = 250
HABIT2TYPE = [("Tree", "Tree"), ("Shrub", "Shrub"), ("Subshrub", "Shrub"), ("Vine", "Vine"),
              ("Graminoid", "Grass"), ("Fern", "Fern"), ("lycophyte", "Fern")]
def to_type(gh):
    for k, v in HABIT2TYPE:
        if k in (gh or ""): return v
    return "Herb"   # Forb/herb, Herbaceous, blank/unknown

def db_scis():
    scis = set(); off = 0
    while True:
        pg = ff.supabase_request(None if False else ff.load_env(), "GET",
            "plants?select=sci&order=id&limit=1000&offset=%d" % off) or []
        scis |= set(" ".join(r["sci"].split()[:2]).lower() for r in pg)
        if len(pg) < 1000: break
        off += 1000
    return scis

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rp.PFAF_NETWORK = False   # bulk build: no PFAF network traffic
    env = ff.load_env()
    ordered = json.load(open(os.path.join(rp.HERE, "nyfa_ordered.json")))
    chunk = ordered[(a.batch - 1) * BATCH: a.batch * BATCH]
    if not chunk:
        print("No species in batch", a.batch); return
    have = db_scis()
    ff.DRAFTS_DIR.mkdir(exist_ok=True)
    rows = []; wiki_ed = 0; skipped = 0
    for i, r in enumerate(chunk):
        sci = r["Scientific_Name"]
        if " ".join(sci.split()[:2]).lower() in have:
            skipped += 1; continue
        typ = to_type(r["Growth_Habit"])
        d = rp.research(sci, r["Common_Name"], r["Family"], typ, r["Duration"],
                        r["Native"], r.get("Habitat", ""))
        d.pop("_meta", None)
        errs = ff.validate_draft(d)
        if errs:
            print("SKIP", sci, errs); continue
        if d["scores"]["raw"][0] or d["scores"]["cooked"][0] or d["scores"]["med"][0]:
            wiki_ed += 1
        (ff.DRAFTS_DIR / (ff.slugify(sci) + ".json")).write_text(json.dumps(d, indent=2))
        rows.append(ff.clean_row(d))
        if (i + 1) % 50 == 0: print("...researched", i + 1, "/", len(chunk))
    print("\nBatch %d: %d new rows, %d already in DB, %d with a documented edible/med use"
          % (a.batch, len(rows), skipped, wiki_ed))
    if a.dry_run:
        print("--dry-run: drafts written, nothing upserted.")
        return
    up = 0
    for i in range(0, len(rows), 40):
        res = ff.supabase_request(env, "POST", "plants?on_conflict=sci", body=rows[i:i+40],
            extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        up += len(res or [])
    print("upserted %d rows" % up)

if __name__ == "__main__":
    main()
