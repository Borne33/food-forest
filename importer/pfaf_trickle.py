#!/usr/bin/env python3
"""Slow, respectful PFAF enrichment. Fills edibility / medicinal / materials
scores and edible-parts/prep/hazards/sun/soil/other-uses prose for plants that
lack them, pulling from pfaf.org ONE species at a time with a long delay and a
per-run cap. Every page is cached, so nothing is ever re-fetched.

Run it repeatedly (e.g. a daily cron) until coverage is complete:

  python3 pfaf_trickle.py --limit 120        # up to 120 new PFAF fetches this run
  python3 pfaf_trickle.py --limit 40 --delay 30

Non-clobbering: PFAF star ratings (authoritative, ethnobotanical) set the use
scores; prose fields are filled only where the DB row is currently empty. A
species with no PFAF page is skipped and retried on a later run.
"""
import sys, argparse, time, re
sys.path.insert(0, ".")
import foodforest_import as ff
import research_plant as rp

def targets(env):
    """Sparse plants first: no edible_parts yet. Paginated past the 1000 cap."""
    out = []; off = 0
    while True:
        pg = ff.supabase_request(env, "GET",
            "plants?select=id,sci,edible_parts,prep,risks,sun,soil,other_uses,scores"
            "&order=id&limit=1000&offset=%d" % off) or []
        out += pg
        if len(pg) < 1000: break
        off += 1000
    return [r for r in out if not (r.get("edible_parts") or "").strip()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120, help="max NEW PFAF fetches this run")
    ap.add_argument("--delay", type=float, default=None, help="seconds between PFAF fetches")
    a = ap.parse_args()
    rp.PFAF_NETWORK = True
    if a.delay: rp.PFAF_DELAY = a.delay
    env = ff.load_env()
    todo = targets(env)
    print("%d plants still lacking edible-parts data; PFAF delay %.0fs, cap %d/run"
          % (len(todo), rp.PFAF_DELAY, a.limit))
    import os
    fetched = updated = 0
    for r in todo:
        if fetched >= a.limit: break
        if os.path.exists(rp._cache_path("pfaf", r["sci"])): continue  # already attempted — skip (converges)
        pf = rp.pfaf(r["sci"])          # paced network fetch (+cache)
        fetched += 1
        if not pf: continue
        sc = r.get("scores") or {}
        patch = {}
        # authoritative use scores from PFAF star ratings (ethnobotanical, tier E)
        def setscore(key, rating, tier="E"):
            if rating and rating > 0:
                sc[key] = [min(10, rating * 2), tier]
        eu = (pf["edible_uses"] or "").lower()
        if pf["er"] > 0:
            base = min(10, pf["er"] * 2)
            if "raw" in eu: sc["raw"] = [base, "E"]
            if any(w in eu for w in ("cook", "boil", "roast", "steam", "baked", "fried")): sc["cooked"] = [base, "E"]
            if sc.get("raw", [0])[0] == 0 and sc.get("cooked", [0])[0] == 0: sc["cooked"] = [max(2, base - 2), "E"]
        setscore("med", pf["mr"]); setscore("materials", pf.get("our", 0), "A")
        patch["scores"] = sc
        # prose fields: fill only where empty
        def fill(col, val):
            if val and not (r.get(col) or "").strip(): patch[col] = val
        fill("edible_parts", pf["edible_parts"]); fill("prep", pf["edible_uses"])
        fill("risks", pf["hazards"]); fill("other_uses", pf["other_uses"])
        cult = pf.get("cultivation", "")
        lights = [x for x in ("full sun", "semi-shade", "part shade", "full shade") if x in cult.lower()]
        if lights: fill("sun", "; ".join(dict.fromkeys(l.capitalize() for l in lights)))
        for s in re.split(r"(?<=[.])\s+", cult):
            if "soil" in s.lower(): fill("soil", s.strip()); break
        # add a PFAF source if not present
        srcs = None
        cur = ff.supabase_request(env, "GET", "plants?select=sources&id=eq.%d" % r["id"])
        if cur and cur[0].get("sources") is not None:
            srcs = cur[0]["sources"]
            if not any("PFAF" in (s[0] if s else "") for s in srcs):
                srcs = srcs + [["Plants For A Future (PFAF)", pf["url"]]]
                patch["sources"] = srcs
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"], body=patch,
                            extra_headers={"Prefer": "return=minimal"})
        updated += 1
    print("PFAF fetched %d new pages; enriched %d plants." % (fetched, updated))

if __name__ == "__main__":
    main()
