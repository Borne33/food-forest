# Food Forest importer

Populate the Supabase `plants` table from web sources, with you approving every
plant before it goes live. Pure Python 3 standard library — **no installs**.

## One-time setup

1. Copy the env template and fill in your secret key:
   ```bash
   cd ~/food-forest/importer
   cp .env.example .env        # .env is gitignored — never commit it
   ```
   Set `SUPABASE_SERVICE_ROLE_KEY` (Supabase Dashboard ▸ Project Settings ▸ API
   ▸ `service_role`). Leave the LLM keys blank to use the free "Route A" below.

## The workflow (Route A — free, you approve each plant)

```
 fetch  ──▶  packets/*.md  ──▶  (paste into Claude)  ──▶  drafts/*.json  ──▶  validate  ──▶  apply
```

1. **Fetch** — look up plants on GBIF (canonical name + family) and Wikipedia
   (reference text), producing a research packet per plant:
   ```bash
   python3 foodforest_import.py fetch "Beach Plum" "Prunus maritima"
   # or a batch:
   cp targets.example.txt targets.txt   # edit it
   python3 foodforest_import.py fetch --file targets.txt
   ```

2. **Draft** — open a packet from `packets/`, paste it into a Claude chat.
   Claude replies with one JSON object. Save it as `drafts/<slug>.json`
   (the packet tells you the exact filename).

3. **Validate** — check every draft against the schema and the app's controlled
   vocab (state codes, regions, evidence tiers, score ranges):
   ```bash
   python3 foodforest_import.py validate
   ```

4. **Apply** — upsert the valid drafts into Supabase. Dry-run first:
   ```bash
   python3 foodforest_import.py apply --dry-run
   python3 foodforest_import.py apply
   ```
   Upserts are keyed on `sci` (unique constraint), so re-running **updates**
   an existing plant instead of creating a duplicate.

Utility: `python3 foodforest_import.py list-remote` prints what's already in the
database.

## What is auto-filled vs. drafted

- **From authoritative APIs (deterministic):** canonical scientific name and
  `family` (GBIF); reference text (Wikipedia).
- **Derived automatically on import:** `native_regions` is computed from
  `native_states` (a region is flagged when the plant covers >=50% of that
  region's states — see `REGION` / `derive_regions` in the CLI), so you never
  hand-tune it. Get `native_states` right and regions follow.
- **Drafted with judgment, then reviewed by you:** `type`, `life`, the prose
  fields, `native_states`, `nf`/`pol`, the 6-category `scores`
  (`raw, cooked, life, eco, materials, med`) with evidence tiers, and `sources`.
- **Backfilled by rule after import, then optionally corrected by USDA:**
  `hardiness_zones` + `deer_resistant` (`populate_traits.py`), `soil_n/p/k`
  (`populate_soil.py`), `soil_texture` + `soil_drainage` (`populate_soildims.py`),
  and fruit traits (`populate_fruit.py`). See the USDA pass below.

Nativity is **not** stored as a score — the app computes it live from
`native_states` / `native_regions` for the user's selected state.

### "No Data Found" convention (important for lesser-known plants)

When no reliable information exists for a field, **leave it empty** — the app
shows **"No Data Found"** for empty prose fields in the expanded card. For the
six **category scores**, no data means a **score of 0** with evidence tier `N`
(no evidence): `[0, "N"]`. Do not invent a value to fill a gap; an honest 0 /
"No Data Found" is correct and will get more common as we add obscure species.

## USDA PLANTS cross-check / enrichment (`usda_enrich.py`)

USDA PLANTS is US-federal **public-domain** data with an open JSON API
(`plantsservices.sc.egov.usda.gov/api`). This pass resolves each plant to its
USDA symbol and replaces the *rule-based estimates* with USDA's authoritative
values **where USDA has data**:

- `nf` ← "Nitrogen Fixation" (None → false, Low/Medium/High → true)
- `soil_texture` ← "Adapted to Coarse/Medium/Fine Textured Soils"
  (Coarse→Sandy, Medium→Loam+Silt, Fine→Clay)
- `soil_drainage` ← Moisture Use / Anaerobic Tolerance / Drought Tolerance
- `native_north_america` ← set true when USDA says native to Canada but not the US
- appends a `USDA PLANTS` source link

It **flags** `native_to_us` disagreements (report only, never auto-changed) and
deliberately **skips `sun`** — USDA "Shade Tolerance" is unreliable (deep-shade
ferns read "Low", full-sun forbs "High"). Runs **dry-run by default**:

```bash
python3 usda_enrich.py               # dry-run over all plants -> JSON report
python3 usda_enrich.py --limit 20    # dry-run, first 20
python3 usda_enrich.py --only "Asclepias tuberosa"
python3 usda_enrich.py --apply       # write changes to DB + sync drafts
```

**Run this LAST** — `soil_texture`/`soil_drainage` live only in the DB, so
re-running `populate_soildims.py` afterward would overwrite USDA's values.

## Fully-automated drafting (optional)

Route A keeps you in the loop for free. If you later want hands-off drafting,
put a `GEMINI_API_KEY` (free tier) or `ANTHROPIC_API_KEY` (paid) in `.env`; the
LLM call step can then be wired to draft the JSON directly. (Not enabled by
default — quality is best when you review each plant.)

## Files

| Path                    | Purpose                                            |
|-------------------------|----------------------------------------------------|
| `foodforest_import.py`  | The CLI (fetch / validate / apply / list-remote).  |
| `fetch_images.py`       | Populate `plants.images` + photo sources from Wikimedia Commons (`python3 fetch_images.py`; `--force` to refetch, `--limit N` to test). Picks up to 3 photos per plant (lead + edible-part captions), skipping range maps / status icons; adds each photo's Commons page to `sources`. |
| `fetch_images_fallback.py` | For plants Wikipedia has no article for: retries the base binomial, then searches Wikimedia Commons' File namespace; last-resort photos come from iNaturalist. |
| `usda_enrich.py`        | USDA PLANTS cross-check/enrichment (see section above). Dry-run by default; `--apply` to write. |
| `populate_traits.py` / `populate_soil.py` / `populate_soildims.py` / `populate_fruit.py` | Rule-based backfills (hardiness + deer; soil N/P/K; soil texture/drainage; fruit traits). Run after `apply`; USDA pass runs after these. |
| `.env`                  | Your secrets (gitignored).                         |
| `.env.example`          | Template.                                          |
| `targets.example.txt`   | Example batch input.                               |
| `drafts/*.json`         | Reviewed plant rows — the curated, versioned source. |
| `packets/*.md`          | Regenerable research packets (gitignored).         |
