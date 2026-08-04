#!/usr/bin/env python3
"""Slow, respectful enrichment from the Native American Ethnobotany Database
(naeb.brit.org) — documented Food / Drug(medicine) / Fiber-Dye uses for North
American natives, with tribe + citation. Ethnobotanical evidence -> tier "E".

Same discipline as the PFAF trickle: one species at a time, long delay, per-run
cap, everything cached (fetched at most once). Fills use-scores where the DB has
none and adds an NAEB citation. Run repeatedly (e.g. hourly cron):

  python3 naeb_trickle.py --limit 50
"""
import sys, argparse, os, re
sys.path.insert(0, ".")
import foodforest_import as ff
import research_plant as rp

def targets(env):
    out = []; off = 0
    while True:
        pg = ff.supabase_request(env, "GET",
            "plants?select=id,sci,edible_parts,other_uses,material_types,scores,sources"
            "&order=id&limit=1000&offset=%d" % off) or []
        out += pg
        if len(pg) < 1000: break
        off += 1000
    # prioritise plants with no edible-parts AND weak use scores
    def weak(r):
        s = r.get("scores") or {}
        return (s.get("raw", [0])[0] == 0 and s.get("cooked", [0])[0] == 0
                and s.get("med", [0])[0] == 0 and s.get("materials", [0])[0] == 0)
    return [r for r in out if weak(r) or not (r.get("edible_parts") or "").strip()]

MAT_TYPES = {"fiber": "Fiber/Cordage", "cordage": "Fiber/Cordage", "basketry": "Basketry/Weaving",
             "weaving": "Basketry/Weaving", "dye": "Dye", "soap": "Soap/Saponin", "wax": "Wax/Resin/Gum"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--delay", type=float, default=None)
    a = ap.parse_args()
    if a.delay: rp.NAEB_DELAY = a.delay
    env = ff.load_env()
    todo = targets(env)
    print("%d candidate plants; NAEB delay %.0fs, cap %d/run" % (len(todo), rp.NAEB_DELAY, a.limit))
    fetched = updated = 0
    for r in todo:
        if fetched >= a.limit: break
        cached = os.path.exists(rp._cache_path("naeb", r["sci"]))
        nb = rp.naeb(r["sci"])
        if not cached: fetched += 1
        if not nb: continue
        sc = r.get("scores") or {}
        patch = {}
        if nb["food"]:
            base = min(9, 4 + len(nb["food"]))
            blob = " ".join(nb["food"]).lower()
            if "raw" in blob: sc["raw"] = [base, "E"]
            if any(w in blob for w in ("cook", "boil", "roast", "dried", "bread", "baked", "sauce")): sc["cooked"] = [base, "E"]
            if sc.get("raw", [0])[0] == 0 and sc.get("cooked", [0])[0] == 0: sc["cooked"] = [base, "E"]
        if nb["drug"]: sc["med"] = [min(9, 4 + len(nb["drug"])), "E"]
        if nb["mat"]: sc["materials"] = [min(9, 3 + len(nb["mat"])), "E"]
        patch["scores"] = sc
        if nb["parts"] and not (r.get("edible_parts") or "").strip():
            patch["edible_parts"] = ", ".join(p.capitalize() for p in nb["parts"])
        if nb["mat"] and not (r.get("other_uses") or "").strip():
            patch["other_uses"] = " ".join(nb["mat"])[:1500]
        # material_types from keywords (merge, no dup)
        mt = list(r.get("material_types") or [])
        for u in nb["mat"]:
            for k, v in MAT_TYPES.items():
                if k in u.lower() and v not in mt: mt.append(v)
        if mt != (r.get("material_types") or []): patch["material_types"] = mt
        # citation
        srcs = list(r.get("sources") or [])
        if not any("Ethnobotany" in (s[0] if s else "") for s in srcs):
            srcs.append(["Native American Ethnobotany Database (BRIT)", nb["url"]])
            patch["sources"] = srcs
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"], body=patch,
                            extra_headers={"Prefer": "return=minimal"})
        updated += 1
    print("NAEB fetched %d new pages; enriched %d plants." % (fetched, updated))

if __name__ == "__main__":
    main()
