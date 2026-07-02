#!/usr/bin/env python3
"""
Populate plants.hardiness_zones and plants.deer_resistant for every plant.

hardiness_zones is DERIVED from the native range and left intentionally
OVER-WIDE (coldest native-state zone .. warmest native-state zone, no cap) to
leave room for future growth.

deer_resistant uses evidence-based patterns: aromatic mints, toxic plants,
ferns, and grasses/sedges/rushes are rarely browsed; fruits, berries, nuts, and
tender greens are frequently browsed.

Usage:  python3 populate_traits.py
"""
import foodforest_import as ff

# Approx USDA zone span present in each state -> (coldest, warmest)
ZONE = {
 "ME":(3,6),"NH":(3,6),"VT":(3,5),"MA":(5,7),"RI":(5,7),"CT":(5,7),"NY":(3,7),
 "NJ":(6,7),"PA":(5,7),"DE":(7,7),"MD":(6,8),"DC":(7,7),"VA":(5,8),"WV":(5,7),
 "NC":(5,8),"SC":(7,9),"GA":(6,9),"FL":(8,11),"AL":(7,9),"MS":(7,9),"TN":(6,8),
 "KY":(6,7),"OH":(5,6),"IN":(5,6),"IL":(5,7),"MI":(4,6),"WI":(3,5),"MN":(3,5),
 "IA":(4,5),"MO":(5,7),"AR":(6,8),"LA":(8,9),"ND":(3,4),"SD":(3,5),"NE":(4,5),
 "KS":(5,7),"OK":(6,8),"TX":(6,9),"MT":(3,5),"WY":(3,5),"CO":(3,7),"NM":(4,9),
 "ID":(3,7),"UT":(4,9),"AZ":(4,10),"NV":(4,9),"WA":(4,9),"OR":(4,9),"CA":(5,11),
 "AK":(1,5),"HI":(10,12),
}


def hardiness(states):
    zs = [ZONE[s] for s in states if s in ZONE]
    if not zs:
        return None
    lo = min(z[0] for z in zs)
    hi = max(z[1] for z in zs)   # intentionally uncapped / over-wide
    return "%d-%d" % (lo, hi) if lo != hi else str(lo)


# ---- deer resistance (evidence-based patterns) ----
RESIST_FAM = {"Lamiaceae","Poaceae","Cyperaceae","Juncaceae","Iridaceae",
  "Apocynaceae","Amaryllidaceae","Myricaceae","Cupressaceae","Aristolochiaceae",
  "Ranunculaceae","Phrymaceae","Scrophulariaceae","Verbenaceae","Asteraceae",
  "Lauraceae","Anacardiaceae","Urticaceae","Campanulaceae"}
RESIST_TYPE = {"Fern", "Grass"}
RESIST_GENUS = {"Baptisia", "Tephrosia", "Gymnocladus", "Podophyllum", "Comptonia"}
BROWSED_GENUS = {"Helianthus"}  # browsed despite resistant family/type


def deer_resistant(sci, family, typ):
    genus = (sci or "").split(" ")[0]
    if genus in BROWSED_GENUS:
        return False
    return bool(typ in RESIST_TYPE or family in RESIST_FAM or genus in RESIST_GENUS)


def main():
    env = ff.load_env()
    rows = ff.supabase_request(env, "GET",
        "plants?select=id,common,sci,family,type,native_states,invasive_states&order=id") or []
    n_deer = 0
    for r in rows:
        states = r.get("native_states") or r.get("invasive_states") or []
        hz = hardiness(states) or "4-8"
        dr = deer_resistant(r.get("sci"), r.get("family"), r.get("type"))
        n_deer += dr
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"hardiness_zones": hz, "deer_resistant": dr},
            extra_headers={"Prefer": "return=minimal"})
    print("updated %d plants; %d flagged deer-resistant" % (len(rows), n_deer))


if __name__ == "__main__":
    main()
