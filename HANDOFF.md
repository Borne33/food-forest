# Native Food Forest Planner — Project Handoff

A self-contained brief so a new session can make edits confidently. Last updated
Jul 2026 at **1000 plants** (batches 1–9). Read this top-to-bottom, then verify
specifics against the live code/DB before asserting them as fact.

---

## 1. What it is & where it lives

Single-page web app that lets a signed-in user browse ~1000 US-native plants
(scored for a food-forest), build one or more named **plans**, and (admin only)
human-verify/edit plant data.

- **Repo:** `https://github.com/Borne33/food-forest` (note capital B).
  **Local clone:** `/Users/alexbornemann/food-forest` — kept OUT of Dropbox on
  purpose (git + Dropbox corrupt each other). PAT is in the macOS keychain
  (osxkeychain helper); expires 2026-09-29.
- **Deploy:** GitHub Pages from `main` root → live at
  `https://borne33.github.io/food-forest/`. **Push = deploy.** (`git push origin main`.)
  A GitHub Actions workflow (`.github/workflows/deploy-pages.yml`) also deploys.
- **Backend:** Supabase project **"Native Food Forest"**, ref
  `sysrtpvnkpfuieznfkzb`, region us-east-2. (An older "Archive Native Plant
  Database" project `jvzswxnyaytacdnkaoan` exists — NOT the live one.)
- **App admin / only real auth user of note:** `alex@bornemann.us`
  (uid `631158fd-3291-4f4e-9294-cff8abc5d3f8`). This is the ONLY user who sees the
  Human Verify page and may edit plants (gated client-side by `ADMIN_EMAIL` in
  index.html + an RLS UPDATE policy on `plants`). There is a second, ordinary
  test user (`c5848b13-…`).

## 2. Tech stack & hard constraints

- **Frontend:** everything is in one file, `index.html` (~2000 lines): React 18
  UMD + Babel-standalone (in-browser JSX transform, no build step) + Supabase JS
  SDK from CDN. Styling is a big `<style>` block using CSS variables. State is
  plain React hooks (`const {useState,useMemo,useEffect} = React;`).
- **Importer:** pure-stdlib **Python 3.9** in `importer/` (the machine has **no
  Node/npm/brew**, and **no pip packages** beyond what's already installed —
  `pdfplumber` was installed ad-hoc once for PDF parsing). Talks to Supabase via
  the PostgREST REST API using the `service_role` key in gitignored
  `importer/.env`.
- **DDL / SQL** (schema changes, triggers, RLS) is run via the Supabase MCP
  (`execute_sql`) — the importer's PostgREST cannot do DDL. Every migration is
  also saved as a doc in `importer/sql/` for the record.
- **Testing caveat:** the browser-preview sandbox is scoped to the primary
  working directory and **cannot serve the `food-forest` repo**, and much of the
  app is **auth-gated + RLS** (you're not the app's signed-in user). So UI
  changes are verified statically (grep, brace-balance, careful reads) and the
  **user must sign in and click through** anything auth-gated (plans, verify).
  Say so plainly when handing off a UI change.

## 3. Database schema (`plants`, `plans`, `user_plans`)

`plants` — public SELECT (anon), admin-only UPDATE (RLS to the admin uid). Key columns:

- **Identity/prose:** `id` (int PK), `common`, `sci` (UNIQUE — upsert key),
  `family`, `type`, `life` (free-text lifecycle detail), `edible_parts`, `prep`,
  `harvest`, `other_uses` (legacy source prose), `sun`, `soil`, `risks`, `buy`.
- **Scores** `scores` (jsonb): 6 keys `raw, cooked, life, eco, materials, med`,
  each `[value 0-10 int, evidence_tier]`; tiers `P`=peer-reviewed, `E`=ethno­botanical,
  `A`=anecdotal, `N`=no evidence. **Nativity is NOT in scores** — computed live.
  (The `materials` key was `fiber` before Jul 2026; renamed everywhere incl. DB.)
- **Nativity:** `native_states` text[] (USPS codes), `native_regions` text[]
  (subset of the 6 regions; **auto-derived** from native_states — see below),
  `native_to_us`, `native_north_america`, `native_americas`,
  `invasive_states` text[], `invasive_everywhere`, `dec_priority` (NY DEC list).
- **Traits (rule-backfilled):** `hardiness_zones` (text, over-wide — do NOT cap),
  `deer_resistant`, `nf` (N-fixer), `pol` (pollinator), `min_plants_fruit`,
  `years_to_fruit`, `soil_ph`, `soil_n/p/k` (Low/Moderate/High),
  `soil_texture` text[] (Sandy/Loam/Clay/Silt), `soil_drainage` text[]
  (Well-drained/Moist/Wet).
- **Structured use taxonomy (Jul 2026, DB-only, from populate_uses.py):**
  `food_types` text[], `material_types` text[], `lifecycle` text (one of 4),
  `eco_uses` text, `material_uses` text (the old `other_uses` re-split into
  ecological vs material).
- **Media/meta:** `images` jsonb (`[{url,title,source}]`, Wikimedia thumbs +
  iNat/Commons fallback), `sources` jsonb (`[[label,url]]`), `human_verified`
  bool, `created_at`, `batch` int (see below).

`plants.batch` — plants numbered by add-time: a `>30-min` gap in `created_at`
starts a new batch. Historical rows numbered 1–9 by a window query; a
**`BEFORE INSERT` trigger `trg_set_plant_batch`** auto-numbers future inserts.
Surfaces as the Database "Added batch" filter.

**Multi-plan tables (per user, RLS-scoped by `auth.uid()`):**
- `plans` (id uuid, `user_id` default auth.uid(), `name`, `color`, created_at).
- `user_plans` (id, user_id, `plant_id`→plants, `plan_id`→plans, created_at),
  UNIQUE `(plan_id, plant_id)` — a plant can be in several plans, once per plan.
  RLS: read/insert/delete own; insert also requires the plan to belong to the user.

SQL for all of the above lives in `importer/sql/*.sql`
(`batch_tracking.sql`, `multi_plans.sql`, `uses_taxonomy.sql`).

## 4. Scoring model (computed in-app)

`Overall = Nativity×4 + Raw×2 + Cooked×2 + Lifecycle×1 + Ecology×1 +
Materials×0.7 + Medicinal×0.3` (range ≈ −20 to 110), colored into bands.
**Nativity** (computed live for the user's selected state): 10 in-state, 8
in-region, 5 native-to-US, **4 native-to-North-America (Canada/Mexico), 3
native-to-Americas**, 0 non-native, −5 invasive. Raw/cooked "good, well-documented"
tier = **9** (was 7). See `WEIGHTS`, `nativity()`, `overall()`, and `GUIDE` in index.html.

## 5. Controlled vocabularies (mirrored in JS + Python — keep in sync)

- **type** (7): Tree, Shrub, Herb, Vine, Fern, Grass, Groundcover. (Importer
  `validate` enforces these. Map herbaceous perennials/annuals/ephemerals/aquatics
  → `Herb`, sedges → `Grass`; keep nuance in `life`.)
- **lifecycle** (4): Annual, Biennial, Short-Lived Perennial, Long-Lived Perennial
  (rule: woody + documented-long = Long-Lived; only documented-short = Short-Lived).
- **food_types** (10): Fruit, Nut/Seed, Grain, Leafy Green, Vegetable,
  Root/Tuber/Bulb, Herb/Spice, Tea/Drink, Flower, Sap/Syrup.
- **material_types** (8): Timber/Wood, Fiber/Cordage, Basketry/Weaving, Dye,
  Soap/Saponin, Wax/Resin/Gum, Fuelwood, Other.
- **6 regions** (`REGION` in index.html / `derive_regions` in importer): Northeast,
  Southeast, Midwest, Great Plains, Mountain/Southwest, Pacific. A region is
  flagged when the plant covers **≥50%** of that region's states. Auto-derived
  from `native_states` — never hand-tune (the Verify editor derives it on save).

## 6. Importer pipeline (`importer/`)

Add plants, then backfill traits. **Do NOT hand-write SQL to add plants** — use
the pipeline.

1. **Draft** — plants are authored as `drafts/<slug>.json` (slug = kebab of sci).
   Historically written by small generator scripts (kept in a scratchpad, not the
   repo) using a `P(...)` helper + `S(raw,cooked,life,eco,materials,med)` scores
   helper. The 622+ **draft files ARE the versioned source of truth** in the repo.
   A draft has the `COLUMNS` fields (see `foodforest_import.py`): common, sci,
   family, type, life, edible_parts, other_uses, prep, harvest, sun, soil, risks,
   buy, native_states, native_regions (`[]`, auto-derived), native_to_us,
   invasive_states, invasive_everywhere, dec_priority, nf, pol, scores, sources,
   hardiness_zones, deer_resistant, native_north_america, native_americas.
2. **validate** — `python3 foodforest_import.py validate` (checks schema/vocab).
3. **apply** — `python3 foodforest_import.py apply` upserts ALL drafts on
   conflict `sci` (idempotent). To apply only a subset (a new batch), import
   `foodforest_import` as a module and POST just the wanted slugs (see the
   session's `apply_*.py` pattern) — the CLI applies the whole drafts/ dir.
4. **backfill** — `python3 backfill.py` runs, in order:
   `populate_traits.py` (hardiness+deer) → `populate_soil.py` (N/P/K) →
   `populate_soildims.py` (texture/drainage, rule-based) → `populate_fruit.py` →
   `populate_uses.py` (food/material/lifecycle + eco/material split) →
   `usda_enrich.py --apply --only-new` (authoritative override, LAST) →
   (optional `--with-images`). Flags: `--usda-all`, `--no-usda`, `--usda-dry-run`,
   `--plan`.
5. **images** — `fetch_images.py` (Wikimedia; only plants missing images) then
   `fetch_images_fallback.py` (base binomial → Wikimedia Commons File search →
   iNaturalist `/v1/taxa/{id}`). 429s are just rate-limits (re-run); 404s are
   title misses (fallback handles them).

**Key backfill design:** these derived/DB-only fields (soil dims, food/material/
lifecycle, USDA enrichment) are NOT in draft files, so re-applying drafts won't
touch them. `populate_uses.py` and `usda_enrich.py` are **fill-only / `--only-new`**
so they don't clobber hand edits; `populate_soildims.py` skips USDA-enriched
plants. Re-run backfill after each new batch; it only touches new plants.

### Individual scripts
| Script | What it does |
|---|---|
| `foodforest_import.py` | CLI: `fetch` (GBIF+Wikipedia research packets) / `validate` / `apply` / `list-remote`. Holds `COLUMNS`, `SCORE_KEYS`, `REGION`, `derive_regions`, `slugify`, `supabase_request`. |
| `populate_traits.py` | Hardiness zones (OVER-WIDE, uncapped) + deer resistance (family/genus rules). |
| `populate_soil.py` | soil N/P/K (Low/Moderate). |
| `populate_soildims.py` | soil_texture/drainage from soil prose (rule-based); **skips USDA-enriched rows**. |
| `populate_fruit.py` | min_plants_fruit / years_to_fruit for fruit/nut plants. |
| `populate_uses.py` | Classifies food_types/material_types/lifecycle + re-splits `other_uses`→`eco_uses`/`material_uses`. Keyword rules; fill-only (`--force` to redo). **Watch for substring false positives** (fixed: "astringent"→string, "European"→rope, acorn "tannin"). |
| `usda_enrich.py` | Resolves each plant to its USDA PLANTS symbol; overrides nf/soil_texture/soil_drainage + sets native_north_america; appends a USDA source; flags native_to_us disagreements. `--only-new` (default in backfill), `--all`, `--only "<sci>"`. Has an `NF_SKIP` set for species where USDA's family-level N-fixation is wrong (e.g. Gymnocladus dioicus). |
| `usda_enrich.py` API | `https://plantsservices.sc.egov.usda.gov/api/` — `PlantSearch?searchText=`, `PlantProfile?symbol=`, `PlantCharacteristics/{id}`. USDA is public-domain but has **no edibility/materials/medicinal data** — it complements, never replaces, ethnobotanical scores. |
| `backfill.py` | Ordered pipeline runner (above). |
| `fetch_images.py` / `fetch_images_fallback.py` | Images (Wikimedia → Commons → iNaturalist). |

## 7. index.html structure

- `dataProvider` (async): `getPlants`, `loadPlans`, `loadPlanItems`, `addPlant(plantId,planId)`,
  `removePlant(plantId,planId)`, `createPlan`, `renamePlan`, `deletePlan`,
  `setVerified`, `saveImages`, `updatePlant` (admin).
- `rowToPlant(r)` maps snake_case DB → camelCase UI (add new columns here).
- Constants near the top: `WEIGHTS`, `REGION`/`STATES`/`STATE_NAMES`, `PLAN_COLORS`,
  `textOn`, `FOOD_TYPES`, `MATERIAL_TYPES`, `LIFECYCLES`, `PLANT_TYPES`, `NPK_LEVELS`,
  `CATS`, `TEXTURES`, `DRAINAGE`, `PH_BANDS`, `deriveRegions`.
- Components: `App` (state + nav + routing), `Database` (filters + list),
  `PlantCard` (+`AddToPlan`, `ScoreBox`, `PlantImages`), `MyPlan` (+`PlanMiniCard`,
  `SoilExam`, `RiskRegister`, `PlanFilter`, `MultiSelect`), `ScoringGuide`,
  `RawData`, `VerifyPage` (+`PlantEditor`, admin), `Auth`.
- **Plans in the App:** state `plans` (array), `planItems` (`[{planId,plantId}]`),
  `curPlan`; a `membership` memo (plantId→[planId]); `toggle(plantId,planId)`;
  `newPlan/renamePlan/deletePlan`. Nav: "My Plans" parent with plans nested +
  "+ New plan". Cards show one colored pill per plan; add-control is a single
  button (1 plan) or a plan dropdown (multiple).
- **Database filters:** search, sort, direction, "Added batch", "Filter by plan"
  (PlanFilter), and multi-selects for **Food type / Material type / Lifecycle**,
  plus chip toggles (N-fixer, pollinator, good raw/cooked, deer, NY priority,
  "Not in any plan"). Pagination caps at 100/page.
- **Expanded card** shows: native regions, hardiness, fruit info, **Lifecycle**
  (category + detail), Edible parts (+food-type chips), prep, **Ecological uses**,
  **Material uses** (+material chips), harvest, sun, soil(+NPK), risks, sources.
- **Verify editor (`PlantEditor`):** finite-option fields are dropdowns/multi-selects
  (type, lifecycle, food/material types, soil N/P/K, texture, drainage, native &
  invasive states); native_regions auto-derives from states on save. Prose fields
  stay text; scores are number+tier. `plantToForm`/`formToPatch` bridge UI↔DB.

## 8. Common tasks

- **Ship a UI change:** edit `index.html`, sanity-check (grep for the identifiers,
  brace/paren balance — a `()` diff of +2 is pre-existing string parens, not a
  bug), `git commit`, `git push origin main`. Then ask the user to click-test if
  auth-gated. Never re-upload files; always push.
- **Add a plant batch:** cross-reference the source against existing `sci` first
  (30–55% overlap is normal) → draft `drafts/*.json` → validate → apply the batch
  → `python3 backfill.py` → images → commit drafts + push. New plants auto-get the
  next `batch` number and the USDA `--only-new` pass.
- **Add a DB column:** `execute_sql` via MCP (save the SQL to `importer/sql/`),
  map it in `rowToPlant`, surface in UI, and add a backfill step if it's derived.
- **Schema/DDL, triggers, RLS:** Supabase MCP `execute_sql` on ref
  `sysrtpvnkpfuieznfkzb` (verify it's the "Native Food Forest" project, not the
  Archive).

## 9. Gotchas / lessons

- **PDF sources:** prefer `pdfplumber.extract_tables()` over `pypdf` (pypdf
  silently dropped rows). Sites behind Cloudflare (e.g. Grow Native!) can't be
  scraped — have the user export a PDF/xlsx, then parse with stdlib
  (`zipfile`+`xml.etree` for xlsx; no openpyxl on this machine).
- **A "USDA export" is not necessarily NY-filtered.** The Jul 2026 xlsx was a
  nationwide characteristic search. For NY work, a USDA *Advanced Search by New
  York state* is a far better source.
- **Keyword classifiers false-positive on substrings** — pad/boundary them
  ("ink"↔"drink", "string"↔"astringent", "rope"↔"European", "tannin"↔acorn
  leaching, "pitch"↔"pitcher", "waxy bloom"↔wax). Auto-classification is a first
  pass; it's correctable on the Verify page (and fill-only so edits stick).
- **USDA family-level nitrogen-fixation can be wrong** (non-nodulating legumes
  like Gymnocladus) — hence `NF_SKIP` in usda_enrich.py.
- **Alpine/very-restricted plants** get no `native_regions` (they don't cover
  ≥50% of any region) — that's correct, not a bug.
- **`life` vs `lifecycle`:** `life` is free-text detail (e.g. "Perennial bulb"),
  `lifecycle` is the slim 4-category filter value. The card pill shows the category.

## 10. Feature & batch history (newest first)

Fix material-tag substring false positives · Structured food/material/lifecycle +
eco/material split + Verify dropdowns · Plan multi-select filter · Multiple named
plans (My Plans) · **Batch 9 (+100 nationwide US edibles → 1000)** · **Batch 8
(+100 NY keystone/habitat → 900)** · "Added batch" filter · usda_enrich
`--only-new` + non-clobber · **Batch (+149 NY edibles → 800)** · backfill.py ·
USDA enrichment tool · Materials rename + edible tiers→9 + NA/Americas nativity +
dyes · Commons/iNat image fallback · **Grow Native! (+275 → 651)** · **DEC
priority (+116 → 376)** · **Cornell perennials (+60 → 260)** · early My Plan /
Verify work · GitHub Actions Pages deploy.

## 11. Current state & likely next work

- **1000 plants**, batches 1–9. Coverage: NY-native edibles comprehensive; DEC
  S794 list fully covered; strong pollinator forbs; 275 lower-Midwest (Grow
  Native!); 100 nationwide top edibles; 100 keystone/habitat (sedges, ferns,
  grasses, willows, ericaceous shrubs, bog/carnivorous, woodland wildflowers).
- **Gaps for future batches:** more Carex, more grasses/rushes, lycophytes,
  submersed aquatics, remaining woodland wildflowers, rare/endangered NY natives.
- **Open review item:** the food/material/lifecycle auto-classification is a solid
  first pass but imperfect on 1000 plants — spot-check on the Verify page; a flag
  report (material tag w/o prose, edible-but-no-food-type, thin eco, food-on-toxic)
  was generated to `~/Downloads/plant_review_flags.json`.
