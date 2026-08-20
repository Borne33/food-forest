#!/usr/bin/env python3
"""Server-side parser for the S8 Shop Editor's document uploads.

The editor drops a PDF / CSV / XLSX into the private `vendor-imports` bucket and
files a `vendor_imports` row. CSV is parsed in the browser and lands already
`status='parsed'`; **PDF and XLSX sit at 'queued' until this runs.** Without it
those uploads are a dead end, which is exactly what happened between S8 shipping
and this script existing.

    python3 vendor_import.py --list                 # what is waiting
    python3 vendor_import.py                        # parse everything queued (dry run)
    python3 vendor_import.py --apply                # ...and write `parsed` back
    python3 vendor_import.py --id 12 --apply
    python3 vendor_import.py --id 12 --apply --match   # also file vendor_plants
    python3 vendor_import.py --file some.pdf        # parse a local file, write nothing

Parsing is deliberately conservative: it extracts ROWS and leaves matching to
`vendor_inventory.match()` (D5 strict). A row it cannot read becomes a skipped
line in the report rather than a guess.

Dependencies: pdfplumber (present). openpyxl is NOT installed on this machine,
so .xlsx is read with zipfile + xml.etree, per HANDOFF §9.
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vendors_seed as vs                      # load_env + supabase helpers
import vendor_inventory as vi                  # the strict D5 matcher

BUCKET = "vendor-imports"
PRICE_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")
# "Eryngium yuccifolium" / "Carex sp." / "Quercus alba var. alba"
SCI_RE = re.compile(
    r"\b([A-Z][a-z]{2,}\s+(?:x\s+)?[a-z][a-z\-]{2,}"
    r"(?:\s+(?:var\.|ssp\.|subsp\.|f\.)\s+[a-z\-]+)?)\b")
FORM_WORDS = [
    ("bare_root", ("bare root", "bare-root", "bareroot", "br ")),
    ("plug",      ("plug", "landscape plug")),
    ("potted",    ("potted", "container", "gallon", "gal", "quart", "qt", "pot")),
    ("seed",      ("seed", "packet", "pkt", "oz", "lb")),
    ("tuber",     ("tuber", "rhizome", "corm", "bulb")),
    ("live_stake",("live stake", "livestake", "cutting")),
    ("scion",     ("scion", "budwood")),
]


# ── storage ───────────────────────────────────────────────────────────────
def storage_get(env, path):
    """Download an object with the service key (bypasses the admin-only RLS)."""
    base = env["SUPABASE_URL"].rstrip("/")
    key = env["SUPABASE_SERVICE_ROLE_KEY"]
    url = base + "/storage/v1/object/" + BUCKET + "/" + urllib.parse.quote(path)
    req = urllib.request.Request(
        url, headers={"apikey": key, "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("storage %s on %s: %s"
                           % (e.code, path, e.read().decode("utf-8", "replace")[:200]))


# ── helpers ───────────────────────────────────────────────────────────────
PRICE_HDR = re.compile(r"price|cost|each|\bea\b|amount|\$", re.I)


def price_cents(text, header=None):
    """A number is only money if it is marked as money.

    Scanning any digits as a price put $2.00 and $4.00 on rows of a USDA export
    that has no prices at all. A fabricated price is worse than a missing one, so
    require either a currency symbol in the cell or a header that names it.
    """
    if not text:
        return None
    s = str(text)
    if "$" not in s and not (header and PRICE_HDR.search(header)):
        return None
    m = PRICE_RE.search(s)
    if not m:
        return None
    try:
        return int(round(float(m.group(1).replace(",", "")) * 100))
    except ValueError:
        return None


def guess_form(text):
    t = (text or "").lower()
    for form, words in FORM_WORDS:
        for w in words:
            if w in t:
                return form
    return None


# Catalogues annotate the botanical column: "Sambucus nigra Syn: S. canadensis",
# "Castanea dentata (Note: seed-grown)", "Acer rubrum; red maple". Everything from
# the first annotation marker on is commentary, not part of the name.
SCI_CUT = re.compile(r"\s*(?:\bsyn\.?\s*:|\bsyn\.\s|\(|;|\bnote\s*:|\baka\b)", re.I)


def tidy_sci(s):
    s = clean(s)
    if not s:
        return ""
    s = SCI_CUT.split(s)[0].strip(" ,;:-")
    m = SCI_RE.search(s)
    return m.group(1) if m else s


def guess_sci(text):
    m = SCI_RE.search(text or "")
    return m.group(1) if m else None


TAG_RE = re.compile(r"<[^>]+>")


def clean(s):
    # spreadsheet exports carry markup straight through: "<i>Abies alba</i>"
    s = TAG_RE.sub("", str(s or "")).replace(chr(160), " ")
    return re.sub(r"\s+", " ", s).strip()


def row_from_cells(cells, header=None):
    """Turn one table row into a listing dict, or None if it is not a listing."""
    cells = [clean(c) for c in cells if c is not None]
    if not cells:
        return None
    joined = " | ".join(cells)
    if len(joined) < 4:
        return None
    # a header or a section banner, not a product
    low = joined.lower()
    if re.match(r"^(botanical|scientific|common|species|name|item|qty|price|total)\b", low):
        return None

    sci, name = None, None
    by = {}
    if header:
        by = {clean(h).lower(): clean(c) for h, c in zip(header, cells) if h}
        for k, v in by.items():
            if not v:
                continue
            if not sci and ("botanical" in k or "scientific" in k or "latin" in k or k == "species"):
                sci = v
            if not name and "common" in k:
                name = v
    if not sci:
        sci = guess_sci(joined)
    if not name:
        # the longest non-sci cell is usually the common name
        cands = [c for c in cells if c and c != sci and not PRICE_RE.fullmatch(c or "")]
        name = max(cands, key=len) if cands else None

    if not sci and not name:
        return None
    # "TREES", "acceptedSymbol", "Search Type: ..." — banners and export metadata
    # carry neither a binomial nor a price. A common-name-only catalogue
    # (Ontario County SWCD) still has prices, so this costs no real rows.
    _h = [clean(h) for h in (header or [])]
    if not sci and not any(price_cents(c, _h[i] if i < len(_h) else None)
                           for i, c in enumerate(cells)):
        return None
    hdrs = [clean(h) for h in (header or [])]
    cents = None
    for i in range(len(cells) - 1, -1, -1):
        cents = price_cents(cells[i], hdrs[i] if i < len(hdrs) else None)
        if cents:
            break
    size = by.get("size") or by.get("pot size") or ""
    return {
        "raw_sci": tidy_sci(sci) if sci else "",
        "raw_name": name or "",
        "form": guess_form(joined) or "",
        "size": clean(size),
        "price_cents": cents,
        "unit": "per plant" if cents else "",
        "stock": "unknown",
        "source": "upload",
        "_row": joined[:300],
    }


# ── parsers ───────────────────────────────────────────────────────────────
def parse_csv(blob):
    text = blob.decode("utf-8-sig", "replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rdr = list(csv.reader(io.StringIO(text), dialect))
    if not rdr:
        return [], []
    header = rdr[0]
    out, skipped = [], []
    for cells in rdr[1:]:
        r = row_from_cells(cells, header)
        (out if r else skipped).append(r or " | ".join(cells)[:200])
    return out, skipped


def parse_xlsx(blob):
    """openpyxl is not installed — read the sheet XML directly (HANDOFF §9)."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    sheets = [n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
    if not sheets:
        return [], ["no worksheet found in the workbook"]
    root = ET.fromstring(z.read(sorted(sheets)[0]))
    rows = []
    for row in root.iter(ns + "row"):
        cells = []
        for c in row.findall(ns + "c"):
            v = c.find(ns + "v")
            txt = ""
            if c.get("t") == "s" and v is not None:
                idx = int(v.text)
                txt = shared[idx] if idx < len(shared) else ""
            elif c.get("t") == "inlineStr":
                txt = "".join(t.text or "" for t in c.iter(ns + "t"))
            elif v is not None:
                txt = v.text or ""
            cells.append(txt)
        if any(clean(x) for x in cells):
            rows.append(cells)
    if not rows:
        return [], ["workbook has no non-empty rows"]
    header, out, skipped = rows[0], [], []
    for cells in rows[1:]:
        r = row_from_cells(cells, header)
        (out if r else skipped).append(r or " | ".join(cells)[:200])
    return out, skipped


def parse_pdf(blob):
    """Tables first (HANDOFF §9 prefers extract_tables), prose lines as a fallback."""
    try:
        import pdfplumber
    except ImportError:
        return [], ["pdfplumber is not installed — cannot parse PDF"]
    out, skipped = [], []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            got_table = False
            for table in (page.extract_tables() or []):
                if not table or len(table) < 2:
                    continue
                got_table = True
                header = table[0]
                for cells in table[1:]:
                    r = row_from_cells(cells, header)
                    if r:
                        r["page"] = pno
                        out.append(r)
                    else:
                        skipped.append("p%d: %s" % (pno, " | ".join(
                            clean(c) for c in cells if c)[:200]))
            if got_table:
                continue
            # no table on this page — fall back to lines that carry a binomial
            for line in (page.extract_text() or "").split("\n"):
                line = clean(line)
                if not line or not guess_sci(line):
                    continue
                r = row_from_cells([line])
                if r:
                    r["page"] = pno
                    out.append(r)
    return out, skipped


PARSERS = [
    (lambda n, m: n.endswith(".csv") or "csv" in (m or ""), parse_csv, "csv"),
    (lambda n, m: n.endswith(".xlsx") or "spreadsheet" in (m or ""), parse_xlsx, "xlsx"),
    (lambda n, m: n.endswith(".pdf") or "pdf" in (m or ""), parse_pdf, "pdf"),
]


def parse_blob(blob, filename, mime):
    name = (filename or "").lower()
    for test, fn, kind in PARSERS:
        if test(name, (mime or "").lower()):
            rows, skipped = fn(blob)
            return kind, rows, skipped
    return None, [], ["unsupported file type: %s (%s)" % (filename, mime)]


# ── matcher bridge ────────────────────────────────────────────────────────
def match_rows(env, vendor_id, rows):
    """Run parsed rows through the strict D5 matcher and file vendor_plants."""
    plants = vi.load_plants(env)
    idx = vi.build_index(env, plants)
    linked, misses = [], []
    for it in rows:
        pid, why = vi.match(it.get("raw_sci"), it.get("raw_name"), idx, None)
        if not pid:
            misses.append({"vendor_id": vendor_id, "raw_name": it.get("raw_name"),
                           "raw_sci": it.get("raw_sci"), "form": it.get("form") or None})
            continue
        linked.append({
            "vendor_id": vendor_id, "plant_id": pid,
            "raw_name": it.get("raw_name"), "raw_sci": it.get("raw_sci"),
            "is_cultivar": False, "cultivar_name": "",
            "form": it.get("form") or None, "size": it.get("size") or "",
            "price_cents": it.get("price_cents"), "unit": it.get("unit") or None,
            "stock": it.get("stock") or "unknown", "source": "upload",
            "confidence": "high" if why in ("sci", "sci_base", "synonym") else "medium",
        })
    seen, dedup = set(), []
    for r in linked:
        k = (r["vendor_id"], r["plant_id"], r["form"], r["cultivar_name"], r["size"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    if dedup:
        vi.supabase(env, "POST",
                    "vendor_plants?on_conflict=vendor_id,plant_id,form,cultivar_name,size",
                    dedup, {"Prefer": "resolution=merge-duplicates"})
    if misses:
        vi.supabase(env, "POST", "vendor_plants_unmatched", misses,
                    {"Prefer": "return=minimal"})
    return len(dedup), len(misses)


# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show the queue and exit")
    ap.add_argument("--id", type=int, help="one vendor_imports row")
    ap.add_argument("--file", help="parse a local file instead; writes nothing")
    ap.add_argument("--apply", action="store_true", help="write `parsed` back and mark parsed")
    ap.add_argument("--match", action="store_true",
                    help="also run the matcher and file vendor_plants (implies --apply)")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    if a.match:
        a.apply = True

    if a.file:
        blob = open(a.file, "rb").read()
        kind, rows, skipped = parse_blob(blob, os.path.basename(a.file), None)
        print("parsed %s: %d row(s), %d skipped" % (kind, len(rows), len(skipped)))
        for r in rows[:15]:
            print("   %-34s %-26s %-10s %s" % ((r["raw_sci"] or "—")[:34],
                  (r["raw_name"] or "—")[:26], r["form"] or "—",
                  ("$%.2f" % (r["price_cents"] / 100)) if r["price_cents"] else "—"))
        for s in skipped[:5]:
            print("   ? %s" % s)
        return

    env = vs.load_env()
    q = "vendor_imports?select=id,vendor_id,kind,mode,filename,mime,bytes,status,storage_path"
    q += ("&id=eq.%d" % a.id) if a.id else "&status=eq.queued"
    q += "&order=id&limit=%d" % a.limit
    jobs = vs.supabase(env, "GET", q) or []

    if a.list or not jobs:
        print("%d row(s) %s" % (len(jobs), "matching" if a.id else "queued"))
        for j in jobs:
            print("   #%-4s %-34s %-6s %-8s %s" % (j["id"], (j.get("filename") or "")[:34],
                  j.get("kind"), j.get("status"), j.get("storage_path")))
        if not jobs:
            print("Nothing to do. Uploads land here from the Shop Editor's Upload tab.")
        return

    for j in jobs:
        print("\n#%s  %s" % (j["id"], j.get("filename") or j.get("storage_path")))
        if not j.get("storage_path"):
            print("   ✗ no storage_path — nothing to fetch")
            continue
        try:
            blob = storage_get(env, j["storage_path"])
        except Exception as e:
            print("   ✗ %s" % e)
            if a.apply:
                vs.supabase(env, "PATCH", "vendor_imports?id=eq.%d" % j["id"],
                            {"status": "failed", "error": str(e)[:500]},
                            {"Prefer": "return=minimal"})
            continue

        kind, rows, skipped = parse_blob(blob, j.get("filename"), j.get("mime"))
        if kind is None:
            print("   ✗ %s" % (skipped[0] if skipped else "unsupported"))
            if a.apply:
                vs.supabase(env, "PATCH", "vendor_imports?id=eq.%d" % j["id"],
                            {"status": "failed", "error": (skipped or ["unsupported"])[0][:500]},
                            {"Prefer": "return=minimal"})
            continue

        priced = sum(1 for r in rows if r.get("price_cents"))
        withsci = sum(1 for r in rows if r.get("raw_sci"))
        print("   %s → %d row(s), %d with a scientific name, %d priced, %d skipped"
              % (kind, len(rows), withsci, priced, len(skipped)))
        for r in rows[:8]:
            print("      %-34s %-24s %-10s %s" % ((r["raw_sci"] or "—")[:34],
                  (r["raw_name"] or "—")[:24], r["form"] or "—",
                  ("$%.2f" % (r["price_cents"] / 100)) if r["price_cents"] else "—"))

        if not a.apply:
            print("   (dry run — pass --apply to write)")
            continue

        payload = {"kind": kind, "rowCount": len(rows), "rows": rows[:500],
                   "skipped": skipped[:50]}
        vs.supabase(env, "PATCH", "vendor_imports?id=eq.%d" % j["id"],
                    {"parsed": payload, "status": "parsed", "error": None},
                    {"Prefer": "return=minimal"})
        print("   ✓ parsed → vendor_imports.parsed (status='parsed')")

        if a.match:
            if not j.get("vendor_id"):
                print("   ⚠ no vendor linked on this upload — skipping the matcher")
            else:
                n, m = match_rows(env, j["vendor_id"], rows)
                vs.supabase(env, "PATCH", "vendor_imports?id=eq.%d" % j["id"],
                            {"status": "applied"}, {"Prefer": "return=minimal"})
                print("   ✓ matched %d into vendor_plants, %d unmatched → review queue" % (n, m))


if __name__ == "__main__":
    main()
