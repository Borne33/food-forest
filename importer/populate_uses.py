#!/usr/bin/env python3
"""Classify each plant into structured food_types / material_types / lifecycle,
and re-split its `other_uses` prose into eco_uses vs material_uses. Rule-based
(keyword) — a first pass, correctable on the Verify page. Fills only empty rows
by default (skips plants already classified / hand-edited); --force redoes all.

Run after `apply` (part of backfill.py). Usage:
  python3 populate_uses.py            # fill unclassified plants
  python3 populate_uses.py --force    # reclassify everything
"""
import sys, re, argparse
sys.path.insert(0, ".")
import foodforest_import as ff

FOOD_TYPES=["Fruit","Nut/Seed","Grain","Leafy Green","Vegetable","Root/Tuber/Bulb","Herb/Spice","Tea/Drink","Flower","Sap/Syrup"]
MATERIAL_TYPES=["Timber/Wood","Fiber/Cordage","Basketry/Weaving","Dye","Soap/Saponin","Wax/Resin/Gum","Fuelwood","Other"]
LIFECYCLES=["Annual","Biennial","Short-Lived Perennial","Long-Lived Perennial"]

FOOD_KW={
 "Fruit":["fruit","berry","berries","haw","hips","drupe","pome"," plum","cherry","cherries","grape","apple","crabapple","tuna","fig ","persimmon","mulberr","pawpaw","currant","gooseberr","blueberr","cranberr","huckleberr","elderberr","raspberr","blackberr","dewberr","strawberr","serviceberr","juneberr","maypop","pitaya","bilberr","farkleberr","dangleberr"],
 "Nut/Seed":["nut","acorn","kernel","hazelnut","walnut","pecan","hickory","chestnut","beechnut","chinquapin","pine nut","piñon","pinyon","oily seed","seeds ("],
 "Grain":["grain","wild rice","pinole","flour","meal (","ground into meal","seed grain","cereal"],
 "Leafy Green":["leaves","leaf ","greens","salad","potherb","spinach","lettuce","cress","sorrel","cooked green","nopales"],
 "Vegetable":["shoot","stem","stalk","pod","nopal","pad","fiddlehead","heart (","bud","sprout","asparagus","scape","cladode","peeled"],
 "Root/Tuber/Bulb":["root","tuber","rhizome","corm","bulb","taproot","wapato","chufa","biscuitroot"],
 "Herb/Spice":["spice","seasoning","flavoring","condiment","peppercorn","aromatic seasoning","bay-leaf","bay leaf","szechuan","juniper spice","oregano"],
 "Tea/Drink":["tea","drink","beverage","cider","lemonade","root beer","root-beer","coffee","wine","infusion","sumac-ade","cordial","horchata","spruce beer","birch beer"],
 "Flower":["flower","blossom","petal"],
 "Sap/Syrup":["sap","maple syrup","birch syrup","tree syrup"],  # not bare 'syrup' (fruit syrup)
}
MAT_KW={
 "Timber/Wood":["timber","lumber","hardwood","rot-resistant wood","tool handle","tool handles","fence-post","posts","shingle","carv","boat","pencil","bat","plank","the wood","its wood","light wood","hard wood","durable wood","cedar-chest","musclewood","ironwood","tools"],
 "Fiber/Cordage":["fiber","fibre","cordage","cord ","rope","twine","string","sandals","netting"],
 "Basketry/Weaving":["basket","weav","splint","wicker","withe","matting"," mat "],
 "Dye":["dye"],
 "Soap/Saponin":["soap","saponin","amole","lather"],
 "Wax/Resin/Gum":["resin","gum ","gum (","gum.","gum,","balsam","chewing gum","latex","storax","candle","beeswax","wax"],
 "Fuelwood":["fuelwood","firewood","grilling","charcoal","kindling"],
}
OTHER_MAT_KW=[" ink","glue","tannin"," brush","beads","smoking","kinnikinnick","fishing float","abrasive","scour ","gruit","lycopodium powder","flash powder"]
def _prep(t): return (t or "").lower().replace("waxy","")  # 'waxy bloom' isn't a wax use
ECO_SENT_KW=["nitrogen","n-fix","actinorhizal","pollinator","bee","butterfl","moth","bird","wildlife","host","nectar","habitat","cover","erosion","streambank","stream bank","stabiliz","soil builder","hedgerow","forage","waterfowl","monarch","larval","songbird","browse","game","quail","grizzly","pollen","understory","restoration","windbreak","screening","shelter","swallowtail","checkerspot","fritillary","hummingbird","carbon"]

def sents(t): return [s.strip() for s in re.split(r"[.;]", t or "") if s.strip()]
def has(text, kws): return any(k in text for k in kws)

DOCUMENTED_SHORT={"Aquilegia canadensis","Silene virginica","Silene caroliniana","Lobelia cardinalis",
 "Lobelia siphilitica","Rudbeckia hirta","Verbena hastata","Gaillardia pulchella","Gaillardia aristata",
 "Castilleja coccinea","Penstemon digitalis","Oenothera biennis","Grindelia lanceolata","Coreopsis tinctoria"}
WOODY_TYPES={"Tree","Shrub","Vine"}

def lifecycle_of(sci, typ, life):
    L=(life or "").lower()
    ann="annual" in L; bien="biennial" in L; short="short-lived" in L; per="perennial" in L or "woody" in L
    if ann and not per and not bien: return "Annual"
    if bien and not short and not per: return "Biennial"
    if short or (bien and per): return "Short-Lived Perennial"
    if sci in DOCUMENTED_SHORT: return "Short-Lived Perennial"
    return "Long-Lived Perennial"   # woody, and herbaceous perennials by default

MAT_ALL=sum(MAT_KW.values(),[])+OTHER_MAT_KW
def food_types_of(edible, scores):
    # from edible_parts ONLY; drop clauses naming a TOXIC / not-eaten part
    if scores["raw"][0]<=0 and scores["cooked"][0]<=0: return []
    frags=[f for f in re.split(r"[;.]", edible or "") if f.strip()
           and not any(w in f.lower() for w in ("toxic","not eaten","poison","inedible","never eat"))]
    txt=" ".join(frags).lower()
    return [t for t in FOOD_TYPES if has(txt, FOOD_KW[t])]

def material_types_of(other, prep, risks):
    txt=_prep(other)+" "+_prep(prep)+" "+_prep(risks)
    out=[t for t in MATERIAL_TYPES if t!="Other" and has(txt, MAT_KW.get(t,[]))]
    if has(txt, OTHER_MAT_KW): out.append("Other")
    return out

def split_uses(other, prep, nf, pol, eco_score):
    # material sentences come from other_uses AND prep (wood/grilling often in prep);
    # ecological/general sentences come from other_uses (skip prep to avoid cooking steps)
    matb=[s for s in sents(other)+sents(prep) if has(_prep(s), MAT_ALL)]
    ecob=[s for s in sents(other) if not has(_prep(s), MAT_ALL)]
    def joinup(xs):
        seen=[]; [seen.append(x) for x in xs if x not in seen]
        t=". ".join(seen); return (t+".") if t and not t.endswith(".") else t
    material_uses=joinup(matb); eco_uses=joinup(ecob)
    if not eco_uses.strip():   # synthesize from attributes
        bits=[]
        if nf: bits.append("fixes nitrogen to feed neighboring plants")
        if pol: bits.append("supports pollinators and provides nectar")
        if eco_score>=8: bits.append("supports abundant wildlife and habitat")
        elif eco_score>=5: bits.append("supports moderate wildlife")
        eco_uses=(", ".join(bits).capitalize()+".") if bits else ""
    return eco_uses, material_uses

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--force",action="store_true"); a=ap.parse_args()
    env=ff.load_env()
    rows=ff.supabase_request(env,"GET",
      "plants?select=id,sci,type,life,edible_parts,prep,other_uses,risks,scores,nf,pol,lifecycle&limit=2000") or []
    todo=[r for r in rows if a.force or not r.get("lifecycle")]
    n=0
    from collections import Counter
    lc=Counter()
    for r in todo:
        life_cat=lifecycle_of(r["sci"], r["type"], r["life"])
        ft=food_types_of(r["edible_parts"], r["scores"])
        mt=material_types_of(r["other_uses"], r["prep"], r["risks"])
        eco,mat=split_uses(r["other_uses"], r["prep"], r["nf"], r["pol"], r["scores"]["eco"][0])
        ff.supabase_request(env,"PATCH","plants?id=eq.%d"%r["id"],
          body={"lifecycle":life_cat,"food_types":ft,"material_types":mt,"eco_uses":eco,"material_uses":mat},
          extra_headers={"Prefer":"return=minimal"})
        lc[life_cat]+=1; n+=1
    print("classified %d plants (%d skipped as already done)"%(n, len(rows)-len(todo)))
    print("lifecycle:", dict(lc))

if __name__=="__main__":
    main()
