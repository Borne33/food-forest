# PC1 engine — verification result (Aug 2026)

**Outcome: the scheduling logic is verified. 14 of 15 rows match an independent
implementation exactly; the 15th is a known convention difference where we follow
MS Project.**

## How it was done
`pc1-fixture-recompute.xml` carries tasks, links and durations but **no finish
dates**, so GanttProject 3.3.3322 had to schedule the project itself. Its output
was then compared against this engine.

The raw dates did **not** match at first — GanttProject's own timeline header
skips 10, 11, 17, 18, 24, 25 April, i.e. weekends. It scheduled Mon–Fri and
ignored the 7-day calendar in the file. Re-running this engine with
**GanttProject's actual assumptions** isolates scheduling logic from calendar
transfer:

| GanttProject did | Evidence |
|---|---|
| used Mon–Fri, not the file's 7-day week | its header omits every weekend date |
| ignored the Good Friday exception | 5 days from 7 Apr lands on 13 Apr only if 9 Apr is a working day |
| ignored the elapsed duration | read 4320 min as 9 *working* days, not 72 hours |
| ignored the SNET constraint | the milestone sat at the project start, not 12 Apr |

Those are documented GanttProject limitations, not defects in the file.

## Result under matched assumptions

```
 1 Phase 1 — Canopy & soil   mine 04/05–05/07   gp 04/05–05/07   MATCH   summary rollup
 2 Site survey & marking     mine 04/05–04/06   gp 04/05–04/06   MATCH
 3 Sheet-mulch the beds      mine 04/07–04/13   gp 04/07–04/13   MATCH
 4 Bare-root order arrives   mine 04/05–04/05   gp 04/05–04/05   MATCH   milestone
 5 Plant canopy trees (12)   mine 04/14–04/16   gp 04/14–04/16   MATCH   two predecessors
 6 Plant shrub layer (24)    mine 04/19–04/22   gp 04/19–04/22   MATCH
 7 Mulch & water in          mine 04/20–04/21   gp 04/20–04/21   MATCH   SS +1d lag
 8 Deer protection           mine 04/23–04/26   gp 04/23–04/26   MATCH
 9 Settle-in period          mine 04/27–05/07   gp 04/27–05/07   MATCH
10 Phase 2 — Understory      mine 04/05–04/27   gp 04/05–04/26   DIFF
11 Soil test & amend         mine 04/05–04/05   gp 04/05–04/05   MATCH
12 Plant herb layer (48)     mine 04/05–04/09   gp 04/05–04/09   MATCH   FS −1d lead
13 Divide groundcover        mine 04/19–04/21   gp 04/19–04/21   MATCH   FF
14 Final inspection          mine 04/22–04/22   gp 04/22–04/22   MATCH
15 Season complete           mine 04/27–04/27   gp 04/27–04/27   MATCH   SF
```

Verified by agreement: forward pass, backward pass, **FS / SS / FF / SF**, positive
lag, negative lag (lead), milestones, multi-predecessor maxima, and summary rollup.

## The one difference
**Phase 2's summary finish.** Phase 2 contains the zero-duration milestone
"Season complete" on 27 Apr. GanttProject ends the summary at 26 Apr —
it **excludes milestones from summary spans**. MS Project includes them, and so
do we (`finish = max(child finish)`).

We are keeping MSP's behaviour. Worth re-checking if the project is ever opened
in MSP itself.

## Still unverified
The engine's own calendar handling (7-day weeks, non-working exceptions, advisory
windows) and its constraint handling (SNET/SNLT/FNET/FNLT/MSO/MFO) could **not**
be cross-checked, because GanttProject ignores both. Those rest on the 25 unit
tests in `test.js` alone until someone opens `pc1-fixture.xml` in MS Project.
