/* PC5 — MS Project XML round-trip test. Runs in the browser (no Node here): it
   fetches index.html, pulls out the <script id="pc5-xml"> block VERBATIM and
   evals it, so the code under test is exactly the code that ships.

   Usage:  await PC5_TEST.run("/food-forest/index.html")   -> {passed, failed, results}  */
(function(g){
"use strict";
const D = 480;

async function loadXml(indexUrl){
  const html = await (await fetch(indexUrl + (indexUrl.includes("?")?"&":"?") + "cb=" + Date.now())).text();
  const m = html.match(/<script id="pc5-xml">([\s\S]*?)<\/script>/);
  if (!m) throw new Error("pc5-xml block not found in " + indexUrl);
  const sandbox = {};
  new Function("globalThis", "module", m[1]).call(sandbox, sandbox, undefined);
  if (!sandbox.PC5) throw new Error("the block did not export PC5");
  return sandbox.PC5;
}

/* A deliberately awkward project: every link type, a lead, a lag, a milestone,
   two levels of hierarchy, each constraint that carries a date, a deadline,
   notes with characters XML cares about, and a baseline. */
function fixture(){
  const iso = s => new Date(s);
  const tasks = [
    {id:1, name:"Phase 1 — Canopy & soil", isSummary:true,  outlineLevel:1, wbs:"1"},
    {id:2, name:"Site survey <marking>",   outlineLevel:2, wbs:"1.1", parentId:1, durationMin:2*D,
     notes:'Quote "north" & south edge'},
    {id:3, name:"Sheet-mulch the beds",    outlineLevel:2, wbs:"1.2", parentId:1, durationMin:5*D},
    {id:4, name:"Bare-root order arrives", outlineLevel:2, wbs:"1.3", parentId:1, durationMin:0,
     isMilestone:true, constraintType:"SNET", constraintDate:iso("2027-04-05T08:00:00")},
    {id:5, name:"Plant canopy (12)",       outlineLevel:2, wbs:"1.4", parentId:1, durationMin:3*D,
     pctComplete:40, deadline:iso("2027-04-30T16:00:00")},
    {id:6, name:"Phase 2 — Understory",    isSummary:true, outlineLevel:1, wbs:"2"},
    {id:7, name:"Soil test & amend",       outlineLevel:2, wbs:"2.1", parentId:6, durationMin:1*D,
     constraintType:"FNLT", constraintDate:iso("2027-05-20T16:00:00")},
    {id:8, name:"Divide groundcover",      outlineLevel:2, wbs:"2.2", parentId:6, durationMin:3*D,
     elapsed:true},
    {id:9, name:"Final inspection",        outlineLevel:2, wbs:"2.3", parentId:6, durationMin:1*D,
     constraintType:"MSO", constraintDate:iso("2027-05-24T08:00:00")},
  ];
  const links = [
    {predId:2, succId:3, type:"FS", lagMin:0},
    {predId:3, succId:5, type:"FS", lagMin:2*D},      // +2d lag
    {predId:4, succId:5, type:"FS", lagMin:0},
    {predId:5, succId:7, type:"SS", lagMin:1*D},
    {predId:7, succId:8, type:"FF", lagMin:0},
    {predId:8, succId:9, type:"SF", lagMin:-1*D},     // a lead
  ];
  // dates the exporter writes; any plausible set will do, they only have to survive
  const dates = {};
  let t = new Date("2027-04-01T08:00:00");
  tasks.forEach((x,i)=>{
    const st = new Date(t.getTime() + i*86400000);
    const fi = new Date(st.getTime() + Math.max(1,(x.durationMin||D)/D)*86400000);
    dates[x.id] = {start:st, finish:fi, critical:i%3===0};
  });
  const baseline = {};
  tasks.forEach(x=>{ baseline[x.id] = {
    start: dates[x.id].start,
    finish: new Date(dates[x.id].finish.getTime() - 86400000),   // baseline a day earlier
    durationMin: x.durationMin||0 }; });
  return {tasks, links, dates, baseline};
}

function run(PC5){
  const results = [];
  const ok = (name, cond, detail) => results.push({name, pass: !!cond, detail: detail||""});
  const eq = (name, a, b) => ok(name, a===b, a===b ? "" : `got ${a}, want ${b}`);

  const F = fixture();
  const xml = PC5.buildMSPDI({
    name:"Round trip", projectStart:new Date("2027-04-01T08:00:00"),
    tasks:F.tasks, links:F.links,
    schedule:id=>F.dates[id]||{},
    baselineOf:t=>F.baseline[t.id]||null,
    calendar:{name:"Standard (7-day)", workweek:{sun:[["08:00","16:00"]],mon:[["08:00","16:00"]],
      tue:[["08:00","16:00"]],wed:[["08:00","16:00"]],thu:[["08:00","16:00"]],
      fri:[["08:00","16:00"]],sat:[["08:00","16:00"]]}, exceptions:[]},
    // an 8h/day, 7-day working measure — the same shape the app hands it
    workingMinutes:(a,b)=>Math.max(0, Math.round((b-a)/86400000))*D
  });

  ok("output is XML", /^<\?xml/.test(xml));
  ok("declares the MSPDI namespace", xml.indexOf('xmlns="http://schemas.microsoft.com/project"')>0);
  ok("no raw < in a task name", xml.indexOf("<Name>Site survey <marking></Name>")<0);
  ok("the name was escaped instead", xml.indexOf("Site survey &lt;marking&gt;")>0);
  ok("dates are local wall-clock, not UTC with a Z", !/<Start>[^<]*Z<\/Start>/.test(xml));

  const P = PC5.parseMSPDI(xml);

  eq("every task survives", P.tasks.length, F.tasks.length);
  eq("every link survives", P.links.length, F.links.length);
  eq("the project name survives", P.name, "Round trip");
  eq("the project start survives", P.projectStart && P.projectStart.getTime(),
     new Date("2027-04-01T08:00:00").getTime());

  const byName = {}; P.tasks.forEach(t=>byName[t.name]=t);
  eq("an escaped name comes back intact", !!byName["Site survey <marking>"], true);
  eq("notes survive quotes and ampersands",
     byName["Site survey <marking>"].notes, 'Quote "north" & south edge');

  eq("durations survive", byName["Sheet-mulch the beds"].durationMin, 5*D);
  eq("a milestone stays a milestone", byName["Bare-root order arrives"].isMilestone, true);
  eq("a summary stays a summary", byName["Phase 1 — Canopy & soil"].isSummary, true);
  eq("a summary's duration is not carried as work", byName["Phase 1 — Canopy & soil"].durationMin, 0);
  ok("a summary is written in WORKING minutes, not wall-clock",
     /<Summary>1<\/Summary>[\s\S]{0,400}?<Duration>PT8H0M0S<\/Duration>/.test(xml),
     (xml.match(/<Summary>1<\/Summary>[\s\S]{0,400}?<Duration>[^<]*<\/Duration>/)||[""])[0].slice(-40));
  eq("elapsed durations survive", byName["Divide groundcover"].elapsed, true);
  eq("% complete survives", byName["Plant canopy (12)"].pctComplete, 40);
  eq("WBS survives", byName["Divide groundcover"].wbs, "2.2");

  eq("SNET survives", byName["Bare-root order arrives"].constraintType, "SNET");
  eq("its constraint date survives", byName["Bare-root order arrives"].constraintDate.getTime(),
     new Date("2027-04-05T08:00:00").getTime());
  eq("FNLT survives", byName["Soil test & amend"].constraintType, "FNLT");
  eq("MSO survives", byName["Final inspection"].constraintType, "MSO");
  eq("a deadline survives", byName["Plant canopy (12)"].deadline.getTime(),
     new Date("2027-04-30T16:00:00").getTime());

  // hierarchy is rebuilt from OutlineLevel + order, the only place MSPDI keeps it
  const uidOf = {}; P.tasks.forEach(t=>uidOf[t.name]=t.uid);
  eq("children hang off the right summary",
     byName["Plant canopy (12)"].parentUid, uidOf["Phase 1 — Canopy & soil"]);
  eq("the second phase's children too",
     byName["Divide groundcover"].parentUid, uidOf["Phase 2 — Understory"]);
  eq("summaries have no parent", byName["Phase 1 — Canopy & soil"].parentUid, null);

  const L = {}; P.links.forEach(l=>L[l.predUid+">"+l.succUid]=l);
  const k = (a,b)=>uidOf[a]+">"+uidOf[b];
  eq("FS survives", L[k("Site survey <marking>","Sheet-mulch the beds")].type, "FS");
  eq("SS survives", L[k("Plant canopy (12)","Soil test & amend")].type, "SS");
  eq("FF survives", L[k("Soil test & amend","Divide groundcover")].type, "FF");
  eq("SF survives", L[k("Divide groundcover","Final inspection")].type, "SF");
  eq("a positive lag survives", L[k("Sheet-mulch the beds","Plant canopy (12)")].lagMin, 2*D);
  eq("a lead (negative lag) survives", L[k("Divide groundcover","Final inspection")].lagMin, -1*D);
  eq("a zero lag stays zero", L[k("Site survey <marking>","Sheet-mulch the beds")].lagMin, 0);

  eq("the baseline comes back", P.baseline.length, F.tasks.length);
  const bl = {}; P.baseline.forEach(b=>bl[b.name]=b);
  eq("a baseline finish survives", bl["Sheet-mulch the beds"].finish.getTime(),
     F.baseline[3].finish.getTime());

  // a second trip must be a fixed point
  const xml2 = PC5.buildMSPDI({
    name:"Round trip", projectStart:P.projectStart,
    tasks:P.tasks.map((t,i)=>({...t, id:t.uid,
      parentId: t.parentUid, constraintDate:t.constraintDate, deadline:t.deadline})),
    links:P.links.map(l=>({predId:l.predUid, succId:l.succUid, type:l.type, lagMin:l.lagMin})),
    schedule:id=>{ const t=P.tasks.find(x=>x.uid===id); return t?{start:t.start, finish:t.finish}:{}; },
    baselineOf:t=>bl[t.name]||null });
  const P2 = PC5.parseMSPDI(xml2);
  eq("re-export keeps the task count", P2.tasks.length, P.tasks.length);
  eq("re-export keeps the link count", P2.links.length, P.links.length);
  eq("re-export keeps the link types",
     P2.links.map(l=>l.type).sort().join(","), P.links.map(l=>l.type).sort().join(","));
  eq("re-export keeps the lags",
     P2.links.map(l=>l.lagMin).sort((a,b)=>a-b).join(","),
     P.links.map(l=>l.lagMin).sort((a,b)=>a-b).join(","));
  eq("re-export keeps the hierarchy",
     P2.tasks.filter(t=>t.parentUid!=null).length, P.tasks.filter(t=>t.parentUid!=null).length);

  // failure modes should say what is wrong, not throw something opaque
  const throws = (fn) => { try{ fn(); return null; }catch(e){ return e.message; } };
  ok("a non-XML file is rejected clearly",
     /not valid XML/i.test(throws(()=>PC5.parseMSPDI("this is not xml"))||""),
     throws(()=>PC5.parseMSPDI("this is not xml")));
  ok("a non-MSPDI XML file is rejected clearly",
     /expected <Project>/.test(throws(()=>PC5.parseMSPDI("<foo><bar/></foo>"))||""),
     throws(()=>PC5.parseMSPDI("<foo><bar/></foo>")));
  ok("an empty project is rejected clearly",
     /no <Task>/.test(throws(()=>PC5.parseMSPDI(
       '<Project xmlns="http://schemas.microsoft.com/project"><Tasks/></Project>'))||""));

  // MSP writes a UID 0 / OutlineLevel 0 project-summary row; it is not a task
  const withRoot = xml.replace("  <Tasks>",
    "  <Tasks>\n    <Task><UID>0</UID><ID>0</ID><Name>Round trip</Name>"
    +"<OutlineLevel>0</OutlineLevel><Summary>1</Summary></Task>");
  eq("MSP's project-summary row is dropped", PC5.parseMSPDI(withRoot).tasks.length, F.tasks.length);

  /* Calendars. Dropping one is not cosmetic: without the fixture's single
     non-working day, its sheet-mulch task recomputed as Apr 07–11 instead of
     Apr 07–12, and nothing said so. */
  const calXml =
    '<Project xmlns="http://schemas.microsoft.com/project"><CalendarUID>1</CalendarUID>'
    +'<Calendars><Calendar><UID>1</UID><Name>Site week</Name><IsBaseCalendar>1</IsBaseCalendar>'
    +'<WeekDays>'
    +'<WeekDay><DayType>1</DayType><DayWorking>0</DayWorking></WeekDay>'
    +'<WeekDay><DayType>2</DayType><DayWorking>1</DayWorking><WorkingTimes>'
    +'<WorkingTime><FromTime>07:00:00</FromTime><ToTime>15:00:00</ToTime></WorkingTime>'
    +'</WorkingTimes></WeekDay>'
    +'<WeekDay><DayType>0</DayType><DayWorking>0</DayWorking><Name>Good Friday</Name>'
    +'<TimePeriod><FromDate>2027-04-09T00:00:00</FromDate><ToDate>2027-04-09T23:59:00</ToDate></TimePeriod>'
    +'</WeekDay>'
    +'</WeekDays></Calendar></Calendars>'
    +'<Tasks><Task><UID>1</UID><ID>1</ID><Name>x</Name><OutlineLevel>1</OutlineLevel>'
    +'<Duration>PT8H0M0S</Duration></Task></Tasks></Project>';
  const CP = PC5.parseMSPDI(calXml);
  ok("a calendar is read at all", !!CP.calendar, CP.calendar? CP.calendar.name : "null");
  eq("its name survives", CP.calendar.name, "Site week");
  eq("a closed day comes back closed", CP.calendar.workweek.sun.length, 0);
  eq("a working day keeps its hours", CP.calendar.workweek.mon[0].join("-"), "07:00-15:00");
  ok("a day the file never mentions defaults to working",
     CP.calendar.workweek.wed.length===1, JSON.stringify(CP.calendar.workweek.wed));
  eq("the exception comes across", CP.calendar.exceptions.length, 1);
  eq("on the right date", CP.calendar.exceptions[0].date, "2027-04-09");
  eq("and marked non-working", CP.calendar.exceptions[0].working, false);
  ok("a file with no <Calendars> reports null rather than inventing one",
     PC5.parseMSPDI('<Project xmlns="http://schemas.microsoft.com/project"><Tasks>'
       +'<Task><UID>1</UID><Name>x</Name><OutlineLevel>1</OutlineLevel></Task></Tasks></Project>').calendar === null);

  // and the calendar has to survive being written back out
  const calOut = PC5.buildMSPDI({ name:"cal", projectStart:new Date("2027-04-01T08:00:00"),
    tasks:[{id:1,name:"x",outlineLevel:1,durationMin:D}], links:[],
    schedule:()=>({start:new Date("2027-04-01T08:00:00"), finish:new Date("2027-04-01T16:00:00")}),
    calendar: CP.calendar });
  const CP2 = PC5.parseMSPDI(calOut);
  eq("a re-exported calendar keeps its closed day", CP2.calendar.workweek.sun.length, 0);
  eq("a re-exported calendar keeps its hours", CP2.calendar.workweek.mon[0].join("-"), "07:00-15:00");
  eq("a re-exported calendar keeps its exception", CP2.calendar.exceptions.length, 1);

  // an ADVISORY window must never be written as an exception — it would move
  // MSP's dates, and it never moves ours (Q6)
  const advOut = PC5.buildMSPDI({ name:"adv", projectStart:new Date("2027-04-01T08:00:00"),
    tasks:[{id:1,name:"x",outlineLevel:1,durationMin:D}], links:[], schedule:()=>({}),
    calendar:{ name:"Adv", workweek:CP.calendar.workweek,
      exceptions:[{date:"2027-05-01", working:true, advisory:true, name:"Frost window"}] } });
  ok("an advisory window is not exported as an exception", advOut.indexOf("2027-05-01")<0);

  eq("a duration parses back", PC5.parseDur("PT40H0M0S"), 2400);
  eq("a fractional duration parses back", PC5.parseDur("PT0H30M0S"), 30);

  const passed = results.filter(r=>r.pass).length;
  return { passed, failed: results.length-passed, results, xml };
}

g.PC5_TEST = {
  loadXml,
  run: async (indexUrl) => run(await loadXml(indexUrl || "/food-forest/index.html"))
};
})(typeof globalThis !== "undefined" ? globalThis : this);
