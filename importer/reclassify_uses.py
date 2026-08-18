#!/usr/bin/env python3
"""Re-run populate_uses' classifiers over a TARGETED set of plants.

`populate_uses.py` is fill-only and its `--force` rewrites all ~2,500 rows, which
would clobber hand corrections made on the Verify page. This re-runs the same
functions over just the rows you name, and refuses to touch `human_verified` rows
unless you pass --include-verified. Use it after fixing a keyword false positive.

  python3 reclassify_uses.py --file three_sisters.txt --dry-run
  python3 reclassify_uses.py --contaminated          # rows whose stored tags no
                                                     # longer match the classifier
"""
import argparse, json, sys
from pathlib import Path
import foodforest_import as ff
import populate_uses as pu

HERE = Path(__file__).resolve().parent
SEL = ("plants?select=id,sci,common,type,life,edible_parts,prep,other_uses,risks,"
       "scores,nf,pol,lifecycle,food_types,material_types,human_verified&order=id")


def classify(r):
    return (pu.lifecycle_of(r["sci"], r["type"], r["life"]),
            pu.food_types_of(r["edible_parts"], r["scores"]),
            pu.material_types_of(r["other_uses"], r["prep"], r["risks"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="newline-separated scientific names")
    ap.add_argument("--contaminated", action="store_true",
                    help="every row where stored tags disagree with the classifier")
    ap.add_argument("--include-verified", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    env = ff.load_env()
    rows = ff.fetch_paged(env, SEL)

    if a.file:
        want = {l.strip() for l in (HERE / a.file).read_text().splitlines() if l.strip()}
        rows = [r for r in rows if r["sci"] in want]
    elif not a.contaminated:
        sys.exit("give --file or --contaminated")

    changed = []
    for r in rows:
        lc, ft, mt = classify(r)
        old_ft = sorted(r.get("food_types") or [])
        old_mt = sorted(r.get("material_types") or [])
        if sorted(ft) == old_ft and sorted(mt) == old_mt and lc == r.get("lifecycle"):
            continue
        if r.get("human_verified") and not a.include_verified:
            print("  · skipped (human_verified): %s" % r["sci"])
            continue
        changed.append((r, lc, ft, mt, old_ft, old_mt))

    print("%d row(s) would change" % len(changed))
    for r, lc, ft, mt, oft, omt in changed:
        bits = []
        if sorted(ft) != oft:
            bits.append("food %s -> %s" % (oft or "[]", sorted(ft) or "[]"))
        if sorted(mt) != omt:
            bits.append("mat %s -> %s" % (omt or "[]", sorted(mt) or "[]"))
        if lc != r.get("lifecycle"):
            bits.append("lifecycle %s -> %s" % (r.get("lifecycle"), lc))
        print("  %-34s %s" % (r["sci"][:34], "; ".join(bits)))

    if a.dry_run or not changed:
        print("\n(dry run — nothing written)" if a.dry_run else "")
        return
    for r, lc, ft, mt, _, _ in changed:
        eco, mat = pu.split_uses(r["other_uses"], r["prep"], r["nf"], r["pol"],
                                 r["scores"]["eco"][0])
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"lifecycle": lc, "food_types": ft, "material_types": mt,
                  "eco_uses": eco, "material_uses": mat},
            extra_headers={"Prefer": "return=minimal"})
    print("\n✓ reclassified %d row(s)" % len(changed))


if __name__ == "__main__":
    main()
