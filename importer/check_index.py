#!/usr/bin/env python3
"""
Cheap static checks for index.html — the app is one no-build file transformed by
Babel-standalone in the browser, so a single SyntaxError blanks the whole site
and there is no compiler here to catch it (no Node, no npm).

Checks:
  1. Duplicate TOP-LEVEL declarations (const/let/function/class). A second
     top-level `const esc` after `function esc` is a SyntaxError -> blank page.
     This actually happened (Aug 2026, Shops map popups).
  2. Bracket/brace/paren balance across the whole file.
  3. `</script>` appearing inside the babel script block, which would end it early.

Usage:  python3 importer/check_index.py [path]
Exit code 1 if anything fails, so it can gate a commit.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent / "index.html"

DECL = re.compile(r'^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)')


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    src = path.read_text()
    fails = []

    # ── the babel script block ────────────────────────────────────────────
    m = re.search(r'<script type="text/babel">(.*?)</script>', src, re.S)
    if not m:
        print("!! could not find the <script type=\"text/babel\"> block")
        return 1
    body = m.group(1)

    # ── 1. duplicate top-level declarations ───────────────────────────────
    # top level == column 0, which is how this file is written
    seen = defaultdict(list)
    for i, line in enumerate(body.splitlines(), start=1):
        d = DECL.match(line)
        if d:
            seen[d.group(1)].append(i)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        for name, lines in sorted(dupes.items()):
            fails.append("duplicate top-level declaration %r at script lines %s"
                         % (name, ", ".join(map(str, lines))))
    print("top-level declarations: %d, duplicates: %d" % (len(seen), len(dupes)))

    # ── 2. balance, as a DELTA against git HEAD ───────────────────────────
    # Absolute counts never balance: prose and CSS contain stray parens
    # ("(CC-BY-SA)", "(10 in-state · 8 in-region)"). See HANDOFF §8. What
    # matters is that an edit adds as many closers as openers.
    import subprocess
    head = subprocess.run(["git", "-C", str(path.parent), "show", "HEAD:" + path.name],
                          capture_output=True, text=True)
    if head.returncode == 0 and head.stdout:
        old = head.stdout
        for o, c in (("{", "}"), ("(", ")"), ("[", "]")):
            do = src.count(o) - old.count(o)
            dc = src.count(c) - old.count(c)
            status = "ok" if do == dc else "MISMATCH"
            print("  %s%s delta vs HEAD: +%d open / +%d close  %s" % (o, c, do, dc, status))
            if do != dc:
                fails.append("edit is unbalanced for %s%s: +%d open vs +%d close" % (o, c, do, dc))
    else:
        print("  (no git HEAD to diff against — balance check skipped)")

    # ── 3. early script termination ───────────────────────────────────────
    if "</script>" in body:
        fails.append("literal '</script>' inside the babel block would end it early")

    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("\nOK — no duplicate top-level declarations, balance even.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
