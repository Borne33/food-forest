#!/usr/bin/env python3
"""Emit the PC1 fixture as MS Project XML (MSPDI, the 2003+ schema).

Purpose: the PC1 gate says compare the engine's dates against a real scheduler.
There is no MS Project on this machine, so this produces a file ProjectLibre /
GanttProject / MSP can all open. Only the fixture is exported — the general
export is PC5.

Enum notes (MSPDI):
  link Type   0=FF 1=FS 2=SF 3=SS
  Constraint  0=ASAP 1=ALAP 2=MSO 3=MFO 4=SNET 5=SNLT 6=FNET 7=FNLT
  LinkLag is in TENTHS OF A MINUTE, so one 480-minute day = 4800.
"""
import re
import sys
from pathlib import Path

# --recompute emits the same project with NO finish dates and every task parked
# at the project start, so the importing tool must schedule it from the links and
# the calendar. That is the version that actually tests the engine — the normal
# file carries our own dates and only proves the structure is expressible.
RECOMPUTE = "--recompute" in sys.argv

HERE = Path(__file__).resolve().parent
D = 480
LINK = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
CONS = {"ASAP": 0, "ALAP": 1, "MSO": 2, "MFO": 3, "SNET": 4, "SNLT": 5, "FNET": 6, "FNLT": 7}


def iso(s):
    return s if "T" in s else s + "T08:00:00"


def dur(mins, elapsed=False):
    h, m = divmod(int(mins), 60)
    return "PT%dH%dM0S" % (h, m)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --- the engine's computed dates, so every task can carry Start/Finish ---
# GanttProject (and MPXJ generally) SKIPS any task with neither start+finish nor
# start+duration. Summaries had neither, so both were dropped and all thirteen
# children were orphaned with "source task not found".
DATES, SUMDUR = {}, {}
import csv as _csv
with open(HERE / "pc1-expected.csv") as fh:
    for row in _csv.DictReader(fh):
        DATES[int(row["ID"])] = (row["Start"].replace(" ", "T") + ":00",
                                 row["Finish"].replace(" ", "T") + ":00")
        SUMDUR[int(row["ID"])] = int(row["Dur(min)"] or 0)

# --- read the fixture straight out of fixture.js so the two cannot drift ---
src = (HERE / "fixture.js").read_text()

def js_array(name):
    i = src.index("const %s = [" % name)
    depth, j = 0, src.index("[", i)
    k = j
    while True:
        if src[k] == "[": depth += 1
        elif src[k] == "]":
            depth -= 1
            if depth == 0: break
        k += 1
    return src[j:k+1]

def objs(block):
    out, depth, start = [], 0, None
    for i, ch in enumerate(block):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: out.append(block[start:i+1])
    return out

def field(o, key, cast=str, default=None):
    m = re.search(r'\b%s\s*:\s*("([^"]*)"|[^,}\s]+)' % key, o)
    if not m: return default
    raw = m.group(2) if m.group(2) is not None else m.group(1)
    raw = raw.strip()
    if cast is bool: return raw == "true"
    if cast is int:
        expr = raw.replace("*D", "*%d" % D).replace("D", str(D))
        try: return int(eval(expr, {"__builtins__": {}}, {}))
        except Exception: return default
    return raw

tasks = objs(js_array("tasks"))
links = objs(js_array("links"))
start_m = re.search(r'const START = "([^"]+)"', src)
PROJ_START = start_m.group(1)

# --- build ---
rows, uid_of, order = [], {}, []
for t in tasks:
    tid = field(t, "id", int)
    uid_of[tid] = tid
    order.append((tid, t))

preds = {}
for l in links:
    s = field(l, "succId", int)
    preds.setdefault(s, []).append(l)

out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
       '<Project xmlns="http://schemas.microsoft.com/project">',
       '  <Name>PC1 fixture</Name>',
       '  <Title>Native Food Forest Planner — PC1 engine fixture</Title>',
       '  <ScheduleFromStart>1</ScheduleFromStart>',
       '  <StartDate>%s</StartDate>' % PROJ_START,
       '  <CalendarUID>1</CalendarUID>',
       '  <DefaultStartTime>08:00:00</DefaultStartTime>',
       '  <DefaultFinishTime>16:00:00</DefaultFinishTime>',
       '  <MinutesPerDay>480</MinutesPerDay>',
       '  <MinutesPerWeek>3360</MinutesPerWeek>',
       '  <DaysPerMonth>30</DaysPerMonth>',
       '  <Calendars><Calendar>',
       '    <UID>1</UID><Name>Standard (7-day)</Name><IsBaseCalendar>1</IsBaseCalendar>'
       '<BaseCalendarUID>-1</BaseCalendarUID>',
       '    <WeekDays>']
for dt in range(1, 8):                       # 1=Sunday .. 7=Saturday, all working
    out += ['      <WeekDay><DayType>%d</DayType><DayWorking>1</DayWorking>' % dt,
            '        <WorkingTimes><WorkingTime><FromTime>08:00:00</FromTime>'
            '<ToTime>16:00:00</ToTime></WorkingTime></WorkingTimes></WeekDay>']
# the one genuinely closed day; the ADVISORY window is deliberately NOT exported
# as an exception — it is advisory in our model and must not move MSP's dates
out += ['      <WeekDay><DayType>0</DayType><DayWorking>0</DayWorking>',
        '        <TimePeriod><FromDate>2027-04-09T00:00:00</FromDate>'
        '<ToDate>2027-04-09T23:59:00</ToDate></TimePeriod></WeekDay>',
        '    </WeekDays>',
        '  </Calendar></Calendars>',
        '  <Tasks>']

for idx, (tid, t) in enumerate(order):
    name = esc(field(t, "name", str, ""))
    is_sum = field(t, "isSummary", bool, False)
    is_ms = field(t, "isMilestone", bool, False)
    parent = field(t, "parentId", int, None)
    dmin = field(t, "durationMin", int, 0) or 0
    elapsed = field(t, "elapsed", bool, False)
    ctype = field(t, "constraintType", str, "ASAP")
    cdate = field(t, "constraintDate", str, None)
    deadline = field(t, "deadline", str, None)
    pct = field(t, "pctComplete", int, 0) or 0
    lvl = 2 if parent else 1

    st, fi = DATES.get(tid, (None, None))
    out += ['    <Task>',
            '      <UID>%d</UID><ID>%d</ID><Name>%s</Name>' % (tid, idx + 1, name),
            '      <Active>1</Active><Manual>0</Manual><Type>1</Type>',
            '      <OutlineLevel>%d</OutlineLevel>' % lvl,
            '      <Summary>%d</Summary><Milestone>%d</Milestone>' % (1 if is_sum else 0, 1 if is_ms else 0),
            '      <ConstraintType>%d</ConstraintType>' % CONS.get(ctype, 0),
            '      <CalendarUID>1</CalendarUID>']
    if RECOMPUTE:
        # start+duration only: enough for MPXJ to import, not enough to skip the maths
        out += ['      <Start>%s</Start>' % PROJ_START]
    elif st and fi:
        out += ['      <Start>%s</Start><Finish>%s</Finish>' % (st, fi)]
    if is_sum and (RECOMPUTE or (st and fi)):
        # a summary still needs a duration of its own or MPXJ treats it as empty
        out += ['      <Duration>%s</Duration><DurationFormat>7</DurationFormat>'
                % dur(SUMDUR.get(tid, 0))]
    if cdate:
        out.append('      <ConstraintDate>%s</ConstraintDate>' % iso(cdate))
    if deadline:
        out.append('      <Deadline>%s</Deadline>' % iso(deadline))
    if not is_sum:
        out += ['      <Duration>%s</Duration>' % dur(dmin),
                '      <DurationFormat>%d</DurationFormat>' % (21 if elapsed else 7),
                '      <PercentComplete>%d</PercentComplete>' % pct]
    for l in preds.get(tid, []):
        out += ['      <PredecessorLink>',
                '        <PredecessorUID>%d</PredecessorUID>' % field(l, "predId", int),
                '        <Type>%d</Type>' % LINK.get(field(l, "type", str, "FS"), 1),
                '        <LinkLag>%d</LinkLag><LagFormat>7</LagFormat>' % ((field(l, "lagMin", int, 0) or 0) * 10),
                '      </PredecessorLink>']
    out.append('    </Task>')

out += ['  </Tasks>', '</Project>']
xml = "\n".join(out) + "\n"
name = "pc1-fixture-recompute.xml" if RECOMPUTE else "pc1-fixture.xml"
(HERE / name).write_text(xml)
print("wrote %s — %d tasks, %d links, %d bytes" % (name, len(tasks), len(links), len(xml)))
