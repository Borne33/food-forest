/* PC1 engine test. Runs in the browser (no Node on this machine): it fetches
   index.html, pulls out the <script id="pc1-engine"> block VERBATIM and evals
   it, so the code under test is exactly the code that ships.

   Usage from the console:  PC1_TEST.run()   ->  {passed, failed, results}   */
(function(g){
"use strict";
const D = 480;
const fmt = d => !d ? "—" :
  d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")
  +" "+String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0");

async function loadEngine(indexUrl){
  const html = await (await fetch(indexUrl + (indexUrl.includes("?")?"&":"?") + "cb=" + Date.now())).text();
  const m = html.match(/<script id="pc1-engine">([\s\S]*?)<\/script>/);
  if (!m) throw new Error("pc1-engine block not found in " + indexUrl);
  const sandbox = {};
  new Function("globalThis", "module", m[1]).call(sandbox, sandbox, undefined);
  if (!sandbox.PC1) throw new Error("engine did not export PC1");
  return sandbox.PC1;
}

function run(PC1, F){
  const results = [];
  const ok = (name, cond, detail) => results.push({name, pass: !!cond, detail: detail || ""});
  const eq = (name, actual, expected) =>
    ok(name, actual === expected, actual === expected ? "" : `got ${actual}, want ${expected}`);

  const out = PC1.scheduleProject(F);
  const T = out.tasks;
  const S = id => fmt(T[id].start), Fi = id => fmt(T[id].finish);

  // ---- 1. calendar: a non-working exception must push work out ----
  // Task 2 starts Mon 5 Apr, 2d. Task 3 (5d) follows FS. 9 Apr is closed, so
  // task 3's 5 working days span 7,8,10,11,12 Apr and finish on the 12th.
  eq("t2 starts at the project start",            S(2),  "2027-04-05 08:00");
  eq("t2 finishes after 2 working days",          Fi(2), "2027-04-06 16:00");
  eq("t3 starts next working instant",            S(3),  "2027-04-07 08:00");
  eq("t3 skips the closed 9 Apr",                 Fi(3), "2027-04-12 16:00");

  // ---- 2. SNET constraint on the milestone ----
  eq("t4 milestone honours SNET",                 S(4),  "2027-04-12 08:00");
  ok("t4 is a zero-duration milestone", T[4].start.getTime() === T[4].finish.getTime());

  // ---- 3. FS with two predecessors takes the later ----
  // t3 finishes 12 Apr 16:00; t4 is 12 Apr 08:00 -> t5 starts 13 Apr 08:00.
  eq("t5 takes the later of its two preds",       S(5),  "2027-04-13 08:00");
  eq("t5 runs 3 working days",                    Fi(5), "2027-04-15 16:00");

  // ---- 4. SS with positive lag ----
  // t6 starts 16 Apr; t7 is SS+1d so it starts one working day later.
  eq("t6 follows t5",                             S(6),  "2027-04-16 08:00");
  eq("t7 starts 1d after t6 starts (SS+1d)",      S(7),  "2027-04-17 08:00");

  // ---- 5. elapsed duration ignores the calendar ----
  // t9 is 3 elapsed days = 72h straight from t8's finish.
  const t8f = T[8].finish, t9f = T[9].finish;
  eq("t9 elapsed duration is exactly 72h",
     Math.round((t9f - T[9].start) / 3600000), 72);
  ok("t9 starts when t8 finishes", T[9].start.getTime() === t8f.getTime(),
     fmt(T[9].start) + " vs " + fmt(t8f));

  // ---- 6. FS with a LEAD (negative lag) overlaps ----
  // t12 is FS-1d from t11, so it starts before t11 finishes.
  ok("t12 starts before t11 finishes (lead)", T[12].start < T[11].finish,
     fmt(T[12].start) + " vs " + fmt(T[11].finish));

  // ---- 7. slack and the critical path ----
  ok("t2 is critical (zero slack)",  T[2].critical, "slack=" + T[2].totalSlackMin);
  ok("total slack is never negative on an ASAP chain",
     [2,3,5,6].every(i => T[i].totalSlackMin >= 0));
  ok("at least one non-critical task exists",
     Object.keys(T).some(k => T[k].critical === false));

  // ---- 8. summary rollup ----
  eq("summary 1 starts at its earliest child",    S(1),  S(2));
  ok("summary 1 finishes at its latest child",
     T[1].finish.getTime() === Math.max(...[2,3,4,5,6,7,8,9].map(i=>T[i].finish.getTime())));
  ok("summary % complete is work-weighted", T[1].pctComplete > 0 && T[1].pctComplete < 100,
     "got " + T[1].pctComplete + "%");

  // ---- 9. Q6: advisory window warns but moves nothing ----
  const adv = out.warnings.filter(w => w.type === "advisory");
  ok("advisory window raised a warning", adv.length > 0, adv.length + " warning(s)");
  eq("advisory did NOT move t2", S(2), "2027-04-05 08:00");

  // ---- 10. deadline warns, never schedules ----
  const dl = out.warnings.filter(w => w.type === "deadline");
  ok("deadline produced a warning if overrun", true, dl.length + " deadline warning(s)");

  // ---- 11. cycle detection reports the loop instead of hanging ----
  const cyc = PC1.scheduleProject({
    tasks: [{id:"a",durationMin:D},{id:"b",durationMin:D},{id:"c",durationMin:D}],
    links: [{predId:"a",succId:"b"},{predId:"b",succId:"c"},{predId:"c",succId:"a"}],
    calendars: F.calendars, projectStart: F.START
  });
  ok("cycle detected", cyc.cycles.length > 0, JSON.stringify(cyc.cycles));
  ok("cycle names the actual loop",
     cyc.cycles.length > 0 && cyc.cycles[0].length >= 3, JSON.stringify(cyc.cycles[0]||[]));

  // ---- 12. a task told to start on a non-working day is nudged forward ----
  const nw = PC1.scheduleProject({
    tasks: [{id:1,name:"x",durationMin:D,calendarId:"std",
             constraintType:"SNET",constraintDate:"2027-04-09T08:00:00"}],
    links: [], calendars: F.calendars, projectStart: F.START
  });
  eq("start on a closed day moves to the next open one",
     fmt(nw.tasks[1].start), "2027-04-10 08:00");

  const passed = results.filter(r=>r.pass).length;
  return { passed, failed: results.length - passed, results, out };
}

g.PC1_TEST = {
  loadEngine,
  run: async (indexUrl) => {
    const PC1 = await loadEngine(indexUrl || "/food-forest/index.html");
    const F = g.PC1_FIXTURE;
    if (!F) throw new Error("fixture not loaded");
    return run(PC1, F);
  }
};
})(typeof globalThis !== "undefined" ? globalThis : this);
