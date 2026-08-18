#!/usr/bin/env python3
"""Apply only the Three Sisters batch (Cucurbita / Phaseolus / Strophostyles / Zea)."""
import json, sys
from pathlib import Path
import foodforest_import as ff

HERE = Path(__file__).resolve().parent
NAMES = [l.strip() for l in (HERE / "three_sisters.txt").read_text().splitlines() if l.strip()]

env = ff.load_env()
rows = []
for sci in NAMES:
    f = HERE / "drafts" / (ff.slugify(sci) + ".json")
    obj = json.loads(f.read_text())
    errs = ff.validate_draft(obj)
    if errs:
        sys.exit("%s: %s" % (f.name, errs))
    rows.append(ff.clean_row(obj))

print("%d row(s) ready" % len(rows))
if "--dry-run" in sys.argv:
    for r in rows:
        print("  · %-34s %-22s regions=%s" % (r["sci"], r["common"][:22], r["native_regions"]))
    sys.exit(0)

done = 0
for i in range(0, len(rows), 40):                       # chunk: PostgREST payload sanity
    chunk = rows[i:i + 40]
    res = ff.supabase_request(
        env, "POST", "plants?on_conflict=sci", body=chunk,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"})
    done += len(res or [])
    print("  upserted %d (%d/%d)" % (len(res or []), done, len(rows)))
print("\n✓ Upserted %d row(s) into plants." % done)
