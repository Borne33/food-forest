#!/usr/bin/env python3
"""Fill each plant's `propagation` text — how to make more of the plant, and how
to collect the seed / cutting / division involved.

Three tiers, most specific wins:
  1. CURATED_GENUS  — researched, standard horticultural propagation protocols
     for the major native NY edibles (pawpaw, serviceberry, hazelnut, oaks, …).
  2. FAMILY_RULE    — defensible family-level guidance (legumes, grasses, sedges,
     mints, composites, heaths).
  3. TYPE_RULE      — general fallback by growth form (tree/shrub/vine/herb/…).

Rules are general guidance meant to be refined on the Verify page. Fill-only by
default (skips rows that already have propagation text / hand edits); --force
rewrites all. Part of backfill.py; run after `apply`.

  python3 populate_propagation.py           # fill blank rows
  python3 populate_propagation.py --force    # rewrite everything
  python3 populate_propagation.py --only "Asimina triloba"
"""
import sys, argparse
sys.path.insert(0, ".")
import foodforest_import as ff

WOODY_TYPES = {"Tree", "Shrub", "Vine"}

# --- Tier 1: researched, genus-level protocols for major native NY edibles ---
CURATED_GENUS = {
 "Asimina": "Seed is recalcitrant — never let it dry out. Scoop seed from ripe fruit, wash off the pulp, and give 90–120 days of cold-moist stratification (moist sand at ~40 °F) before sowing in deep pots for the long taproot; it sprouts in warm soil the following summer. Named varieties are grafted in spring; cuttings rarely root.",
 "Amelanchier": "Collect ripe berries in early summer, mash and rinse the pulp off the tiny seeds, then fall-sow outdoors or cold-moist stratify 90–120 days. Also spreads by suckers you can dig and divide while dormant; softwood cuttings under mist in early summer give modest success.",
 "Sambucus": "Easiest from dormant hardwood cuttings — in late winter cut pencil-thick pieces 8–10 in long with 2–3 nodes and stick two-thirds deep in moist soil; they root readily. Also divides from suckers. Seed needs a warm then cold period and is slower.",
 "Vaccinium": "Take softwood cuttings in early summer or hardwood cuttings in late winter and root in moist acidic peat/sand kept humid. Seed: squeeze from ripe berries, surface-sow on moist acidic peat (needs light) after ~90 days cold stratification. Lowbush kinds spread by rhizome divisions.",
 "Rubus": "Propagate vegetatively — tip-layer arching canes in late summer (bury the growing tip until it roots), divide rooted suckers while dormant, or take root cuttings in late winter. Seed needs a warm then cold stratification and is mainly for breeding.",
 "Ribes": "Very easy from dormant hardwood cuttings — in late fall/winter take pencil-thick shoots 8–10 in long and push two-thirds into moist soil. Low branches also layer. Seed needs 3–4 months cold-moist stratification.",
 "Fragaria": "Simplest from runners: pin the plantlets down to root, then sever and transplant. Crowns also divide. Seed is tiny — clean from the ripe berry, surface-sow with light; a 3–4 week cold-moist period helps.",
 "Corylus": "Sow fresh nuts in fall in a rodent-proof bed, or cold-moist stratify 3–4 months and sow in spring; protect from squirrels. Dig and divide suckers, or layer low stems. Named cultivars are layered or grafted.",
 "Juglans": "Sow fresh nuts (husk removed) in fall 1–2 in deep in a rodent-proof bed, or cold-moist stratify 90–120 days and sow in spring. Deep taproot — direct-sow or use tall pots and move while young. Cultivars are grafted.",
 "Carya": "Sow fresh nuts in fall (rodent-proof) or cold-moist stratify 90–150 days for spring germination. Very deep taproot — direct-sow or deep pots and transplant young. Cultivars are patch- or whip-grafted in spring.",
 "Castanea": "Keep the nuts cool and moist — never let them dry. Cold-moist stratify ~60–90 days and sow in spring, or fall-sow protected from rodents. Cultivars are grafted.",
 "Quercus": "Sow acorns as soon as they drop. White-oak-group acorns germinate immediately in fall with no chilling; red-oak-group need ~30–60 days cold-moist stratification. Float-test to cull, protect from rodents, and direct-sow or use deep pots for the taproot.",
 "Prunus": "Clean the pulp off the pits and cold-moist stratify ~90–120 days (some need a warm spell first); fall-sowing outdoors works well. Suckering kinds (beach plum, chokecherry) can be dug and divided; softwood cuttings root with hormone under mist.",
 "Morus": "Roots easily from hardwood cuttings in late winter or softwood cuttings under mist in summer. Seed needs ~30–90 days cold-moist stratification. Named fruiting types are grafted or grown from cuttings.",
 "Diospyros": "Cold-moist stratify seed 60–90 days and sow in deep pots (taproot). Spreads by root suckers you can dig. Cultivars are grafted (whip/cleft in spring); cuttings are difficult.",
 "Salix": "About the easiest of all — dormant hardwood cuttings root almost anywhere; push 8–12 in pieces into moist soil in late winter/early spring. Seed is viable only days, so sow fresh.",
 "Vitis": "Dormant hardwood cuttings root readily — in late winter take pencil-thick canes with 3–4 buds, callus, and stick in moist soil. Low canes also layer. Seed needs ~90 days cold stratification and is for breeding.",
 "Asclepias": "Cold-moist stratify seed 30–60 days (or fall-sow) and surface-sow with light. Taprooted species resent transplanting, so sow in place or in deep pots. Some spread by rhizomes you can divide.",
 "Allium": "Slow from seed — a warm then long cold period, often germinating the second spring; sow fresh in fall. Faster by dividing bulb offsets/clumps or planting bulbils while dormant. Ramps: lift and divide bulbs in early spring and replant at once.",
 "Helianthus": "Tuberous kinds (sunchoke): replant tubers or tuber pieces, each with an eye, in spring — they spread fast. Clumping perennials divide in spring or fall. Seed needs light and ~30 days cold stratification.",
 "Apios": "Plant the small tubers or tuber-bearing rhizome pieces in spring; strings of tubers run along the roots. Seed is slow, needing scarification plus cold stratification.",
 "Matteuccia": "Divide the crown/rhizome in spring, keeping a growing tip and roots — the reliable method, and it spreads by runners. Or sow ripe spores on sterile moist mix kept humid and shaded (slow, months).",
 "Viburnum": "Seed is doubly dormant — a warm period (~2–3 months) then cold (~2–3 months), often germinating the second year. Faster from softwood cuttings under mist in early summer, or by layering.",
 "Aronia": "Divides easily from suckers; softwood cuttings root well under mist in early summer. Seed needs ~90 days cold-moist stratification.",
 "Lindera": "Cold-moist stratify the cleaned seed ~90 days and sow; keep seed moist (short-lived). Layering and summer softwood cuttings give modest results. Dioecious — grow several for berries.",
 "Sassafras": "Spreads readily by root suckers — dig and transplant while dormant (easiest). Seed needs ~90–120 days cold-moist stratification after cleaning off the pulp; root cuttings also work. Dioecious.",
 "Gaultheria": "Divide the creeping rhizome in spring, or take semi-ripe cuttings, rooting in moist acidic mix. Seed is tiny — surface-sow on moist peat with light.",
 "Acer": "Sow seed fresh — sugar and red maple need ~90 days cold-moist stratification, while silver maple germinates at once without chilling. Named forms are grafted.",
 "Rhus": "Spreads aggressively by root suckers — dig and transplant while dormant (easiest). Seed has a hard coat plus dormancy: scarify (hot-water or acid soak) then cold-stratify. Root cuttings work well.",
 "Typha": "Divide the rhizome in spring/summer, replanting pieces with a shoot into wet soil or shallow water. Seed germinates readily on warm wet mud in the light.",
 "Crataegus": "Seed is deeply dormant — a warm then cold stratification, often germinating the second year; fall-sow cleaned seed outdoors. Cultivars are grafted.",
 "Cornus": "Take softwood cuttings in early summer under mist, or layer low branches; shrubby dogwoods also root from hardwood cuttings. Seed needs a warm then cold stratification (double dormancy in many).",
 # actinorhizal (non-legume) nitrogen-fixers
 "Alnus": "Surface-sow the tiny seed on moist soil (needs light) after ~1 month cold stratification; keep it wet. Softwood cuttings and layering work. Actinorhizal nitrogen-fixer.",
 "Comptonia": "Tricky from seed (double dormancy) — easiest from root cuttings taken in late winter, or by digging rooted suckers. Actinorhizal nitrogen-fixer.",
 "Morella": "Cold-moist stratify seed ~90 days after rubbing off the waxy coat (or a brief warm-water soak). Layering and semi-ripe cuttings work. Dioecious; actinorhizal.",
 "Myrica": "Cold-moist stratify seed ~90 days after removing the waxy coat. Layering and semi-ripe cuttings work. Dioecious; actinorhizal nitrogen-fixer.",
 "Shepherdia": "Warm then cold stratify the seed and scarify the hard coat. Suckers and softwood cuttings work. Dioecious; actinorhizal nitrogen-fixer.",
}

# --- Tier 2: family-level rules ---
FAMILY_RULE = {
 "Fabaceae": "Legume — scarify the hard-coated seed (nick it or give a 10-minute hot-water soak) to break dormancy, and dust with a rhizobia inoculant for good nodulation, then sow. Woody legumes can also be grown from root cuttings or dug suckers.",
 "Poaceae": "Divide the clump in spring (reliable), or collect ripe seed and sow fresh; many natives need a cold-moist period, so fall-sowing works. Sow warm-season grasses in late spring.",
 "Cyperaceae": "Divide the clump in spring — the dependable method. Or surface-sow fresh seed on constantly moist soil with light; most sedges need cold-moist stratification and to stay wet.",
 "Lamiaceae": "Very easy — soft stem cuttings root in water or moist soil, and clumps divide readily in spring or fall. Seed is small; surface-sow with light.",
 "Asteraceae": "Gather the dry seed heads once fluffy and sow; many need light plus ~30 days cold-moist stratification (fall-sowing works). Clumping perennials divide in spring or fall, and some take basal cuttings.",
 "Ericaceae": "Acid-lover — surface-sow the fine seed on moist peat with light after ~1–3 months cold stratification. Softwood or semi-ripe cuttings root in an acidic mix; low shrubs layer where stems touch the ground.",
}

# --- Tier 3: growth-form fallback ---
def type_rule(typ, lifecycle):
    if typ in ("Tree", "Shrub"):
        return ("Most woody plants grow from seed given cold-moist stratification — clean the fruit off, then ~1–3 months at ~40 °F (fall-sowing outdoors mimics this) — or vegetatively from dormant hardwood cuttings in late winter or softwood cuttings under mist in early summer. Suckering kinds can be dug and divided; named selections are grafted.")
    if typ == "Vine":
        return ("Grow from cuttings (hardwood in late winter or softwood in summer) or by layering a stem to the ground until it roots. Seed usually needs cold-moist stratification.")
    if typ == "Fern":
        return ("Divide the rhizome or crown in spring, keeping roots and a growing tip. Or sow ripe spores on a sterile moist mix kept humid and shaded — slow, through the gametophyte stage.")
    if typ == "Grass":
        return FAMILY_RULE["Poaceae"]
    if typ == "Groundcover":
        return ("Spreads on its own — divide rooted clumps or runners, or take stem cuttings of the trailing shoots. Seed often needs light and a cold-moist period.")
    # Herb (and anything else)
    if (lifecycle or "") == "Annual":
        return ("Grow from seed each year — direct-sow after frost or start indoors, and let some plants self-seed to return. A short cold-moist period helps many native species germinate.")
    if (lifecycle or "") == "Biennial":
        return ("Sow seed (a cold-moist period helps); it makes a rosette the first year and flowers/seeds the second. Let it self-seed, or sow a fresh batch yearly for continuity.")
    return ("Divide the crown in spring or fall (quickest), or sow seed — many perennials need a cold-moist period, so fall-sow or stratify ~30–60 days. Some take basal cuttings.")

def propagation_for(sci, family, typ, lifecycle):
    genus = (sci or "").split(" ")[0]
    if genus in CURATED_GENUS:
        return CURATED_GENUS[genus]
    if family in FAMILY_RULE:
        return FAMILY_RULE[family]
    return type_rule(typ, lifecycle)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=None, help="single scientific name")
    a = ap.parse_args()
    env = ff.load_env()
    rows = []; _off = 0   # paginate past PostgREST's 1000-row cap
    while True:
        _pg = ff.supabase_request(env, "GET",
            "plants?select=id,sci,family,type,lifecycle,propagation&order=id&limit=1000&offset=%d" % _off) or []
        rows += _pg
        if len(_pg) < 1000: break
        _off += 1000
    from collections import Counter
    tier = Counter()
    n = 0
    for r in rows:
        if a.only and r["sci"] != a.only:
            continue
        if not a.force and (r.get("propagation") or "").strip():
            continue
        genus = (r["sci"] or "").split(" ")[0]
        t = "curated" if genus in CURATED_GENUS else ("family" if r.get("family") in FAMILY_RULE else "type")
        text = propagation_for(r["sci"], r.get("family"), r["type"], r.get("lifecycle"))
        ff.supabase_request(env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"propagation": text}, extra_headers={"Prefer": "return=minimal"})
        tier[t] += 1
        n += 1
    print("filled propagation for %d plants" % n)
    print("by tier:", dict(tier))

if __name__ == "__main__":
    main()
