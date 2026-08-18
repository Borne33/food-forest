#!/usr/bin/env python3
"""Record the taxonomic synonyms resolved by GBIF for the Three Sisters batch.

One plants row per ACCEPTED species; every name the user's list carried that GBIF
resolves to a synonym or an infraspecific taxon becomes a plant_synonyms row, so
the vendor matcher and search still find it.  (plant_synonyms_uniq is an EXPRESSION
index — PostgREST can't ON CONFLICT it, so check first, then insert.)
"""
import json, sys, urllib.parse
from pathlib import Path
import foodforest_import as ff

SYN = {
  # accepted sci                  -> names that resolve to it
  "Cucurbita argyrosperma": ["Cucurbita mixta", "Cucurbita kellyana",
                             "Cucurbita palmeri", "Cucurbita sororia",
                             "Cucurbita argyrosperma subsp. sororia"],
  "Cucurbita palmata":      ["Cucurbita californica"],
  "Cucurbita okeechobeensis": ["Cucurbita martinezii",
                               "Cucurbita okeechobeensis subsp. martinezii"],
  "Cucurbita pedatifolia":  ["Cucurbita moorei"],
  "Cucurbita radicans":     ["Cucurbita gracilior"],
  "Cucurbita pepo":         ["Cucurbita fraterna", "Cucurbita texana",
                             "Cucurbita melopepo", "Cucurbita pepo var. texana",
                             "Cucurbita pepo var. ozarkana"],
  "Phaseolus augusti":      ["Phaseolus bolivianus"],
  "Phaseolus vulcanicus":   ["Phaseolus pluriflorus"],
  "Phaseolus pedicellatus": ["Phaseolus grayanus", "Phaseolus laxiflorus",
                             "Phaseolus pedicellatus var. grayanus"],
  "Phaseolus sonorensis":   ["Phaseolus albinervus"],
  "Phaseolus maculatus":    ["Phaseolus ritensis", "Phaseolus maculatus subsp. ritensis"],
  "Phaseolus polystachios": ["Phaseolus smilacifolius"],
  "Phaseolus leptostachyus":["Phaseolus anisotrichos"],
  "Phaseolus micranthus":   ["Phaseolus brevicalyx"],
  "Phaseolus dumosus":      ["Phaseolus leucanthus", "Phaseolus x dumosus"],
  "Phaseolus xanthotrichus":["Phaseolus xanthrotrichus"],
}

env = ff.load_env()

def q(path):
    return ff.supabase_request(env, "GET", path)

ids = {}
for sci in SYN:
    r = q("plants?select=id,sci&sci=eq." + urllib.parse.quote(sci))
    if not r:
        sys.exit("missing plant row: " + sci)
    ids[sci] = r[0]["id"]

have = {row["name"].lower() for row in
        (q("plant_synonyms?select=name&limit=5000") or [])}

new = []
for sci, names in SYN.items():
    for n in names:
        if n.lower() in have:
            continue
        have.add(n.lower())
        new.append({"plant_id": ids[sci], "name": n, "kind": "sci",
                    "source": "GBIF backbone / WCVP"})

print("%d synonym row(s) to insert" % len(new))
if new and "--dry-run" not in sys.argv:
    ff.supabase_request(env, "POST", "plant_synonyms", body=new,
                        extra_headers={"Prefer": "return=minimal"})
    print("✓ inserted")
for r in new:
    print("   %-42s -> %s" % (r["name"], next(s for s, i in ids.items() if i == r["plant_id"])))
