#!/usr/bin/env python3
"""
Populate plants.harvest_calendar — per-part harvest timing for the Harvest
view. Maps each edible food_type to the month numbers (1-12) when that part is
harvested, e.g. {"Flower":[5,6], "Fruit":[8,9,10]}.

Method (best-effort, reviewable on the Verify page):
  1. Parse the free-text `harvest` field into a set of months (month names,
     season words, and ranges like "late summer to fall").
  2. For each of the plant's food_types, intersect that window with a typical
     per-part window (a "prior") so different parts land in sensible, differing
     months. If the intersection is empty, keep the plant's stated window; if
     the plant has no parseable window, fall back to the part's prior.

Fill-only by default (skips plants whose harvest_calendar is already set);
pass --force to recompute all. Edible food_types only.

Usage:  python3 populate_harvest_calendar.py [--force]
"""
import re
import sys
import foodforest_import as ff

# season -> months (temperate / NY-centric, matching the app's 4-season model)
SEASON = {
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "fall": [9, 10, 11], "autumn": [9, 10, 11],
    "winter": [12, 1, 2],
}
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
FULL = {m: i + 1 for i, m in enumerate(MONTHS)}

# typical harvest window per edible food_type (the "prior")
PRIOR = {
    "Fruit":            [7, 8, 9, 10],
    "Nut/Seed":         [9, 10, 11],
    "Grain":            [8, 9, 10],
    "Leafy Green":      [4, 5, 6],
    "Vegetable":        [6, 7, 8, 9],
    "Root/Tuber/Bulb":  [9, 10, 11],
    "Herb/Spice":       [5, 6, 7, 8, 9],
    "Tea/Drink":        [5, 6, 7, 8, 9],
    "Flower":           [5, 6, 7],
    "Sap/Syrup":        [2, 3],
}


def _cyclic_range(a, b):
    """Inclusive month range a..b, wrapping across the year end."""
    out, m = [], a
    while True:
        out.append(m)
        if m == b:
            break
        m = m % 12 + 1
        if len(out) > 12:
            break
    return out


def _token_month(tok):
    tok = tok.lower()
    if tok in FULL:
        return FULL[tok]
    if tok[:3] in ABBR:
        return ABBR[tok[:3]]
    return None


def parse_window(text):
    """Return a set of month numbers described by the free-text harvest field."""
    if not text:
        return set()
    t = text.lower()
    if re.search(r"year[\s-]?round|all year|any season|year long", t):
        return set(range(1, 13))

    # collect ordered anchors: (start_month, end_month) for each token found
    anchors = []
    for mo in re.finditer(r"[a-z]+", t):
        w = mo.group(0)
        if w in SEASON:
            ms = SEASON[w]
            anchors.append((mo.start(), ms[0], ms[-1]))
        else:
            m = _token_month(w)
            if m:
                anchors.append((mo.start(), m, m))
    if not anchors:
        return set()

    months = set()
    # if the text reads like a range between the first and last anchor, fill it
    if len(anchors) >= 2 and re.search(r"\b(to|through|thru|until|into|[-–—])\b|[-–—]", t):
        months |= set(_cyclic_range(anchors[0][1], anchors[-1][2]))
    for _, a, b in anchors:
        months |= set(_cyclic_range(a, b))
    return months


def calendar_for(harvest, food_types):
    win = parse_window(harvest)
    cal = {}
    for ft in (food_types or []):
        prior = PRIOR.get(ft)
        if not prior:
            continue
        if win:
            inter = sorted(set(win) & set(prior))
            months = inter if inter else sorted(win)
        else:
            months = list(prior)
        if months:
            cal[ft] = months
    return cal


def main():
    force = "--force" in sys.argv
    env = ff.load_env()
    rows = ff.supabase_request(
        env, "GET",
        "plants?select=id,sci,harvest,food_types,harvest_calendar&order=id") or []
    n = 0
    for r in rows:
        if not force and r.get("harvest_calendar"):
            continue  # fill-only
        cal = calendar_for(r.get("harvest"), r.get("food_types"))
        if not cal and not force:
            continue  # nothing to set (non-edible)
        ff.supabase_request(
            env, "PATCH", "plants?id=eq.%d" % r["id"],
            body={"harvest_calendar": cal},
            extra_headers={"Prefer": "return=minimal"})
        n += 1
    print("set harvest_calendar on %d plants (of %d)" % (n, len(rows)))


if __name__ == "__main__":
    main()
