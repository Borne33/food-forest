#!/usr/bin/env python3
"""
Populate soil nutrient guidance for every plant: soil_ph (preferred range) and
soil_n / soil_p / soil_k (Low / Moderate demand).

Native plants are generally low-input; this is generalized guidance, not a soil
test. pH is set from known acid-lovers (Ericaceae etc.) vs limestone-tolerant
genera, defaulting to slightly-acid-to-neutral. N/P/K demand is heuristic:
nitrogen-fixers supply their own N; fruit/nut producers want moderate P & K.

Usage:  python3 populate_soil.py
"""
import foodforest_import as ff

ACID_FAMILIES = {"Ericaceae"}
ACID_GENERA   = {"Comptonia", "Morella", "Ilex", "Kalmia", "Rhododendron"}
ALK_GENERA    = {"Celtis", "Juniperus", "Cercis", "Gymnocladus", "Ceanothus"}
ALK_SCI       = {"Quercus macrocarpa"}   # bur oak — limestone tolerant


def soil_ph(sci, family):
    genus = (sci or "").split(" ")[0]
    if family in ACID_FAMILIES or genus in ACID_GENERA:
        return "4.5–5.5 (acidic)"
    if genus in ALK_GENERA or sci in ALK_SCI:
        return "6.5–8.0 (neutral–alkaline)"
    return "5.5–7.0 (slightly acidic–neutral)"


def npk(nf, is_fruit):
    n = "Low — supplies its own (N-fixer)" if nf else ("Moderate" if is_fruit else "Low")
    p = "Moderate" if is_fruit else "Low"
    k = "Moderate" if is_fruit else "Low"
    return n, p, k


def main():
    env = ff.load_env()
    rows = ff.supabase_request(env, "GET",
        "plants?select=id,sci,family,nf,min_plants_fruit&order=id") or []
    for r in rows:
        ph = soil_ph(r.get("sci"), r.get("family"))
        n, p, k = npk(bool(r.get("nf")), r.get("min_plants_fruit") is not None)
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"soil_ph": ph, "soil_n": n, "soil_p": p, "soil_k": k},
            extra_headers={"Prefer": "return=minimal"})
    print("set soil nutrients on %d plants" % len(rows))


if __name__ == "__main__":
    main()
