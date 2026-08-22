# Stage gates — what to evaluate before starting the next stage

Companion to `SHOPS_PLAN.md` and `PLANNING_UPGRADE.md`.

**Every stage that ships code also owes the token counter.** HANDOFF §13 says to add each session's
`/cost` total to `build_stats.tokens`, which drives the AI-footprint figure on the About page. I cannot read my
own usage, so this can only happen if you paste the `/cost` number and I write it. It was missed for the whole
S1–S6 run, so the published figure currently understates reality. Treat it as a line item on every gate below,
not an afterthought.

**Why these exist:** the browser-preview sandbox can't serve this repo, and most of the app is auth-gated behind RLS
(HANDOFF §2), so I verify changes statically and *you* are the only one who can confirm they actually work signed in.
Each stage below ends with a short list of things to check before the next stage starts building on top of it. Items
marked **⛔ blocking** mean don't proceed until they pass — the next stage would build on a bad foundation.

Suggested order interleaves the two workstreams so the highest-regression-risk work (the plan data migration, PA)
lands early, while the shop work — which is purely additive — proves out the new page shell first.

**Order:** S1 ✅ → S2 ✅ → S2b ✅ → S3 ✅ → S4 ✅ → PA ✅ → ~~PB~~ (→PC1) → S5 ✅ → S6 ✅ → **S7** → S8 → PC1 ✅ → PC2 ✅ → PC3 ✅ → PC4 ✅ → PC5 🟡 → S9 → S10

---

## S1 — Schema + Upstate NY seed data

Ships: `importer/sql/vendors.sql` applied; `vendors`, `sales`, `organizations` populated with the Upstate NY set.
No UI yet.

Evaluate:
1. **⛔ Read the seeded records.** I'll send you a CSV of every vendor and sale. Check the ones you know personally —
   names, towns, whether they actually sell natives, whether the seed libraries are still running. Vendor data ages
   badly and a wrong listing is worse than a missing one.
2. **⛔ Anything you'd rather not list.** Small operations that don't want traffic, anything defunct, anything
   politically awkward. Easier to drop now than after it's linked from plant cards.
3. Coverage sanity: are the shops you'd actually drive to present? Name the ones I missed — the seed list is the
   foundation for everything downstream.
4. Sub-region assignments (Western NY vs Finger Lakes) — does the split match how you think about the region?
5. Whether **organizations** feels right at ~15 records, or wants to be broader/narrower before the page is designed
   around it.

Unlocks: the whole Shops page.

---

## S2 — Shops & Seed page: Directory tab

Ships: new nav item, `Shops` component, card list, filters, chip toggles, sort-by-any-column.

**Blocked gate item — needs a decision.** `index.html` line ~4468 is `if(!user) return <Auth/>;` — the *whole app*
is sign-in-only, so no page can be seen signed-out no matter what the RLS says. The DB half of D6 is done and
verified (public SELECT works with the anon key; anon INSERT is refused), but the app half needs App's auth gate
moved from "the entire app" to "only the pages that need a user" (My Plans, Verify). That is ~30 lines and touches
the core routing of every page, so it is its own stage — **S2b** — not a silent add-on to S2. Until it runs, treat
gate item 1 below as deferred, not failed.

Evaluate:
1. **⛔ Signed-out access** — *deferred to S2b, see above.* When S2b lands: open the site in a private window; the
   Shops page must load and show everything without logging in (D6). If it's blank, the RLS policy is wrong.
2. **⛔ No regression on existing pages** — Database, My Plans, Grant Finder, About all still load and the nav still
   works on mobile. A new top-level page touches the router and the menu.
3. Sorting: click through every sort column, both directions. Empty/unknown values should sort predictably (last),
   not scatter.
4. Distance figures — do they look right for shops you know? Distance depends on the plan centroid, so check it both
   with a plan selected and with none.
5. Card density: with address now on the card (D7), is the card too tall on mobile? This is the moment to cut fields.
6. "Has plants from my plan" chip is meaningless until S5 — confirm it degrades gracefully rather than showing 0 for
   everything as if it were a real answer.

Unlocks: Map and Calendar tabs (same data, same shell).

---

## S3 — Map tab

Evaluate:
1. **⛔ Leaflet doesn't collide with the Planting Plan map.** Open Shops → Map, then My Plans → Planting Plan, then
   back. Two Leaflet instances in one SPA is the classic source of grey tiles and dead drag — check both maps still
   pan/zoom after switching, and after a page resize.
2. Pin legibility at default zoom with the real seeded count — if pins overlap badly, that's the trigger for
   clustering (deferred in the plan).
3. Radius slider ↔ list agreement: the list count must match what's inside the circle.
4. Mail-order vendors behave sensibly (in the list, no pin, greyed).
5. Mobile: is the map usable at phone width, or should it get a full-screen mode?

---

## S4 — Sale Calendar tab + Directory upcoming-sales banner

Evaluate:
1. **⛔ Dates.** Every sale date in the calendar against the vendor's own page. This is the highest-consequence data
   on the site — someone driving to a sale on the wrong day is a real harm.
2. Order-window sales appearing twice (order opens / pick-up) — is that clarifying or confusing in practice?
3. Banner window: current + next month. Too noisy in March (everything at once)? Too empty in August?
4. ICS export opens correctly in your calendar app.
5. Past-sales section: useful as a prediction of next year, or just clutter?

Unlocks: nothing structurally — but it's the first thing worth telling other people about, so evaluate it as a
public-facing artifact.

---

## PA — Plants tab: one column per phase — ✅ CLOSED (Aug 2026)

Ships: `v:1 → v:2` layout migration, per-phase quantity columns, frozen name column, updated sorting/filtering/bulk
edit, and updates to every consumer of `counts`/`phases`.

Evaluate:
1. **⛔ Back up first.** Before I apply anything, take a snapshot of `plan_layouts` (I'll dump it to a JSON file and
   confirm the row count with you). The migration rewrites the shape of every saved plan.
2. **⛔ Open each existing plan and confirm nothing was lost** — same plants, same total quantities, phases landed
   where they used to be. Check a plan that had phases set and one that never did.
3. **⛔ Cross-device / stale-tab check.** Open a plan in two tabs, edit in one, reload the other. The migration keeps
   derived `counts`/`phases` written for one release specifically to survive this; confirm it does.
4. Downstream tabs still agree: Forest Layers phase filter, Maintenance, Harvest, Project Plan Budget and the summary
   sentence should all show the same totals they did before the change.
5. The wide-table behaviour: add phases until it scrolls. Frozen name column still readable, header still sticky, no
   sideways scrolling of the *page*.
6. Whether 4 baseline phases feels right when you start a new plan.
7. Bulk edit semantics — "set qty in phase P for N selected" and "move phase X → Y" do what you expect.

Unlocks: PB, and the Shopping List (S7) quantity source.

---

## PB — Scope tab: schedulable phases — ❌ REVERTED, folded into PC1

Built and undone by decision: scheduling is PC1's job and must not exist in two places. The Scope tab keeps
clickable planting waves with a sortable plant list; no dates are set here.

### (original gate, kept for PC1's benefit)

Evaluate:
1. **⛔ Quarter/Year changes propagate** into Budget, Project Plan horizon, and the summary sentence — `pYear` is gone,
   so anything still assuming "phase N = year N" will show wrong years. Check a plan where two phases share a year and
   one where a phase is skipped.
2. Row drag: does reordering feel right *without* renumbering (Q3)? This is the decision most likely to feel wrong
   once it's real — the "Renumber to match order" button is there if it does.
3. Phase totals (plants, qty, hours, cost) reconcile with the Plants tab totals.
4. Column set: with one column per data point, is anything missing that you'd want before the Gantt consumes it?
   Adding columns later is cheap; changing what a phase *means* later is not.
5. Horizon behaviour when the latest phase is pushed out several years — does the Budget/Schedule still read sensibly?

Unlocks: **PC — the Gantt takes its phase-level dates from here.** Don't start PC until PB's dates are trustworthy.

---

## S5 — Inventory sampling (6–10 vendors, 20–60 plants each)

Evaluate:
1. **⛔ Matching quality (D5).** I'll give you the `vendor_plants_unmatched` list and a sample of auto-matched rows.
   Spot-check ~30: any wrong `plant_id` link is a bug in the matcher, not a data-entry slip, and it'll repeat at scale.
2. Cultivar handling — are `'Viking'`-type entries linking to the straight species and flagged, as intended?
3. Genus-level rows (`Amelanchier spp.`) — is the null-`plant_id` + genus hint useful, or noise?
4. Whether `stock` states map onto how these vendors actually operate, or whether "seasonal" is doing too much work.
5. **Price data reality check** — this is the sample that decides **D8**. How many rows have a price, how stale, how
   consistent the units are. Decide then whether prices go public.

---

## S6 — Plant card "Where to buy"

Evaluate:
1. **⛔ The "unknown" state reads as unknown**, not as "unavailable". Find a plant with no sourced vendors and confirm
   the wording doesn't imply you can't buy it anywhere.
2. Ordering (local in-stock → local seasonal → mail order → unknown) matches what you'd actually want to see first.
3. Freshness labels are honest and legible at a glance.
4. The legacy `plants.buy` prose still shows and doesn't contradict the structured list.
5. Page weight — the plant card is the most-rendered component in the app; check that expanding a card is still snappy
   on mobile with the extra query.

---

## S7 — My Plan: Shopping List tab

Evaluate:
1. **⛔ Quantities come through correctly from PA's per-phase allocation** — a plant in two phases should produce the
   right total (and, ideally, tell you which phase each is for).
2. Vendor grouping: does "best vendor" produce a list you'd actually shop from, or does it scatter 20 plants across
   9 vendors? If it scatters, the grouping heuristic needs a "minimise number of stops" mode.
3. Check-off state persists across devices.
4. CSV/print output is usable at a nursery — on a phone, offline.

---

## S8 — Shop Editor (admin)

Evaluate:
1. **⛔ Admin gating.** Confirm the tab is invisible and its writes fail for the non-admin test user, not just hidden
   in the UI.
2. Form mode: can you add a real new shop end-to-end without touching SQL?
3. Link mode: expect most sites to fail CORS and fall back to queueing (§5 of the shops plan). Confirm the failure is
   *clearly communicated*, not silent.
4. Upload mode: upload a real SWCD order-form PDF. Confirm it queues, and that the UI says it isn't instant.
5. Storage bucket permissions — try to read the bucket signed out; it must refuse.
6. The unmatched/import review queue is somewhere you'd actually keep up with, or it'll rot.

---

## PC1 — Gantt scheduling engine (headless) — ✅ SHIPPED, gate largely closed

Ships: `scheduleProject()` + calendar math, no UI. Verified with a test fixture, not by clicking.

**Result (Aug 2026):** 25/25 unit tests pass, and a cross-check against GanttProject 3.3.3322
matched **14 of 15 rows exactly** — see `schedule/VERIFICATION.md`. Forward/backward pass,
FS/SS/FF/SF, lag, lead, milestones and summary rollups are all confirmed against an independent
implementation. The single difference is Phase 2's summary finish: GanttProject excludes
milestones from summary spans, MS Project includes them, and we follow MSP.

**Still open:** calendars (7-day weeks, exceptions, advisory windows) and constraints
(SNET/SNLT/FNET/FNLT/MSO/MFO) are **not** cross-checked — GanttProject ignores both, so those
rest on the unit tests until someone opens `schedule/pc1-fixture.xml` in MS Project itself.

Evaluate:
1. **⛔ Compare against MS Project directly.** I'll produce a small fixture (≈15 tasks, mixed FS/SS/FF/SF, lags, a
   constraint, a milestone) and its computed dates; open the same project in MS Project and confirm the dates match.
   This is the single most valuable check in the whole program — every later stage assumes the engine is right.
2. Cycle detection reports the cycle instead of hanging.
3. Calendar edge cases: a task starting on a non-working day, a zero-duration milestone, an elapsed-duration task.
4. Critical path matches MSP's on the fixture, including near-critical tasks with small slack.
5. Advisory planting-window warnings fire without moving any date (Q6).

---

## PC2 — Task grid

Evaluate:
1. **⛔ Task generation from the plan** produces something recognisable as your actual planting sequence — and
   regenerating after a plan edit **doesn't clobber your manual edits** (`generated_key` non-clobber rule).
2. Predecessor text syntax (`12FS+3d`) parses, validates, and rejects garbage clearly.
3. Indent/outdent and reorder produce a sane WBS; summary rollups are correct.
4. Editing speed with a realistic task count (200+ rows) — this is where the tables-not-blob decision (Q2) pays off or
   doesn't.
5. Column set vs. what you use in MS Project — missing columns are cheap to add now.

---

## PC3 — Timeline (SVG)

Evaluate:
1. **⛔ Page-load regression checkpoint (Q7).** Time first paint of the whole app before and after. If it's noticeably
   worse, this is the moment to move the Schedule tab into its own iframe file — not later.
2. Bars/arrows legible at each zoom level; dependency arrows not overwhelming at 200 tasks.
3. Drag-to-move and drag-to-link behave like MSP (a drag sets a constraint — confirm that's what you want, it surprises
   people).
4. ~~Printing / PNG export produces something you'd put in front of someone else.~~ **PNG done** (Aug 2026) — 2× canvas,
   title/subtitle/date stamp, grid + scale + bars + baseline bars + % complete + deadline flags + arrows + legend.
   Swaps the Slack column for Base finish / Finish var when a baseline exists. Print stylesheet still not done.
5. Mobile: probably read-only there. Confirm that's acceptable rather than trying to make it editable.

---

## PC4 — Baselines, warnings, variance — ✅ SHIPPED (Aug 2026)

Evaluate:
1. ~~Capture a baseline, shift a phase in Scope (PB), confirm variance columns and baseline bars tell the true story.~~
   **Done.** Stretching Site prep 1.8d → 6d gave it start var 0d / finish var +4.3d, carried +4.3d to every task
   downstream of it and to the Phase 1 summary, and left Phase 2 — a separate chain — at 0d. Five baseline bars went red.
2. ~~Warning strip surfaces the planting-window overlaps you'd care about, and can be dismissed/filtered.~~
   **Done.** Grouped by kind with per-kind hide chips and counts, expandable list, click-a-message-to-select-the-row,
   "show all" when anything is hidden. ⛔ **Still to check with real data:** the advisory/planting-window kind has never
   fired, because no `plan_calendars` exceptions exist yet. Confirm it reads well once frost dates are loaded.
3. ~~Deadline markers behave like MSP (flag, no scheduling effect).~~ **Done, with the MSP nuance stated:** a deadline
   never moves a date, but it *does* cap late finish and therefore eats slack, and drives the task critical when
   overrun. That is MS Project's behaviour and it is what the Slack box in the editor writes.

Still open for a later pass: baseline variance is not surfaced in the Budget or Summary tabs, only in the task grid
and on the chart.

---

## PC5 — MS Project XML import/export — 🟡 BUILT, gate needs Alex

Built and tested in-app (60 XML tests, all green). What is written and read back is listed in `schedule/README.md`,
along with what is deliberately not carried.

Evaluate:
1. **⛔ Round-trip. STILL NEEDS ALEX — there is no MS Project on this machine.** Export → open in MS Project → save →
   re-import. What has been proven here: a full app-level export→import is byte-identical on all 19 rows and 6 links
   with the baseline intact, and re-importing `pc1-fixture.xml` (written by a *different* writer, the Python script)
   reproduces all 15 rows of `pc1-expected.csv` exactly, critical path included. What MSP itself does with the file
   is untested.
2. **⛔ Import a project *you* made in MS Project and see what breaks.** Same reason. The closest proxy run here was
   the Python-written fixture, which is not the same as MSP's own output — MSP writes far more elements, and the
   reader ignores everything it does not recognise, which is the behaviour to check.
3. Whether v2 (resources, assignments, earned value) is worth starting, now that you've used v1 on a real plan.

**Known loss, worth reading before the round trip:** imported tasks arrive with no `generated_key`, so they are treated
as hand-made and "Regenerate from plan" will leave them alone and add its own alongside. That is the safe default but
it means a round trip through MSP severs a plan's tasks from the planting plan that produced them.

---

## S9 — Automated inventory refresh — 🟡 BUILT, and the answer to item 2 changes what it is for

`importer/vendor_fetch.py`. Dry run by default; `--apply` writes.

Evaluate:
1. ~~**⛔ Run `--dry-run` and read the diff before anything is applied.** Check for false "out of stock" — a feed that
   fails should leave rows alone, not mark them out.~~ **Machinery done and tested; the READ is still Alex's.**
   All four failure modes (HTTP error, timeout, empty feed, unparseable body) were forced against the live Ernst
   vendor and left the data untouched — `stock='out'` count 0 before and after each. On top of that a feed that comes
   back below 60% of the rows already held still applies prices and additions but **refuses to mark anything out of
   stock**; a deliberately truncated run reproduced this (46% coverage, 118 rows protected). Rows are never deleted;
   a row the feed stops mentioning goes to `stock='unknown'`, the explicit state D4 asks for.
2. ~~Which vendors are actually on Shopify/Square (that's what determines whether this stage was worth it).~~
   **Answered, and it is the headline. Of 44 vendors with a URL, 3 expose a public product feed, and only one of
   those — Ernst Conservation Seeds, 205 rows — is a native-plant source.** The other two are The English Gardener
   (a gift shop: first product "Artisan Glass Sunflower Bowl") and Urban Roots (a garden market: "Cannabis Growing
   101"). Platforms: 25 no e-commerce markers at all, 7 Wix, 4 Squarespace, 3 WooCommerce, 3 Square, 2 Shopify —
   and Wix, Squarespace and Square publish no public catalogue endpoint. **The two biggest catalogues in the
   database will never come this way:** Prairie Moon (670 rows) is Magento, whose catalogue API needs a token, and
   the HGCNY list (153 rows) is a PDF. So the "one adapter, many vendors" premise does not hold, and
   `vendor_fetch.py` was built source-agnostic instead — `--file` takes a supplied list through the same diff and
   the same safety rails.
3. ~~Request volume per vendor per run — confirm you'd be comfortable with a nursery owner seeing it.~~
   **Probe: at most 5 requests per vendor per run** (robots.txt, homepage, up to 3 feed candidates), 1.5 s apart,
   honest User-Agent, no crawling beyond those fixed paths. A full probe of all 44 is ≤220 requests over ~6 minutes.
   **Refresh: one paginated read per vendor** — Ernst's whole 687-product catalogue is 14 requests. ⛔ Your call
   whether that reads as reasonable.
4. ~~Whether any vendor should be asked for permission first, or invited to submit a list instead.~~
   **Decided Aug 2026: tabled.** No vendor outreach for now; revisit as a longer-term goal. `--file` is already
   wired for supplied lists whenever that changes.

**Also decided Aug 2026: this stays MANUAL.** No cron. The argument for it is this very run — three defects surfaced
only because a person read the dry run before it was applied. Run it seasonally, when Ernst refreshes pricing.

**Three defects the dry run shook out, all fixed before anything was written:**
- 237 seed **mixes** were being filed against single species — a mix is not a species, and that is exactly the wrong
  "where to buy" the strict D5 matcher exists to prevent.
- 13 named Switchgrass selections, 7 Big Bluestem and 6 Indiangrass were **collapsing onto one row each**, because
  the inherited ecotype pattern only caught a trailing bare state code and missed "Long Island-NY Ecotype",
  "NY4 Ecotype", "Fort Indiantown Gap-PA Ecotype". A regional ecotype is not packaging; it is the product.
- Duplicate keys would have made PostgREST reject the whole batch ("ON CONFLICT DO UPDATE cannot affect row a
  second time"). Collapsed and reported rather than left to fail at write time.

**Nothing has been applied.** The pending Ernst diff is 60 new, 189 unchanged, 18 to `unknown`. Most of those 18 are
the *same products* re-keyed under the corrected ecotype string, not delistings — the run says so and prints both
lists so it can be checked. Read it, then:
```
python3 importer/vendor_fetch.py --vendor ernst-conservation-seeds --unit "per pound (bulk seed)" --apply
```

---

## S10 — Community input + D8 price decision

Evaluate:
1. Suggestion/correction queue is manageable at your expected volume.
2. **D8:** with real data in hand, decide whether prices are published, admin-only, or dropped.
3. Whether "claim your listing" outreach is something you want to run — it's the highest-quality data source in the
   plan and the only one that costs relationship time rather than compute.
