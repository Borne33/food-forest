#!/usr/bin/env python3
"""
Derive soil_texture and soil_drainage (for the Soil Exam matcher) from each
plant's existing soil prose. Best-effort keyword parse; review on the Verify
page. Textures: Sandy / Loam / Clay / Silt. Drainage: Well-drained / Moist / Wet.

Usage:  python3 populate_soildims.py
"""
import foodforest_import as ff


def texture(soil):
    s = (soil or "").lower()
    out = set()
    if "sand" in s: out.add("Sandy")
    if "clay" in s: out.add("Clay")
    if "silt" in s: out.add("Silt")
    if "loam" in s or "rich" in s or "average" in s or "garden" in s or "fertile" in s:
        out.add("Loam")
    if any(w in s for w in ("adaptable", "tolerat", "wide range", "any soil",
                            "most soil", "variety of soil", "poor")):
        out |= {"Sandy", "Loam", "Clay", "Silt"}
    if not out:
        out = {"Loam"}
    return sorted(out)


def drainage(soil):
    s = (soil or "").lower()
    out = set()
    if any(w in s for w in ("well-drain", "well drain", "dry", "drought", "sandy", "rocky")):
        out.add("Well-drained")
    if "moist" in s or "rich" in s or "average" in s or "loam" in s:
        out.add("Moist")
    if any(w in s for w in ("wet", "saturat", "marsh", "pond", "bog", "swamp",
                            "standing water", "shallow water", "stream", "floodplain")):
        out.add("Wet")
    if "adaptable" in s or "wet to dry" in s or "dry to wet" in s or "wide range" in s:
        out |= {"Well-drained", "Moist", "Wet"}
    if not out:
        out = {"Well-drained", "Moist"}
    return sorted(out)


def main():
    env = ff.load_env()
    rows = ff.supabase_request(env, "GET", "plants?select=id,soil&order=id") or []
    for r in rows:
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"soil_texture": texture(r.get("soil")),
                  "soil_drainage": drainage(r.get("soil"))},
            extra_headers={"Prefer": "return=minimal"})
    print("set soil texture/drainage on %d plants" % len(rows))


if __name__ == "__main__":
    main()
