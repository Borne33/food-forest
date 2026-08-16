# Seed & Plant Shop Database + Organizations Database — build plan

Companion to `HANDOFF.md`. Mockups: `mockups/shops-mockups.html`.
Planting-Plan / Gantt workstream: `PLANNING_UPGRADE.md`. Evaluation checkpoints: `STAGE_GATES.md`.

**Status: decisions D1–D9 answered (Aug 2026). This doc is now the build spec, not a proposal.**

---

## 0. Decisions of record

| # | Decision |
|---|---|
| D1 | **Own top-level nav page**, "Shops & Seed", alongside Database / My Plans / Grant Finder / About. Public (signed-out) read. |
| D2 | Four tabs — **Directory · Map · Sale Calendar · Shop Editor (admin)**. Full spec in §2. |
| D3 | **Vendors and Sales are separate tables**; a sale belongs to a vendor (`sales.vendor_id`). **A sale is never itself a vendor — the organization hosting it is.** So Wild Ones HGCNY is one organization *and* one vendor, with its spring and fall sales as `sales` rows. An organization that sells or gives away plants/seed appears on **both** lists, joined by `vendors.org_id`; organizations that don't supply anything appear only on the Organizations list. The seeder rejects any vendor whose `kind` is `plant_sale` or `seed_swap`. |
| D4 | Freshness = **public product feeds (Shopify/Square/Woo) + annual PDF/order-form parse** first; vendor-supplied CSV as an ongoing outreach track; per-vendor HTML adapters case-by-case with permission; user reports later. Freshness always shown in UI; `unknown` is an explicit state, never an empty cell. |
| D5 | **Auto-link only on exact `sci`, exact `plant_synonyms`, or unambiguous exact common name.** Everything else goes to `vendor_plants_unmatched` for admin review. Cultivars keep the raw string, link to the straight species, flagged `is_cultivar`. |
| D6 | **Public read** on vendors / sales / vendor_plants / organizations. Admin write. Shopping list is per-user RLS. |
| D7 | Region + state + county + NY sub-region + lat/lon. **Street address is displayed on the card.** NY sub-regions are the **10 Empire State Development / REDC regions** (source: <https://esd.ny.gov/regions>) and are **derived from `county`** by `COUNTY_TO_SUBREGION` in `vendors_seed.py`, never hand-typed. Note ESD puts **Monroe and Livingston in Finger Lakes** and **Tompkins (Ithaca) in Southern Tier**. |
| D8 | **Deferred.** Collect `price_cents` + `unit` + `last_seen` from Phase 5 onward, expose it in the admin table only, and decide public display once there's a real sample of how complete and how stale it is. |
| D9 | Organizations scoped to groups that supply, teach about, or steward native plants in NY. No duplication with `ABOUT_SOURCES` / `SUSTAIN_AI` — link instead. |

---

## 1. Data model

Three concerns, four tables plus supporting ones:

| Concern | Table |
|---|---|
| A place you can get plants/seed | `vendors` |
| A dated selling/giving event | `sales` |
| What a place has | `vendor_plants` |
| A group doing native-plant work | `organizations` |

`vendors.org_id → organizations.id` (nullable) links "Wild Ones Genesee Valley" (org) to its sale vendor row.
Seed libraries, SWCD seedling programs, one-day chapter sales and commercial nurseries are all `vendors`, separated by
`kind` — they answer the same question ("can I get this plant, near me, and when").

`importer/sql/vendors.sql` — run via Supabase MCP `execute_sql` on ref `sysrtpvnkpfuieznfkzb`, then save the file.

```
organizations
  id, slug UNIQUE, name, kind, scope, mission, focus_areas text[],
  state, county, subregion, region, url, events_url, contact_email,
  membership text, notes, sources jsonb, needs_verification bool default true,
  last_verified date, created_at

vendors
  id, slug UNIQUE, name, org_id → organizations(id) null,
  kind text  -- how they supply plants/seed:
             -- nursery | seed_company | seed_library | conservation_district | botanic_garden
             -- | coop | society | chapter | nonprofit | land_trust | library | other
             -- NOT plant_sale / seed_swap (D3): an event is a `sales` row and its host
             -- organization is the vendor. The Directory's "plant sale" filter is derived
             -- from `exists (select 1 from sales where vendor_id = v.id)`.
  street, city, county, state, postal, subregion, region, lat, lon,
  address_note text,          -- "pick-up at the fairgrounds, gate C"
  url, catalog_url, order_form_url, email, phone,
  sells bool, gives_free bool, membership_required bool,
  ships bool, ships_states text[], pickup_only bool,
  forms text[],               -- seed | potted | plug | bare_root | tuber | scion | live_stake
  season_note text, order_window text, hours text,
  straight_species_only bool, local_ecotype bool, nursery_propagated bool,
  neonic_free bool, sourcing_notes text,
  inventory_mode text,        -- feed | vendor_csv | adapter | pdf_annual | manual | none
  inventory_url text, inventory_last_sync timestamptz,
  notes text, sources jsonb,
  needs_verification bool default true, last_verified date, verified_by text, created_at

sales                          -- D3: dated events, associated with a vendor
  id, vendor_id → vendors(id) on delete cascade, org_id → organizations(id) null,
  name, kind text,             -- sale | swap | order_window | open_house | pickup
  starts_on date, ends_on date, starts_at time, ends_at time,
  order_opens_on date, order_closes_on date, pickup_on date,
  recurs text,                 -- annual_spring | annual_fall | annual_winter_order | one_off
  venue_name, street, city, county, state, lat, lon,
  url, price_note, member_preview text, notes,
  source_url, needs_verification bool default true, last_verified date, created_at
  INDEX on (starts_on), (vendor_id)

vendor_plants
  id, vendor_id → vendors(id) on delete cascade,
  plant_id → plants(id) null,
  sale_id → sales(id) null,    -- set when stock is specific to one sale/order window
  raw_name, raw_sci, is_cultivar bool, cultivar_name,
  form text, size text, price_cents int, unit text,
  stock text,                  -- in_stock | out | seasonal | unknown
  source text,                 -- feed | vendor_csv | adapter | pdf | manual | user_report
  confidence text,             -- high | medium | low
  url, first_seen date, last_seen date, created_at
  UNIQUE (vendor_id, plant_id, form, cultivar_name)

plant_synonyms                 -- D5 matcher input
  id, plant_id → plants(id), name text, kind text ('sci'|'common'), source text
  UNIQUE (lower(name), kind)

vendor_plants_unmatched        -- D5 staging
  id, vendor_id, raw_name, raw_sci, form, seen_count,
  first_seen, last_seen, resolved_plant_id, dismissed bool

vendor_imports                 -- Shop Editor uploads / link submissions (§2.4)
  id, vendor_id null, sale_id null, kind text,   -- vendor | sale | inventory
  mode text,                   -- form | link | upload
  source_url text, storage_path text, filename, mime, bytes int,
  status text,                 -- queued | parsed | applied | failed | dismissed
  parsed jsonb, error text, created_by uuid, created_at, applied_at

shopping_list                  -- per user
  id, user_id default auth.uid(), plan_id → plans(id), plant_id, vendor_id null,
  qty int, done bool, note, created_at
  UNIQUE (user_id, plan_id, plant_id, vendor_id)
```

RLS: public `SELECT` on `organizations`, `vendors`, `sales`, `vendor_plants`, `plant_synonyms`; admin-uid
`INSERT/UPDATE/DELETE` (copy `importer/sql/admin_insert_plants.sql`). `vendor_imports` and
`vendor_plants_unmatched` are admin-only. `shopping_list` is own-row.

Views: `vendor_plant_counts` (natives per vendor), `plant_sources` (plant → vendors ordered by freshness/distance),
`sales_upcoming` (next 12 months, for the Directory banner and the Calendar tab).

---

## 2. The Shops & Seed page — four tabs

Nav: top-level "Shops & Seed" (`page==="shops"`). Component `Shops` in `index.html`, tabs like `MyPlan`'s.
`rowToVendor` / `rowToSale` mirror `rowToPlant`. Paginate every bulk read — the 1000-row PostgREST cap has bitten
this codebase repeatedly (HANDOFF §11, §12).

### 2.1 Directory tab — mockup 1 base + mockup 3 sorting
- Card list exactly as mockup 1: name, kind chips, distance, plan-match count, freshness dot, inventory preview,
  key/value block, action row. **Street address shown on the card** (D7), with a Directions link.
- **Sort by any datapoint** — the mockup-3 column set as a sort control: name, kind, sub-region, county, distance,
  native count, plan matches, plan coverage %, forms, ships, free, stock source, last checked, price completeness.
  Implement as `SCOLS` + `sortVal(v,key)` + a direction toggle, the same shape as `QCOLS`/`qSortVal` in the
  Planting Plan Plants tab (index.html ~line 1846). Reuse `.dirbtn` for direction.
- Filter bar + chip toggles as mocked (kind, region, state, sub-region, free, ships, local ecotype, straight species,
  has plants from my plan).
- **Upcoming-sales banner**, pinned above the filter bar: every `sales` row whose `starts_on`, `order_closes_on` or
  `pickup_on` falls in the **current or next calendar month**. Compact horizontal strip, one line per sale
  (date · name · vendor · town · "order closes in 9 days"), styled like the mockup-5 calendar block. Hidden when empty.
  Each entry deep-links to the Sale Calendar tab anchor.

### 2.2 Map tab — mockup 2, real Leaflet
- **Leaflet 1.9.4 is already loaded** in `index.html` for the Planting Plan (pinned CDN, plus leaflet-draw) — no new
  dependency. Same tile providers already in use (OpenStreetMap / Esri / OpenTopoMap) so the About sources list needs
  no change.
- `L.circleMarker` pins sized by plan-match count and coloured by `kind` (the mockup legend). `L.divIcon` if the count
  numeral inside the pin is wanted. Cluster only if the pin count passes ~150 (would need a plugin — defer).
- Radius slider draws an `L.circle` around the plan centroid (already reverse-geocoded for the Grant Finder prefill)
  and filters the list. "Ships to me" chip keeps out-of-radius mail-order vendors in the list, greyed, with no pin.
- Right-hand list is the same vendor records as the Directory, one-line form; hover ↔ pin highlight both ways;
  click scrolls the list and opens the popup.
- Sale locations render as a separate pin kind when their venue differs from the vendor address.

### 2.3 Sale Calendar tab
- Vertical, month-by-month, current month first, 12 months forward, then a "past sales" collapsed section
  (last year's dates are the best predictor of this year's).
- Each month is a section header (`Space Mono`, rule underneath, count on the right) containing the mockup-5 `gcard`
  small cards: sale name, vendor, town + address, date/time, kind chip, free flag, price note, "N plants from your
  plan", link.
- Order-window sales (SWCD) appear in **two** places: the month the order opens and the month of pick-up, each
  labelled for which it is.
- Filters: sub-region, kind, free-only, "only sales carrying plants from my plan".
- Actions: "Add to my plan's calendar", ICS export (one `.ics` per sale or all shown — pure string building, no dep).

### 2.4 Shop Editor tab — admin only
Gated on `ADMIN_EMAIL` / admin uid like the Verify page. Three entry modes for each of two record types:

**Add / edit a Shop** and **Add / edit a Sale**, each via:
1. **Form** — structured, every field a select/chip where the vocabulary is finite, mirroring the grants editor's
   `buildForm`/`readForm` approach (`grants.html`, HANDOFF §19). Empty number inputs read back as `null`, not `0`.
2. **Link** — paste a URL. Attempts a live fetch and pre-fills what it can; on CORS failure it still creates a
   `vendor_imports` row with `mode='link'` so the importer can fetch it server-side later. See §5 for the CORS reality.
3. **Document upload** — PDF / CSV / XLSX order form or plant list → Supabase Storage bucket `vendor-imports`
   (admin-write, admin-read) + a `vendor_imports` row. CSV parses in-browser immediately; PDF/XLSX queue for
   `importer/vendor_import.py`, which writes `parsed` back for admin review and one-click apply. See §5.
- Edit flow: searchable list of all vendors and sales, including past/closed ones (last year's sale is the starting
  point for this year's — same reasoning as the grants "duplicate an existing" flow). Duplicating a sale clears
  `source_url`/`needs_verification` state so importers don't later claim the copy.
- A **review queue** panel: `vendor_plants_unmatched` (D5) and `vendor_imports` with `status='parsed'`.

---

## 3. Elsewhere on the site

| Where | Change |
|---|---|
| **Plant card (Database)** | Mockup 4's inline "Where to buy" block, from the `plant_sources` view. Sorted local & in stock → local & seasonal → mail order → unknown. Legacy `plants.buy` prose kept below as a fallback note. Explicit "no known source — suggest one" state. |
| **My Plan** | New **Shopping List** tab: the plan's plants grouped by best vendor, per-vendor coverage %, qty pulled from the Planting Plan allocation, check-off state, CSV/print export, "sales coming up that carry these" strip. Backed by `shopping_list`. |
| **Planting Plan → Plants / Scope / Schedule** | See `PLANNING_UPGRADE.md` — separate workstream. |
| **About** | Add each new data source to `ABOUT_SOURCES` as it's introduced; cite per-record in `sources`. |

---

## 4. Phases

**Phase 1 — schema + Upstate NY seed.**
DDL + `importer/sql/vendors.sql`. `importer/vendors_seed.py` upserts `importer/vendors/seed_vendors.json` and
`seed_sales.json` on `slug` (PostgREST, same pattern as `foodforest_import.py`). Geocode once via Nominatim, cached
under `importer/cache/geo/`. Scope for the first pass is the **Western NY, Finger Lakes and Southern Tier** ESD regions, plus mail-order sources
shipping to NY, and every known 2026–27 sale date.
**Every seeded record is confirmed against the vendor's own live site before `needs_verification` is cleared.** The
names in the mockups are a starting list, not verified data.

**Phase 2 — the page.** `Shops` component, Directory + Map tabs, `dataProvider.getVendors/getSales/getVendorPlants/
getPlantSources`, nav entry, public read path tested signed-out.

**Phase 3 — Sale Calendar tab + Directory upcoming banner** (needs only `sales`, so it ships before any inventory).

**Phase 4 — initial inventory sampling.** 6–10 vendors × 20–60 plants via `importer/vendor_inventory.py` from catalog
pages and order-form PDFs. Matching per D5; misses to `vendor_plants_unmatched`. This is what makes the plant card
useful and it does not need automation to be worth shipping.

**Phase 5 — plant card "Where to buy"** (mockup 4 block) + **My Plan Shopping List**.

**Phase 6 — Shop Editor tab** (form → link → upload, in that order of delivery).

**Phase 7 — automated refresh.** `importer/vendor_fetch.py` with the `grant_fetch.py` interface (`--limit`,
`--dry-run`, `--only <slug>`, `--stale-days`), dispatching per `vendors.inventory_mode` to adapters in
`importer/vendors/`. First adapter: the Shopify/Square/Woo public product-feed reader — one file, many vendors.
Second: `pdf_annual` for SWCD order forms (`pdfplumber.extract_tables`, per HANDOFF §9). Never deletes rows; marks
`out` and lets them age out of display. Cache under `importer/cache/vendors/`, respect `robots.txt`, identify the
client honestly, rate-limit hard — same discipline as `trickle_loop.sh`.

**Phase 8 — community input.** "Suggest a shop" / "Report a correction" → admin queue. "Claim your listing" outreach
to seeded nurseries (D4 track 2). Revisit **D8 (price display)** here, with real data to look at.

---

## 5. Known issues to design around

- **CORS blocks most "add via link".** Confirmed in the grants editor (HANDOFF §19): Grants.gov and dec.ny.gov both
  refuse browser fetches; small nursery sites mostly will too. The Shop Editor's link mode therefore always writes a
  `vendor_imports` row as its real output and treats a successful in-browser fetch as a bonus. The ArcGIS-style
  CORS-friendly source is the exception, not the rule.
- **PDF parsing cannot happen in the browser** without adding a CDN dependency, and nursery order forms are messy
  enough that `pdfplumber.extract_tables()` in the importer is the proven path. Upload → Storage → queue → importer
  parses → admin approves. Be explicit in the UI that upload is not instant.
- **Supabase Storage is new to this project.** One bucket, admin-only policies, saved to `importer/sql/`.
- **Seasonality reads as staleness.** A nursery legitimately has nothing in October — `season_note` and a
  "closed for the season" state, not `out` on 200 rows.
- **One-day sales are the majority of local supply**, which is exactly why `sales` is its own table and gets its own
  tab and banner. A pure inventory model renders Upstate NY's best sources as empty.
- **Cultivar creep and genus-level listings.** "Serviceberry, *Amelanchier* spp." matches no `plant_id`; allow null
  `plant_id` with a genus hint rather than forcing a wrong link.
- **Small businesses are not APIs.** Feeds and vendor-supplied lists first; ask before adapting anything else.
- **Publishing about third parties.** Use only what an organization publishes about itself, cite the source, honour
  removal requests, default `needs_verification=true`.

## 6. Carried-over constraints (HANDOFF)

No build step, no Node, no new deps beyond CDN scripts already loaded; everything in `index.html` and stdlib
Python 3.9 in `importer/`. DDL only via Supabase MCP, mirrored to `importer/sql/`. UI can't be preview-tested here —
verify statically, then click-test signed in. After the session, add its `/cost` total to `build_stats` (§13).
