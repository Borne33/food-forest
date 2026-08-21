# PC1 — scheduling engine

Headless, per `STAGE_GATES.md`. No UI ships with it.

## Where the code lives
`index.html`, in a **plain-JS** `<script id="pc1-engine">` block — deliberately not
inside the JSX/babel block, so the test can extract and run *the exact shipped
code* rather than a copy that drifts.

Exposed as `window.PC1`:
`scheduleProject · addWorkingTime · subWorkingTime · workingMinutesBetween ·
intervalsFor · topoOrder · DEFAULT_CALENDAR`

## Running the test
There is **no Node on this machine**, so the test runs in a browser console
(any page on the site — it fetches `index.html` itself):

```js
// 1. load the fixture and the harness
for (const f of ["schedule/fixture.js","schedule/test.js"]) {
  new Function(await (await fetch("/food-forest/"+f)).text())();
}
// 2. run
await PC1_TEST.run("/food-forest/index.html");   // -> {passed, failed, results}
```

Current state: **59 passed, 0 failed.**

## Verifying against a real scheduler (the ⛔ gate)

**Two files, and the difference matters.**

| File | Contains | What it proves |
|---|---|---|
| `pc1-fixture.xml` | tasks, links, calendar **and our computed dates** | the project imports and the structure is expressible |
| `pc1-fixture-recompute.xml` | same, but **no finish dates**; every task parked at the project start | the other tool schedules it itself — *this* is the real check |

Import the **recompute** file, let GanttProject/ProjectLibre lay it out, then
compare its dates against `pc1-expected.csv`. The plain file only echoes us back.

> **Import bug fixed Aug 2026.** The first version emitted no `<Start>` or
> `<Finish>` on any task, and nothing at all for the two summaries. MPXJ (which
> GanttProject uses) skips a task with neither start+finish nor start+duration,
> so both summaries were dropped and all thirteen children were orphaned —
> "source task=N was not found" thirteen times over. Every task now carries
> Start, Finish and Duration. The links and lags were read correctly even then.

`pc1-fixture.xml` is the same fixture as MS Project XML (MSPDI 2003+ schema),
openable in **ProjectLibre / GanttProject / MS Project**.
`pc1-expected.csv` is what this engine computes.

Open the XML, compare row by row against the CSV, and report any row that differs.

**Two caveats, stated up front:**

1. There is no MS Project here, so the comparison target is ProjectLibre or
   GanttProject. They agree with MSP on the common cases but diverge on some
   **constraint** handling (notably ALAP and the SNLT/FNLT family) and on
   calendar exceptions. Treat rows 4 and 14 — the SNET milestone and the FNLT
   task — as **provisional** until someone checks them in MSP itself.
2. The **advisory** planting window is deliberately *not* exported as a calendar
   exception. In this engine it warns without moving dates (decision Q6); if it
   were exported as non-working time, MSP would move dates and the two would
   disagree by design.

## What the fixture exercises
15 tasks · 13 links · FS, SS, FF, SF · a +1d lag and a −1d lead · a milestone ·
an elapsed-duration task · SNET and FNLT constraints · a deadline · one genuinely
closed day (Good Friday) · one advisory window · two summary rollups.

## Bugs the test caught before anything shipped
- `subWorkingTime`/`snapBack` bounced off a non-working day and spun until the
  20 000-iteration guard threw (`atMinutes(prev, 24*60)` is midnight of the
  *original* day).
- A negative lag was swallowed by `minutes <= 0`, so `FS−1d` behaved as `FS+0`
  and never overlapped.
- A start landing on an interval end (16:00) was not normalised to the next
  day's 08:00, so `SS+1d` disagreed with MSP. FS only worked by accident, via
  the lag-0 early return.
- The backward pass let `LF` run past the project finish through a non-binding
  SF link, so the task defining the end reported slack and **nothing came out
  critical at all**.

## Not in PC1
Task grid (PC2), timeline (PC3), baselines/variance UI (PC4), general MS Project
XML import/export (PC5). The XML here is fixture-only, for the gate.
