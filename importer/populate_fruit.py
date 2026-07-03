#!/usr/bin/env python3
"""
Populate min_plants_fruit (minimum plants needed to set fruit — 2 means the
species needs a cross-pollination partner or is dioecious) and years_to_fruit
for fruit/nut-producing plants. Non-fruiting plants are left NULL (n/a).

Curated by genus with a few species overrides. Best-effort draft — review on
the Verify page.

Usage:  python3 populate_fruit.py
"""
import foodforest_import as ff

# genus -> (min_plants_to_fruit, years_to_first_fruit)
FRUIT = {
 "Asimina":(2,"5-7"), "Diospyros":(2,"4-6"), "Amelanchier":(1,"2-4"),
 "Prunus":(2,"3-5"), "Morus":(1,"2-3"), "Corylus":(2,"3-5"),
 "Carya":(2,"10-15"), "Juglans":(2,"6-10"), "Castanea":(2,"3-6"),
 "Quercus":(1,"20-30"), "Fagus":(1,"20-40"), "Celtis":(1,"5-8"),
 "Vaccinium":(2,"2-3"), "Aronia":(1,"2-3"), "Sambucus":(2,"2-3"),
 "Ribes":(1,"1-2"), "Rubus":(1,"1-2"), "Rosa":(1,"2-3"), "Fragaria":(1,"1"),
 "Vitis":(1,"2-3"), "Passiflora":(1,"1-2"), "Viburnum":(2,"2-4"),
 "Shepherdia":(2,"2-4"), "Lindera":(2,"3-5"), "Juniperus":(2,"3-5"),
 "Rhus":(2,"2-4"), "Gaultheria":(1,"2-3"), "Arctostaphylos":(1,"2-3"),
 "Elaeagnus":(1,"2-3"),
}
# species that differ from their genus default (mostly self-fertile cherries)
OVERRIDE = {
 "Prunus serotina":(1,"3-5"), "Prunus virginiana":(1,"3-4"),
 "Prunus pumila":(1,"2-4"),
}


def traits_for(sci):
    if sci in OVERRIDE:
        return OVERRIDE[sci]
    genus = (sci or "").split(" ")[0]
    return FRUIT.get(genus)


def main():
    env = ff.load_env()
    rows = ff.supabase_request(env, "GET", "plants?select=id,common,sci&order=id") or []
    n = 0
    for r in rows:
        t = traits_for(r.get("sci"))
        if not t:
            continue
        mn, yrs = t
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"min_plants_fruit": mn, "years_to_fruit": yrs},
            extra_headers={"Prefer": "return=minimal"})
        n += 1
    print("set fruit traits on %d plants (of %d)" % (n, len(rows)))


if __name__ == "__main__":
    main()
