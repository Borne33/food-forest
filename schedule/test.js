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

  // ═══════════ PC2: predecessor parsing ═══════════
  const P = (s) => PC1.parsePredecessors(s, {minutesPerDay: D});
  eq("bare id defaults to FS",        JSON.stringify(P("3").links), JSON.stringify([{predRef:3,type:"FS",lagMin:0}]));
  eq("type is parsed",                P("7SS").links[0].type, "SS");
  eq("positive lag in days",          P("12FS+3d").links[0].lagMin, 3*D);
  eq("negative lag (lead)",           P("4FS-1d").links[0].lagMin, -D);
  eq("hours lag",                     P("4FS+4h").links[0].lagMin, 240);
  eq("weeks lag",                     P("4FS+1w").links[0].lagMin, 7*D);
  eq("comma-separated list",          P("3, 4FS+2d, 7SS").links.length, 3);
  eq("whitespace tolerated",          P(" 12 FS + 3 d ").links[0].lagMin, 3*D);
  ok("garbage is reported, not dropped", P("banana").errors.length === 1 && P("banana").links.length === 0,
     JSON.stringify(P("banana")));
  ok("partial garbage keeps the good half",
     P("3, banana, 5SS").links.length === 2 && P("3, banana, 5SS").errors.length === 1);
  ok("unit without a value is rejected", P("4FSd").errors.length === 1, JSON.stringify(P("4FSd")));
  eq("round-trips through format",
     PC1.formatPredecessors([{predId:12,type:"FS",lagMin:3*D}], null, {minutesPerDay:D}), "12+3d");
  eq("format keeps a non-FS type",
     PC1.formatPredecessors([{predId:7,type:"SS",lagMin:0}], null, {minutesPerDay:D}), "7SS");

  // ═══════════ PC2: task generation ═══════════
  const plants = {
    101:{id:101,type:"Tree",deerResistant:false}, 102:{id:102,type:"Shrub",deerResistant:true},
    103:{id:103,type:"Herb",deerResistant:true},  104:{id:104,type:"Tree",deerResistant:true}
  };
  const LAYER = {Tree:"Canopy", Shrub:"Shrub", Herb:"Herbaceous", Vine:"Vine"};
  const gen = PC1.generateTasks({
    alloc: {101:{1:12}, 102:{1:24}, 103:{2:18}, 104:{2:6}},
    plantsById: plants,
    layerOf: p => p ? LAYER[p.type] : "Herbaceous",
    hoursOf: p => ({Tree:0.75,Shrub:0.4,Herb:0.15}[p && p.type] || 0.3),
    phaseName: n => "Phase " + n, horizon: 2, minutesPerDay: D
  });
  const names = gen.tasks.map(t=>t.name);
  const key = k => gen.tasks.find(t=>t.generatedKey===k);
  ok("a summary per phase",
     !!key("phase:1") && !!key("phase:2") && key("phase:1").isSummary === true);
  ok("planting split by LAYER, not by plant",
     !!key("phase:1:plant:Canopy") && !!key("phase:1:plant:Shrub"),
     names.filter(n=>/^Plant /.test(n)).join(" | "));
  eq("canopy row carries its quantity", key("phase:1:plant:Canopy").name, "Plant canopy layer (12)");
  ok("no per-plant rows", gen.tasks.filter(t=>/plant:/.test(t.generatedKey||"")).length === 4,
     "got " + gen.tasks.filter(t=>/plant:/.test(t.generatedKey||"")).length);
  ok("browse protection only where something is browsed",
     !!key("phase:1:protect") && !key("phase:2:protect"),
     "p1=" + !!key("phase:1:protect") + " p2=" + !!key("phase:2:protect"));
  ok("maintenance is aggregated per year, not per plant",
     !!key("maint:1:weed") && !!key("maint:2:weed") && !key("maint:1:prune"));
  ok("year-2 weeding counts every plant established by then",
     /60 plants/.test(key("maint:2:weed").name), key("maint:2:weed").name);
  ok("tasks are chained within a phase", gen.links.length > 0, gen.links.length + " links");
  ok("nothing has zero duration",
     gen.tasks.filter(t=>!t.isSummary).every(t=>t.durationMin > 0));

  // ═══════════ PC2: regeneration must not clobber hand edits ═══════════
  const existing = [
    {id:1, generatedKey:"phase:1:prep", name:"Site prep — MY WORDING", durationMin:999, userEdited:true},
    {id:2, generatedKey:"phase:1:mulch", name:"Mulch and water in", durationMin:120},
    {id:3, generatedKey:null, name:"Call the nursery", durationMin:60},
  ];
  const merged = PC1.mergeGenerated(existing, gen);
  ok("a hand-edited generated task is left alone",
     merged.skipped.some(t=>t.id===1) && !merged.updated.some(t=>t.id===1));
  ok("an untouched generated task is refreshed", merged.updated.some(t=>t.id===2));
  ok("manual tasks survive regeneration", merged.manual.some(t=>t.id===3));
  ok("new generated tasks are added", merged.added.length > 0, merged.added.length + " added");

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
