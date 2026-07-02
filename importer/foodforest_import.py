#!/usr/bin/env python3
"""
Food Forest importer — populate the `plants` table from web sources.

Pure standard-library (no pip installs). Works on the system Python 3.9.

Pipeline (free "Route A" — you approve every plant):

    1. fetch    Look up each target plant on GBIF (canonical name + family) and
                Wikipedia (reference text), then write a "research packet"
                (Markdown) into  packets/  for each plant.

    2. (you)    Paste a packet into your Claude chat. Claude replies with a
                single JSON object matching the schema. Save it as
                drafts/<slug>.json  (Claude can do this for you directly).

    3. validate Check every drafts/*.json against the schema and the app's
                controlled vocab (state codes, regions, evidence tiers, ...).

    4. apply    Upsert the validated drafts into Supabase (on conflict `sci`,
                so re-runs update instead of duplicating). Use --dry-run first.

Usage:
    python3 foodforest_import.py fetch "Common Pawpaw" "Asimina triloba"
    python3 foodforest_import.py fetch --file targets.txt
    python3 foodforest_import.py list-remote
    python3 foodforest_import.py validate
    python3 foodforest_import.py apply --dry-run
    python3 foodforest_import.py apply
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKETS_DIR = HERE / "packets"
DRAFTS_DIR = HERE / "drafts"

# ── App-derived reference data (kept in sync with index.html) ──────────────
REGION = {
    "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "DE", "MD", "DC"],
    "Southeast": ["VA", "WV", "NC", "SC", "GA", "FL", "AL", "MS", "TN", "KY", "AR", "LA"],
    "Midwest": ["OH", "IN", "IL", "MI", "WI", "MN", "IA", "MO"],
    "Great Plains": ["ND", "SD", "NE", "KS", "OK", "TX"],
    "Mountain/Southwest": ["MT", "WY", "CO", "NM", "ID", "UT", "AZ", "NV"],
    "Pacific": ["WA", "OR", "CA", "AK", "HI"],
}
REGION_THRESHOLD = 0.5  # flag a region when the plant covers >= this share of its states


def derive_regions(states):
    """native_regions is derived from native_states: a region is flagged when the
    plant is native to at least REGION_THRESHOLD of that region's states."""
    s = set(states or [])
    return [name for name, rs in REGION.items()
            if rs and len(s & set(rs)) / len(rs) >= REGION_THRESHOLD]
STATES = sorted({s for g in REGION.values() for s in g})
REGIONS = list(REGION.keys())
TIERS = {"P": "peer-reviewed", "E": "ethnobotanical", "A": "anecdotal", "N": "no evidence"}
SCORE_KEYS = ["raw", "cooked", "life", "eco", "fiber", "med"]
TYPES = ["Tree", "Shrub", "Herb", "Vine", "Fern", "Grass", "Groundcover"]

# All columns we write to `plants` (snake_case, matching the table).
COLUMNS = [
    "common", "sci", "family", "type", "life", "edible_parts", "other_uses",
    "prep", "harvest", "sun", "soil", "risks", "buy", "native_states",
    "native_regions", "native_to_us", "invasive_states", "invasive_everywhere",
    "dec_priority", "nf", "pol", "scores", "sources",
    "hardiness_zones", "deer_resistant",
]


# ── tiny .env loader (no python-dotenv dependency) ─────────────────────────
def load_env():
    env = {}
    envfile = HERE / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    # real environment overrides the file
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def slugify(sci):
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "food-forest-importer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── web sources (best-effort; failures degrade gracefully) ─────────────────
def gbif_match(name):
    """Resolve to a canonical scientific name + family via GBIF (free, no key)."""
    try:
        url = "https://api.gbif.org/v1/species/match?name=" + urllib.parse.quote(name)
        d = http_get_json(url)
        if d.get("matchType") in (None, "NONE"):
            return {}
        return {
            "canonical": d.get("canonicalName") or d.get("scientificName"),
            "family": d.get("family"),
            "genus": d.get("genus"),
            "rank": d.get("rank"),
            "confidence": d.get("confidence"),
            "matchType": d.get("matchType"),
        }
    except Exception as e:
        return {"error": str(e)}


def wikipedia_summary(title):
    """Fetch a plain-text summary from Wikipedia's REST API (free, no key)."""
    try:
        url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
               + urllib.parse.quote(title.replace(" ", "_")))
        d = http_get_json(url)
        return {
            "title": d.get("title"),
            "extract": d.get("extract"),
            "url": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
        }
    except Exception as e:
        return {"error": str(e)}


# ── supabase (PostgREST) ───────────────────────────────────────────────────
def supabase_request(env, method, path, body=None, extra_headers=None):
    base = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        sys.exit("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing from importer/.env")
    url = base + "/rest/v1/" + path.lstrip("/")
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit("Supabase error %s: %s" % (e.code, e.read().decode("utf-8")))


def fetch_existing(env):
    rows = supabase_request(env, "GET", "plants?select=common,sci") or []
    return {r["sci"] for r in rows}, rows


# ── packet builder ─────────────────────────────────────────────────────────
RUBRIC = """\
Score each category 0-10, paired with an evidence tier:
  P = peer-reviewed   E = ethnobotanical   A = anecdotal   N = no evidence

  raw    Edibility RAW:     10 excellent & safe, 7 good, 4 marginal, 1 poor/unsafe, 0 toxic raw
  cooked Edibility COOKED:  10 excellent staple, 7 reliable, 4 secondary, 1 rare, 0 none
  life   Lifecycle:         10 long-lived woody perennial, 8 hardy herb. perennial,
                            5 short-lived/self-seeder, 2 biennial, 0 annual
  eco    Ecology:           10 keystone (e.g. monarch host), 8 strong pollinator/N-fixer,
                            5 moderate, 2 limited, 0 none/negative
  fiber  Fiber/Material:    10 premium (rot-resistant timber), 7 solid, 4 minor, 1 negligible, 0 none
  med    Medicinal:         10 peer-reviewed, 7 traditional+some science, 4 folk, 1 anecdotal, 0 none

Nativity is NOT scored here — the app computes it from native_states/native_regions.
Set evidence tiers conservatively: only use P when real studies exist.
"""


def build_packet(common, sci, gbif, wiki, existing_names):
    resolved_sci = gbif.get("canonical") or sci
    family = gbif.get("family") or ""
    wiki_extract = wiki.get("extract") or "(no Wikipedia summary found — use your knowledge)"
    wiki_url = wiki.get("url") or ""

    schema_example = {
        "common": common,
        "sci": resolved_sci,
        "family": family,
        "type": "Tree | Shrub | Herb | Vine | Fern | Grass | Groundcover",
        "life": "e.g. Perennial / Woody perennial / Annual",
        "edible_parts": "", "other_uses": "", "prep": "", "harvest": "",
        "sun": "", "soil": "", "risks": "", "buy": "",
        "native_states": ["2-letter codes from the list below"],
        "native_regions": ["subset of Eastern/Central/Western"],
        "native_to_us": True,
        "invasive_states": [], "invasive_everywhere": False, "dec_priority": False,
        "nf": False, "pol": False,
        "scores": {k: [0, "N"] for k in SCORE_KEYS},
        "sources": [["Wikipedia", wiki_url or "https://en.wikipedia.org/..."]],
    }

    return f"""# RESEARCH PACKET — {common}

You are drafting one row for a native-plant food-forest database. Using the
reference material below **plus your own botanical knowledge**, reply with a
SINGLE JSON object (no prose, no code fence) matching the schema exactly.

## Target
- Common name (as entered): {common}
- Scientific name (GBIF canonical): {resolved_sci}
- Family (GBIF): {family or "unknown — infer"}
- GBIF match: {gbif.get("matchType")} (confidence {gbif.get("confidence")})

## Wikipedia summary
{wiki_extract}

Source: {wiki_url}

## Scoring rubric
{RUBRIC}

## Controlled vocabulary
- type: one of {TYPES}
- state codes (native_states / invasive_states): {STATES}
- regions: {REGIONS}
  Region membership: Eastern={REGION['Eastern']}
                     Central={REGION['Central']}
                     Western={REGION['Western']}
- native_regions is AUTO-DERIVED from native_states on import (a region is
  flagged when the plant covers >=50% of that region's states), so focus on
  getting native_states right and don't hand-tune native_regions.
- evidence tiers: {list(TIERS.keys())}

## Already in the database (do NOT duplicate; pick a genuinely new species)
{", ".join(sorted(existing_names)) if existing_names else "(none)"}

## Output schema (fill every field; arrays may be empty)
```json
{json.dumps(schema_example, indent=2)}
```

Reply with ONLY the completed JSON object.
Save it as:  drafts/{slugify(resolved_sci)}.json
"""


# ── commands ───────────────────────────────────────────────────────────────
def cmd_fetch(args, env):
    PACKETS_DIR.mkdir(exist_ok=True)
    DRAFTS_DIR.mkdir(exist_ok=True)

    targets = []
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # "Common Name | Scientific name"  OR  just a name
            if "|" in line:
                c, s = [x.strip() for x in line.split("|", 1)]
            else:
                c, s = line, line
            targets.append((c, s))
    else:
        # positional: [common] [sci]  (if one arg, used for both)
        if not args.names:
            sys.exit("Give a name, two names (common sci), or --file targets.txt")
        if len(args.names) == 1:
            targets = [(args.names[0], args.names[0])]
        else:
            targets = [(args.names[0], " ".join(args.names[1:]))]

    existing_names, _ = ({}, None)
    try:
        existing_set, _ = fetch_existing(env)
        existing_names = existing_set
    except SystemExit:
        print("  (couldn't reach Supabase for the dedupe list — continuing without it)")

    for common, sci in targets:
        print(f"→ {common}  ({sci})")
        gbif = gbif_match(sci if sci != common else common)
        resolved = gbif.get("canonical") or sci
        wiki = wikipedia_summary(resolved)
        if gbif.get("error"):
            print(f"    GBIF: {gbif['error']}")
        else:
            print(f"    GBIF: {resolved}  family={gbif.get('family')}  "
                  f"match={gbif.get('matchType')}")
        if wiki.get("error"):
            print(f"    Wikipedia: {wiki['error']}")
        elif not wiki.get("extract"):
            print("    Wikipedia: no summary found")
        if resolved in existing_names:
            print("    ⚠ already in the database — skipping packet")
            continue
        packet = build_packet(common, sci, gbif, wiki, existing_names)
        out = PACKETS_DIR / (slugify(resolved) + ".md")
        out.write_text(packet)
        print(f"    ✓ packet → {out.relative_to(HERE)}")

    print("\nNext: paste a packet from packets/ into your Claude chat, "
          "save the JSON reply into drafts/, then run:  validate  then  apply --dry-run")


def validate_draft(obj):
    errs = []
    for req in ("common", "sci"):
        if not obj.get(req):
            errs.append(f"missing required field: {req}")
    if obj.get("type") and obj["type"] not in TYPES:
        errs.append(f"type '{obj['type']}' not in {TYPES}")
    for field in ("native_states", "invasive_states"):
        for st in obj.get(field, []) or []:
            if st not in STATES:
                errs.append(f"{field}: '{st}' is not a valid state code")
    for rg in obj.get("native_regions", []) or []:
        if rg not in REGIONS:
            errs.append(f"native_regions: '{rg}' not in {REGIONS}")
    scores = obj.get("scores", {})
    for k in SCORE_KEYS:
        if k not in scores:
            errs.append(f"scores missing key: {k}")
            continue
        pair = scores[k]
        if (not isinstance(pair, list) or len(pair) != 2
                or not isinstance(pair[0], int) or not (0 <= pair[0] <= 10)
                or pair[1] not in TIERS):
            errs.append(f"scores.{k} must be [0-10 int, tier in {list(TIERS)}], got {pair}")
    for src in obj.get("sources", []) or []:
        if not (isinstance(src, list) and len(src) == 2):
            errs.append(f"sources entry must be [label, url], got {src}")
    return errs


def load_drafts():
    DRAFTS_DIR.mkdir(exist_ok=True)
    out = []
    for f in sorted(DRAFTS_DIR.glob("*.json")):
        try:
            out.append((f, json.loads(f.read_text())))
        except json.JSONDecodeError as e:
            out.append((f, {"__parse_error__": str(e)}))
    return out


def cmd_validate(args, env):
    drafts = load_drafts()
    if not drafts:
        print("No drafts/*.json found yet.")
        return
    ok = 0
    for f, obj in drafts:
        if "__parse_error__" in obj:
            print(f"✗ {f.name}: invalid JSON — {obj['__parse_error__']}")
            continue
        errs = validate_draft(obj)
        if errs:
            print(f"✗ {f.name}:")
            for e in errs:
                print(f"    - {e}")
        else:
            print(f"✓ {f.name}: {obj.get('common')} ({obj.get('sci')})")
            ok += 1
    print(f"\n{ok}/{len(drafts)} drafts valid.")


def clean_row(obj):
    """Keep only known columns; fill sensible defaults."""
    row = {}
    for c in COLUMNS:
        if c in obj:
            row[c] = obj[c]
    row.setdefault("native_states", [])
    # native_regions is always derived from native_states for consistency
    row["native_regions"] = derive_regions(row.get("native_states", []))
    row.setdefault("invasive_states", [])
    row.setdefault("sources", [])
    for b in ("native_to_us", "invasive_everywhere", "dec_priority", "nf", "pol",
              "deer_resistant"):
        row.setdefault(b, False)
    return row


def cmd_apply(args, env):
    drafts = load_drafts()
    valid = []
    for f, obj in drafts:
        if "__parse_error__" in obj:
            print(f"skip {f.name}: invalid JSON")
            continue
        errs = validate_draft(obj)
        if errs:
            print(f"skip {f.name}: {len(errs)} validation error(s) — run validate")
            continue
        valid.append(clean_row(obj))

    if not valid:
        print("Nothing valid to apply.")
        return

    print(f"{len(valid)} row(s) ready:")
    for r in valid:
        print(f"  · {r['common']} ({r['sci']})")

    if args.dry_run:
        print("\n--dry-run: nothing written. Re-run without --dry-run to upsert.")
        return

    res = supabase_request(
        env, "POST", "plants?on_conflict=sci", body=valid,
        extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    print(f"\n✓ Upserted {len(res or [])} row(s) into plants (on conflict sci).")


def cmd_list_remote(args, env):
    existing, rows = fetch_existing(env)
    for r in sorted(rows, key=lambda x: x["sci"]):
        print(f"  {r['sci']:<32} {r['common']}")
    print(f"\n{len(existing)} plants currently in the database.")


def main():
    p = argparse.ArgumentParser(description="Food Forest importer")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="build research packets from web sources")
    pf.add_argument("names", nargs="*", help='"Common Name" "Scientific name"')
    pf.add_argument("--file", help="targets file (one plant per line: Common | Sci)")

    sub.add_parser("validate", help="check drafts/*.json against the schema")

    pa = sub.add_parser("apply", help="upsert validated drafts into Supabase")
    pa.add_argument("--dry-run", action="store_true", help="show what would happen")

    sub.add_parser("list-remote", help="list plants already in the database")

    args = p.parse_args()
    env = load_env()
    {"fetch": cmd_fetch, "validate": cmd_validate,
     "apply": cmd_apply, "list-remote": cmd_list_remote}[args.cmd](args, env)


if __name__ == "__main__":
    main()
