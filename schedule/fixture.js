/* PC1 verification fixture — 15 tasks, mixed FS/SS/FF/SF, lags and a lead,
   a milestone, an elapsed-duration task, two constraints, a deadline, and an
   advisory planting window. Deliberately small enough to check by hand and to
   open in ProjectLibre/GanttProject via the XML export.

   Calendar: 7-day week, 08:00–16:00, so 1d = 480 working minutes. */
(function(g){
"use strict";
const D = 480;                       // one working day, in minutes
const START = "2027-04-05T08:00:00"; // a Monday

const calendars = [{
  id: "std", name: "Standard (7-day)", isDefault: true,
  workweek: { sun:[["08:00","16:00"]], mon:[["08:00","16:00"]], tue:[["08:00","16:00"]],
              wed:[["08:00","16:00"]], thu:[["08:00","16:00"]], fri:[["08:00","16:00"]],
              sat:[["08:00","16:00"]] },
  exceptions: [
    // genuinely closed — this one DOES move dates
    { date: "2027-04-09", working: false, name: "Good Friday" },
    // Q6: advisory only — must NOT move anything, only warn
    { from: "2027-04-05", to: "2027-04-07", working: true, advisory: true,
      name: "tail of the dormant window" }
  ]
}];

const tasks = [
  { id: 1,  name: "Phase 1 — Canopy & soil", isSummary: true },
  { id: 2,  name: "Site survey & marking",   parentId: 1, durationMin: 2*D, calendarId: "std", pctComplete: 100 },
  { id: 3,  name: "Sheet-mulch the beds",    parentId: 1, durationMin: 5*D, calendarId: "std", pctComplete: 60 },
  { id: 4,  name: "Bare-root order arrives", parentId: 1, durationMin: 0, isMilestone: true, calendarId: "std",
             constraintType: "SNET", constraintDate: "2027-04-12T08:00:00" },
  { id: 5,  name: "Plant canopy trees (12)", parentId: 1, durationMin: 3*D, calendarId: "std" },
  { id: 6,  name: "Plant shrub layer (24)",  parentId: 1, durationMin: 4*D, calendarId: "std" },
  { id: 7,  name: "Mulch & water in",        parentId: 1, durationMin: 2*D, calendarId: "std" },
  { id: 8,  name: "Deer protection",         parentId: 1, durationMin: 2*D, calendarId: "std",
             deadline: "2027-04-25T16:00:00" },
  { id: 9,  name: "Settle-in period",        parentId: 1, durationMin: 3*1440, elapsed: true, calendarId: "std" },
  { id: 10, name: "Phase 2 — Understory",    isSummary: true },
  { id: 11, name: "Soil test & amend",       parentId: 10, durationMin: 1*D, calendarId: "std" },
  { id: 12, name: "Plant herb layer (48)",   parentId: 10, durationMin: 5*D, calendarId: "std" },
  { id: 13, name: "Divide groundcover",      parentId: 10, durationMin: 3*D, calendarId: "std" },
  { id: 14, name: "Final inspection",        parentId: 10, durationMin: 1*D, calendarId: "std",
             constraintType: "FNLT", constraintDate: "2027-05-10T16:00:00" },
  { id: 15, name: "Season complete",         parentId: 10, durationMin: 0, isMilestone: true, calendarId: "std" }
];

const links = [
  { predId: 2,  succId: 3,  type: "FS" },
  { predId: 3,  succId: 5,  type: "FS" },
  { predId: 4,  succId: 5,  type: "FS" },
  { predId: 5,  succId: 6,  type: "FS" },
  { predId: 6,  succId: 7,  type: "SS", lagMin: 1*D },   // start 1d after shrubs start
  { predId: 6,  succId: 8,  type: "FS" },
  { predId: 8,  succId: 9,  type: "FS" },
  { predId: 7,  succId: 13, type: "FF" },                // finish together
  { predId: 11, succId: 12, type: "FS", lagMin: -1*D },  // lead: overlap by a day
  { predId: 12, succId: 13, type: "FS" },
  { predId: 13, succId: 14, type: "FS" },
  { predId: 14, succId: 15, type: "FS" },
  { predId: 9,  succId: 15, type: "SF" }
];

const FIXTURE = { tasks, links, calendars, projectStart: START, D, START };
g.PC1_FIXTURE = FIXTURE;
if (typeof module !== "undefined" && module.exports) module.exports = FIXTURE;
})(typeof globalThis !== "undefined" ? globalThis : this);
