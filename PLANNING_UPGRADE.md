# Planting Plan upgrade — per-phase quantities, Scope scheduling, MS-Project-style Gantt

Companion to `HANDOFF.md` (§12, §14) and `SHOPS_PLAN.md`. This is a separate workstream from the Shop database;
they share only the Shopping List (plan → vendors).

Three changes, in dependency order: **(A) Plants tab → one column per phase**, which changes the stored data model;
**(B) Scope tab → schedulable phases**, which depends on A; **(C) Schedule tab → Gantt**, which depends on B.

---

## A. Plants tab — one column per phase, quantity inside each

### Today
`index.html` stores the Planting Plan as a single blob in `plan_layouts.data` (~line 1531):

```
layout = { v:1, step, counts, view, polys, places, soilMap, phases }
counts = { plantId: qty }        // one quantity per plant
phases = { plantId: phaseNo }    // one phase per plant
```

`computeProject` (~line 2484) maps **phase N → project year N** (`pYear`). `plantTasks`, the Maintenance tab, the
Forest Layers phase filter, `PlanMiniCard`'s P# badge and the Budget all read these two maps.

### Target
```
layout = { v:2, step, alloc, phaseMeta, view, polys, places, soilMap }
alloc     = { plantId: { phaseNo: qty } }          // qty per plant per phase
phaseMeta = { phaseNo: { name, quarter, year, order } }
```
`counts` and `phases` become **derived** for backward compatibility:
`counts[pid] = Σ alloc[pid]`, `phases[pid] = lowest phase with qty > 0`.

**Migration** — `migrateLayout(d)`: if `d.v < 2`, `alloc[pid] = { (phases[pid] || 1): counts[pid] || 0 }`, seed
`phaseMeta` from the existing phase numbers (one per project year, matching the old `pYear` behaviour), write `v:2`
on first save. Keep the derived `counts`/`phases` keys **written into the blob as well** for one release, so a stale
tab or an un-migrated reader doesn't lose data.

### Table changes
Column set becomes: `Common name · Layer · Score · Min→fruit · Yrs→fruit · Harvest · Ecology · P1 · P2 · … · Pn · Total`

- Each phase column is the existing `.ppqty` stepper (−/number/+), writing `alloc[pid][ph]`.
- `Total` is read-only, right-aligned, bold; it's what Scope/Budget/Harvest consume.
- **Add / remove phase column** control in the table header bar. Removing a phase that holds quantities asks first and
  offers to move them into an adjacent phase.
- **Phase count: no cap.** New and migrated plans start with **4 phases**; "+ Add phase" appends without limit.
  Once the columns exceed the container the table scrolls **horizontally inside its own wrapper** (`overflow-x:auto`;
  the page body never scrolls sideways), with the **Common name column frozen** (`position:sticky; left:0`, opaque
  background, right border, `z-index` above the cells and below the sticky header so the two corners stack correctly).
  Same treatment on the Scope table (B).
- **Sorting** (`QCOLS`/`qSortVal`, ~line 1846): each phase column is sortable by its own quantity; `Total` sortable.
- **Column filter row** (`colF`/`passCol`): each phase column gets `any / has qty / none`.
- **Bulk edit** (`bulkSetPhase`/`bulkSetQty`, ~line 1840): replaced by "set quantity **in phase P** for N selected
  plants", plus "move all quantities from phase X to phase Y".
- Mobile: phase columns collapse into a stacked per-phase list under each plant (the `data-l` label pattern already
  used at ~line 1994).

### Ripple — all of these read the old shape and must be updated in the same commit
`computeProject` · `plantTasks` / Maintenance tab · Budget (`projPrice`, stock cost per year) · Harvest tab ·
Forest Layers phase filter (`phaseVals`, ~line 2891) · `PlanMiniCard` P# badge · the Project Plan summary sentence
(~line 2626) · the new Shopping List (`SHOPS_PLAN.md` §3).

---

## B. Scope tab — one row per plant, grouped by phase, phases schedulable

- Full table, **one column per data point**: plant, sci, layer/type, qty in this phase, install hours, stock cost,
  site-prep hours, years to fruit, first-harvest year, notes. (Today Scope is a rolled-up summary; this replaces it
  with the detail table and keeps a totals row per phase.)
- Rows are **grouped under a phase header row** carrying: phase name, **Quarter** select (Q1–Q4), **Year** select,
  drag handle, up/down buttons, phase totals (plants, qty, hours, cost).
- Shifting a phase: either **drag its header row** (native HTML5 `draggable` — no library) or **change its Quarter /
  Year selects** directly. Both write `phaseMeta[ph].{quarter,year,order}`.
- Consequence: `computeProject`'s `pYear` (phase N → year N) is replaced by a real calendar lookup from `phaseMeta`,
  so two phases can share a year, a phase can be skipped, and the horizon derives from the latest scheduled phase.
- Phase schedule is the **single source of truth for the Gantt's phase-level dates** (C).

---

## C. Schedule tab — Gantt chart section

Added **below** the existing Schedule content, not replacing it.

### Data model (new tables, RLS per user — see Q2)
```
plan_tasks
  id, plan_id → plans(id), user_id default auth.uid(),
  wbs text, outline_level int, sort_order int, parent_id → plan_tasks(id) null,
  name, notes,
  duration_min int,            -- stored in minutes; displayed as d/w per the unit field
  duration_unit text,          -- m|h|d|w|mo, plus 'e' elapsed variants
  is_milestone bool, is_summary bool, is_manual bool,   -- MSP manual vs auto scheduling
  start_at timestamptz, finish_at timestamptz,          -- computed unless is_manual
  actual_start, actual_finish, pct_complete int,
  constraint_type text,        -- ASAP|ALAP|SNET|SNLT|FNET|FNLT|MSO|MFO
  constraint_date timestamptz, deadline timestamptz,
  calendar_id → plan_calendars(id) null,
  work_min int, cost_cents int, fixed_cost_cents int,
  phase_no int null,           -- links a task back to a planting phase (B)
  plant_id → plants(id) null,  -- links a task to a plant, for generated tasks
  is_generated bool, generated_key text,  -- lets regeneration preserve manual edits
  created_at, updated_at

plan_task_links                -- predecessors
  id, plan_id, pred_id → plan_tasks(id), succ_id → plan_tasks(id),
  type text,                   -- FS|SS|FF|SF
  lag_min int,                 -- negative = lead
  UNIQUE (pred_id, succ_id)

plan_resources
  id, plan_id, user_id, name, type text,      -- work|material|cost
  initials, group_name, max_units numeric,    -- 1.0 = 100%
  std_rate_cents int, ot_rate_cents int, cost_per_use_cents int,
  accrue text, calendar_id, material_label

plan_assignments
  id, plan_id, task_id, resource_id, units numeric, work_min int, cost_cents int

plan_calendars
  id, plan_id, name, is_default bool,
  workweek jsonb,              -- {mon:[["08:00","17:00"]], ..., sat:[...]}
  exceptions jsonb             -- [{date|range, working:false, name:"Frost"}]

plan_baselines
  id, plan_id, name, captured_at,
  snapshot jsonb               -- {taskId: {start,finish,duration_min,work_min,cost_cents}}
```

### Scheduling engine (`scheduleProject(tasks, links, calendars, opts)`) — pure function, no deps
- Calendar-aware date math: `addWorkingTime(date, minutes, cal)` / `workingMinutesBetween(a, b, cal)` honouring
  workweek, exceptions and a project start date.
- **Planting windows are advisory, never constraints** (Q6). The default calendar is 7-day working; frost dates and
  the dormant season are stored as `plan_calendars.exceptions` with `working:true, advisory:true`, so they **shade the
  timeline and raise a warning indicator** on any task overlapping them, but they never move a computed date and never
  block a save. Warnings surface as an indicator column in the grid + a filterable "N scheduling warnings" strip.
- Topological sort with **cycle detection** (report the cycle, don't hang).
- **Forward pass** → early start/finish; **backward pass** → late start/finish; **total slack** and **free slack**;
  `critical = totalSlack <= 0`.
- Dependency types **FS / SS / FF / SF with lag and lead**.
- Constraint types ASAP / ALAP / SNET / SNLT / FNET / FNLT / MSO / MFO, applied in the forward pass, with a
  "constraint conflict" warning rather than silent violation (MSP's behaviour).
- Summary tasks roll up: start = min child start, finish = max child finish, duration = span, work/cost = Σ children,
  % complete = work-weighted.
- Milestones: zero duration, diamond, still participates in links.
- Deadlines: no scheduling effect, red marker when finish > deadline (MSP behaviour).
- Recompute is debounced and memoised on `[tasks, links, calendars, projectStart]`.

### Grid (left pane)
MSP-like editable column set, user-toggleable: `ID · WBS · Indicators · Task Name (indent/outdent) · Duration ·
Start · Finish · Predecessors (text, "12FS+3d" syntax, parsed and validated) · Resource Names · Work · Cost ·
% Complete · Baseline Start · Baseline Finish · Start Variance · Finish Variance · Total Slack · Critical · Notes`.
Indent/outdent builds the summary hierarchy; drag to reorder; multi-select bulk edit (same pattern as the Plants tab).

### Timeline (right pane)
Custom **SVG** (not a library — theme control and feature coverage; see Q6):
- Zoom: day / week / month / quarter / year, with a two-row header (major/minor scale) like MSP.
- Bars: task bars, summary bars (bracket style), milestone diamonds, **baseline bars** as a thin bar beneath,
  **% complete** as a darker inner bar, **critical path** in `--red`, non-working time shaded, today line.
- Dependency arrows drawn as orthogonal polylines, faded unless the row is hovered/selected (they're noise at scale).
- Drag a bar to move (sets a constraint, MSP-style), drag its edge to change duration, drag from bar end to another
  bar to create an FS link.
- Print/export: PNG via canvas render, plus the CSV/XML exports below.

### Resources
Resource sheet tab (name, type, max units, rates, calendar) + assignment editor per task (units, work).
Over-allocation highlighted per day. **Automatic levelling is out of v1** (see Q5).

### Task seeding from the plan
Generated from the plan and then user-editable:
- one summary task per **phase** (dates from `phaseMeta` — B),
- under it: Site prep → Amend/soil → Plant (per plant or per layer, qty-driven) → Mulch → Water/establishment →
  Protect (deer/voles), with durations from `INSTALL_HRS` and quantities from `alloc`,
- recurring maintenance from `plantTasks(p)`,
- each carries `generated_key`; **regeneration updates only untouched generated tasks** and leaves anything the user
  edited alone (same non-clobber discipline as the importer's fill-only backfills).

### Interop
- **Export / import MS Project XML** (`.xml`, the Project 2003+ schema MSP still opens and saves natively) —
  `<Tasks>`, `<Resources>`, `<Assignments>`, `<Calendars>` with MSP's own field names and enum codes. Built with
  string templating + `DOMParser` on import. No dependency.
- CSV export of the grid.
- **`.mpp` is not possible** — see Q1.

---

## Status (Aug 2026)

**PA — shipped and gate closed.** Per-phase quantities (`alloc`), v1→v2 migration verified against the real
backup (54→54 plants, 441→441 quantity, phases intact), per-phase columns with a frozen name column.

**PB — built, then deliberately reverted.** Phase scheduling (quarter/year/reorder) briefly lived on the Scope
tab. It is gone: `phaseSlot`, `savePhaseMeta` and the renumber control were removed and `computeProject` is back
to "phase N = project year N". **Scheduling belongs to PC1 and must not be modelled twice.** What survives is the
Scope chart with clickable planting waves that open a sortable plant list.

**PC1 — engine shipped, gate open.** `scheduleProject()` lives in `index.html` as a plain-JS
`<script id="pc1-engine">` block (not JSX) so `schedule/test.js` runs the exact shipped code. **25/25 tests pass.**
Verification artefacts in `schedule/`: fixture, browser test harness, `pc1-fixture.xml` (MSPDI) and
`pc1-expected.csv`. There is no Node and no MS Project on this machine — the test runs in the browser and the
scheduler comparison targets ProjectLibre/GanttProject, so the **SNET and FNLT rows are provisional** until
checked in MSP itself. Row movement (settled Aug 2026): a drag changes **ID and WBS only**; links belong to the
task and travel with it, so no date moves and predecessor references merely re-render to keep pointing at the
same task. Reorder is within a phase.

**PC1 owns tasks, order and dates.** Confirmed direction: `computeProject` becomes a *generator* of work packages;
PC1 is the scheduler that assigns and stores their order and dates, and the Scope / Schedule / Budget views read
back from it. `plan_tasks` is therefore the source of truth for anything dated, and nothing else should compute a
date independently.

`phaseMeta` stays lifted to MyPlan and shared — PA's quantity columns need it and PC1 will want the same copy.

---

## Decisions of record (Q1–Q8, answered Aug 2026)

| # | Decision |
|---|---|
| Q1 | **MS Project XML (`.xml`) both ways.** `.mpp` is a closed binary format and is not producible here; MSP opens and saves the XML schema natively. |
| Q2 | **Real tables** (`plan_tasks`, `plan_task_links`, `plan_resources`, `plan_assignments`, `plan_calendars`, `plan_baselines`), RLS per user — not a JSONB blob. |
| Q3 | Reordering a phase in Scope **repositions it only**; phase labels stay stable (P2 may be scheduled before P1). A separate **"Renumber to match order"** button does the destructive rewrite, behind a confirm. |
| Q4 | **No phase cap.** Baseline 4 phases on new/migrated plans; "+ Add phase" is unlimited. Wide tables scroll horizontally inside their own wrapper with the **Common name column frozen**. |
| Q5 | **v1 only** to start: task grid + hierarchy + durations + FS/SS/FF/SF with lag + calendars + constraints + critical path + baselines + % complete + timeline (bars, arrows, zoom) + MS Project XML in/out. Resources/assignments/earned value are v2; levelling, multiple baselines, split tasks are v3. |
| Q6 | 7-day default working calendar. **The planting window is a warning, not a constraint** — it shades the timeline and flags overlapping tasks, but never moves a date and never blocks a save. |
| Q7 | Build inside `index.html`, with a hard checkpoint: if first paint regresses, move the Schedule tab to its own iframe file like `grants.html`. |
| Q8 | Staged build with an evaluation gate between stages — see **`STAGE_GATES.md`**. |

## PC2 — task grid (Aug 2026) — shipped

Sits **below** the existing Schedule content, not replacing it. Dates are never
computed in the component: `plan_tasks` is the source of truth and PC1's
`scheduleProject()` is the only thing that assigns dates.

**Grain (settled):** one summary per phase → per-**layer** planting tasks inside
it (canopy, shrub, herbaceous, groundcover, vine, in that order) → mulch/water →
browse protection where anything is browsed. Maintenance is aggregated: one row
per activity per year, never per plant. A 124-plant, 3-phase plan generates
**25 tasks**, not 350.

- **Add / delete tasks** — manual rows carry a null `generated_key` and survive
  regeneration untouched.
- **Regeneration is non-clobbering.** Editing a generated task sets `user_edited`;
  from then on regeneration skips it. Verified: a renamed, re-timed task kept both
  through a regenerate, and the notice reported "1 hand-edited task left untouched."
- **Predecessor text** `12FS+3d` parses with units m/h/d/w/mo and leads. Garbage is
  rejected with the offending text quoted; a reference to a non-existent task is
  rejected by number. Neither closes the editor.
- **Reorder changes ID and WBS only** — verified by diffing every task's dates
  across a drag: zero changed. Confined to the task's own phase.
- **Change notice** collapses to zero height when empty and compensates scroll on
  appearing, so the view never jumps.

### Bugs the mount-and-drive testing caught
1. `rowToTask`/`taskToRow` were inserted **inside** the `dataProvider` object
   literal. Babel caught it.
2. A just-added manual task had neither `id` nor `generatedKey`, so `persist()`
   could not match the saved row back and **inserted it again on the next save**.
   Falls back to `sortOrder` now.
3. The reorder guard compared parents **after** splicing the row out, so `toIdx`
   pointed one row further on and a legitimate move inside a phase was refused as
   a cross-phase jump.

### Not done here
Inline cell editing (everything goes through the row editor, per the approved
design), and the timeline pane — that is PC3, and slots into the same scroller.

## Project start + phase targets, and PC3 — timeline (Aug 2026) — shipped

### Dated fields live on `plans`, not the layout
`plans.project_start` (date) and `plans.phase_targets` (jsonb `{phase: date}`).
Deliberately **not** in the layout blob: the layout is written only by
`PlantingPlan`, which is unmounted while the user is on the Schedule tab, so the
task grid could never have persisted there. PC1 owns anything dated, so these sit
where PC1 can reach them.

**A phase target is hard, and reported.** It becomes a `SNET` constraint on the
phase's first task, so a phase cannot start before it; dependencies may still push
it later, and when they do a `target` warning fires. `targetDate` is a separate
field from `constraintDate` on purpose — SNET does the scheduling, `targetDate`
does the reporting.

Verified: with targets a year apart, Phase 1/2/3 start Apr 2027 / Apr 2028 /
Apr 2029 and the timeline widens from 320px to 10,304px. Before this, every phase
started on the project start date.

### PC3 — timeline
**HTML rows with positioned bars plus one SVG overlay for arrows — not a single
big SVG.** A monolithic SVG has to derive its geometry from the grid's rendered
row heights, which is exactly the coupling that made the first mockups drift apart
on mobile. Both panes now read the same `--rowh` / `--headh`. Measured in the real
component: **0px drift across 25 rows**.

Ships: task bars, summary brackets, milestone diamonds, % complete as a darker
inner bar, critical path in `--red`, target-date markers, today line, dependency
arrows (faded unless the row is selected), and day/week/month/quarter zoom.

Not yet: drag-to-move and drag-to-link on the bars, baseline bars (PC4), and
PNG export.

### Bugs caught by driving the real component
1. **`generate()` dropped `constraintType` / `constraintDate` / `targetDate`.** The
   generator produced them, the row builder never copied them across, so every
   phase still started on the project start date and the whole feature silently
   did nothing.
2. Grid dates showed `Apr 05` with no year — ambiguous across a multi-year plan.
3. Adding the year overflowed the 58px Start/Finish columns; measured the actual
   overflow (79px content in a 74px box) rather than guessing, and set 86px.
