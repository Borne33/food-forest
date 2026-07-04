#!/usr/bin/env python3
"""USDA PLANTS cross-check / enrichment pass  (reusable — keep in the toolkit).

Public-domain data from the USDA PLANTS JSON API
(https://plantsservices.sc.egov.usda.gov/api). For each plant it:
  1. Resolves the scientific name -> USDA symbol via PlantSearch.
  2. Pulls PlantProfile (NativeStatuses) + PlantCharacteristics.
  3. ENRICHES (authoritative, replacing rule-based estimates where USDA has data):
       - nf             from "Nitrogen Fixation" (None -> false, Low/Med/High -> true)
       - soil_texture   from "Adapted to Coarse/Medium/Fine Textured Soils"
                        (Coarse->Sandy, Medium->Loam+Silt, Fine->Clay)
       - soil_drainage  from Moisture Use / Anaerobic Tolerance / Drought Tolerance
       - native_north_america  true when USDA says native to Canada but NOT the US
       - appends a "USDA PLANTS" source link
  4. FLAGS (reports only, never auto-changes): native_to_us disagreements.
  NB: `sun` is deliberately NOT enriched — USDA "Shade Tolerance" proved
      unreliable (deep-shade ferns read "Low", full-sun forbs read "High").

Writes changed draft-backed fields (nf, native_north_america, sources) back to
the matching drafts/*.json so a later `apply` stays consistent. soil_texture /
soil_drainage live only in the DB (set by populate_soildims.py) — re-running
that rule-based script will overwrite USDA values, so run this pass LAST.

Usage:
  python3 usda_enrich.py                 # dry-run over all plants -> report
  python3 usda_enrich.py --limit 20      # dry-run, first 20
  python3 usda_enrich.py --only "Asclepias tuberosa"
  python3 usda_enrich.py --apply         # write changes (DB + drafts)
"""
import sys, os, re, json, time, argparse, urllib.parse, urllib.request, urllib.error
import foodforest_import as ff

API = "https://plantsservices.sc.egov.usda.gov/api/"
UA = {"User-Agent": "food-forest-planner/1.0 (native plant education; github.com/Borne33)"}
DR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drafts")
US_REGIONS = {"L48", "AK", "HI", "PR", "VI"}


def api_get(path):
    req = urllib.request.Request(API + path, headers=UA)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1)); continue
            raise
        except Exception:
            if attempt < 3:
                time.sleep(1.5); continue
            raise
    return None


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def base_binom(sci):
    b = re.split(r"\s+(?:var\.|ssp\.|subsp\.|f\.)\s+", sci)[0]
    return " ".join(b.split()[:2])


def resolve(sci):
    """Return (symbol, id, matched_name) for an exact binomial match, else None."""
    q = base_binom(sci)
    data = api_get("PlantSearch?searchText=" + urllib.parse.quote(q))
    if not data:
        return None
    tgt = q.lower()
    exact = []
    for it in data:
        p = it.get("Plant") or {}
        nm = strip_html(p.get("ScientificName", ""))
        if " ".join(nm.split()[:2]).lower() == tgt:
            exact.append(p)
    if not exact:
        return None
    for p in exact:                       # prefer accepted names over synonyms
        if not p.get("SynonymSymbol"):
            return (p["Symbol"], p["Id"], strip_html(p["ScientificName"]))
    p = exact[0]
    return (p["Symbol"], p["Id"], strip_html(p["ScientificName"]))


def usda_native(profile):
    ns = profile.get("NativeStatuses") or []
    us_native = any(x.get("Region") in US_REGIONS and x.get("Type") == "Native" for x in ns)
    us_present = any(x.get("Region") in US_REGIONS for x in ns)
    can_native = any(x.get("Region") == "CAN" and x.get("Type") == "Native" for x in ns)
    return us_native, us_present, can_native


def char_map(cid):
    data = api_get("PlantCharacteristics/%s" % cid) or []
    return {c["PlantCharacteristicName"]: c["PlantCharacteristicValue"]
            for c in data if c.get("PlantCharacteristicValue") not in (None, "")}


def map_nf(cm):
    v = cm.get("Nitrogen Fixation")
    return None if v is None else (v in ("Low", "Medium", "High"))


def map_texture(cm):
    keys = ("Adapted to Coarse Textured Soils", "Adapted to Medium Textured Soils",
            "Adapted to Fine Textured Soils")
    if not any(k in cm for k in keys):
        return None
    tex = []
    if cm.get("Adapted to Coarse Textured Soils") == "Yes": tex.append("Sandy")
    if cm.get("Adapted to Medium Textured Soils") == "Yes": tex += ["Loam", "Silt"]
    if cm.get("Adapted to Fine Textured Soils") == "Yes": tex.append("Clay")
    return tex or None


def map_drainage(cm):
    mu, at, dt = cm.get("Moisture Use"), cm.get("Anaerobic Tolerance"), cm.get("Drought Tolerance")
    if not any([mu, at, dt]):
        return None
    dr = []
    if dt in ("Medium", "High") or mu == "Low": dr.append("Well-drained")
    if mu in ("Medium", "High"): dr.append("Moist")
    if at in ("Medium", "High"): dr.append("Wet")
    return dr or ["Moist"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--report", type=str,
                    default="/private/tmp/claude-501/-Users-alexbornemann-Library-CloudStorage-Dropbox-Claude-AI/776c5c38-2e5e-44ee-8bdb-880e097b65c8/scratchpad/usda_report.json")
    args = ap.parse_args()
    env = ff.load_env()

    rows = ff.supabase_request(env, "GET",
        "plants?select=id,sci,common,nf,soil_texture,soil_drainage,native_to_us,"
        "native_north_america,sources&order=sci&limit=2000")
    if args.only:
        rows = [r for r in rows if r["sci"].lower() == args.only.lower()]
    if args.limit:
        rows = rows[:args.limit]

    stats = {"resolved": 0, "unresolved": 0, "nf": 0, "texture": 0, "drainage": 0,
             "native_na": 0, "src": 0}
    unresolved, nf_flips, native_flags, report = [], [], [], []

    for i, r in enumerate(rows):
        res = resolve(r["sci"])
        time.sleep(0.3)
        if not res:
            stats["unresolved"] += 1
            unresolved.append(r["sci"])
            continue
        sym, cid, matched = res
        profile = api_get("PlantProfile?symbol=" + urllib.parse.quote(sym)) or {}
        time.sleep(0.3)
        cm = char_map(cid)
        time.sleep(0.3)
        stats["resolved"] += 1

        patch, notes = {}, {}
        nf_new = map_nf(cm)
        if nf_new is not None and bool(nf_new) != bool(r["nf"]):
            patch["nf"] = nf_new; notes["nf"] = [r["nf"], nf_new]; stats["nf"] += 1
            nf_flips.append((r["common"], r["sci"], r["nf"], nf_new))
        tex_new = map_texture(cm)
        if tex_new and set(tex_new) != set(r.get("soil_texture") or []):
            patch["soil_texture"] = tex_new; notes["soil_texture"] = [r.get("soil_texture"), tex_new]
            stats["texture"] += 1
        dr_new = map_drainage(cm)
        if dr_new and set(dr_new) != set(r.get("soil_drainage") or []):
            patch["soil_drainage"] = dr_new; notes["soil_drainage"] = [r.get("soil_drainage"), dr_new]
            stats["drainage"] += 1

        us_native, us_present, can_native = usda_native(profile)
        if (not us_native) and can_native and not r.get("native_north_america"):
            patch["native_north_america"] = True; notes["native_north_america"] = [False, True]
            stats["native_na"] += 1
        # flag native_to_us disagreements (report only)
        if us_present and not us_native and r.get("native_to_us"):
            native_flags.append((r["common"], r["sci"], "we=native_to_us / USDA=introduced-in-US"))
        if us_native and not r.get("native_to_us"):
            native_flags.append((r["common"], r["sci"], "we=NOT-native_to_us / USDA=native-in-US"))

        # USDA source link
        purl = "https://plants.usda.gov/plant-profile/" + sym
        srcs = r.get("sources") or []
        if not any(isinstance(s, list) and len(s) == 2 and s[1] == purl for s in srcs):
            new_srcs = srcs + [["USDA PLANTS", purl]]
            patch["sources"] = new_srcs; stats["src"] += 1
        else:
            new_srcs = srcs

        if patch:
            report.append({"sci": r["sci"], "symbol": sym, "changes": notes,
                           "added_source": "sources" in patch})
            if args.apply:
                ff.supabase_request(env, "PATCH", "plants?id=eq.%s" % r["id"],
                                    body=patch, extra_headers={"Prefer": "return=minimal"})
                # sync draft-backed fields (nf, native_north_america, sources)
                fn = os.path.join(DR, ff.slugify(r["sci"]) + ".json")
                if os.path.exists(fn):
                    d = json.load(open(fn))
                    if "nf" in patch: d["nf"] = patch["nf"]
                    if "native_north_america" in patch: d["native_north_america"] = patch["native_north_america"]
                    if "sources" in patch: d["sources"] = new_srcs
                    json.dump(d, open(fn, "w"), indent=2, ensure_ascii=False)
        if (i + 1) % 50 == 0:
            print(f"...{i+1}/{len(rows)} processed", flush=True)

    out = {"stats": stats, "unresolved": unresolved, "nf_flips": nf_flips,
           "native_to_us_flags": native_flags, "changes": report, "applied": args.apply}
    json.dump(out, open(args.report, "w"), indent=2, ensure_ascii=False)
    print("\n==== USDA enrichment %s ====" % ("APPLIED" if args.apply else "DRY-RUN"))
    print("processed:", len(rows), "| resolved:", stats["resolved"], "| unresolved:", stats["unresolved"])
    print("changes -> nf:%d  soil_texture:%d  soil_drainage:%d  native_north_america:%d  +USDA source:%d"
          % (stats["nf"], stats["texture"], stats["drainage"], stats["native_na"], stats["src"]))
    print("nf flips:", len(nf_flips), "| native_to_us flags:", len(native_flags))
    print("report ->", args.report)


if __name__ == "__main__":
    main()
