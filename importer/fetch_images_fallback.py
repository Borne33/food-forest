#!/usr/bin/env python3
"""Fallback image fetch for plants still missing images.

For each plant with no images it tries, in order:
  1. Wikipedia media-list on the scientific name (retries 429).
  2. Wikipedia media-list on the base binomial (strips var./ssp./subsp.).
  3. Wikipedia media-list on the common name.
  4. Wikimedia Commons File-namespace SEARCH on the base binomial, then sci
     (finds photos even when no Wikipedia article exists).

Usage: python3 fetch_images_fallback.py
"""
import json, re, time, urllib.parse, urllib.request
import foodforest_import as ff
from fetch_images import media_list, pick_images, to_records, EXCLUDE, MAX_IMAGES

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "food-forest-planner/1.0 (native plant education; contact via github.com/Borne33)"}


def base_binomial(sci):
    # drop var./ssp./subsp./f. and anything after
    b = re.split(r"\s+(?:var\.|ssp\.|subsp\.|f\.)\s+", sci)[0]
    parts = b.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else b


def commons_search(term):
    """Search Commons File namespace; return picks in pick_images() shape."""
    q = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": term, "gsrnamespace": "6", "gsrlimit": "12",
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "640",
    }
    url = COMMONS_API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(3 * (attempt + 1)); continue
            raise
    pages = (data.get("query") or {}).get("pages") or {}
    # keep insertion/search order via 'index'
    items = sorted(pages.values(), key=lambda p: p.get("index", 999))
    picks = []
    for p in items:
        title = p.get("title", "")            # "File:Foo.jpg"
        low = title.lower()
        if not (low.endswith(".jpg") or low.endswith(".jpeg") or low.endswith(".png")):
            continue
        if any(x in low for x in EXCLUDE):
            continue
        ii = (p.get("imageinfo") or [{}])[0]
        src = ii.get("thumburl") or ii.get("url")
        if not src:
            continue
        meta = ii.get("extmetadata") or {}
        cap = ""
        for k in ("ImageDescription", "ObjectName"):
            v = (meta.get(k) or {}).get("value")
            if v:
                cap = re.sub(r"<[^>]+>", "", v).strip(); break
        picks.append({"file": title, "caption": cap, "url": src})
    return picks[:MAX_IMAGES]


def main():
    env = ff.load_env()
    rows = ff.supabase_request(
        env, "GET", "plants?select=id,common,sci,images,sources&order=id") or []
    todo = [r for r in rows if not r.get("images")]
    print(f"{len(todo)} plant(s) still missing images.\n")
    done = fail = 0
    for r in todo:
        sci, common = r["sci"], r["common"]
        base = base_binomial(sci)
        picks = []
        # 1-3: Wikipedia media-list on sci / base / common
        for title in [sci] + ([base] if base != sci else []) + [common]:
            try:
                picks = pick_images(media_list(title))
            except Exception:
                picks = []
            if picks:
                via = f"wiki:{title}"; break
        # 4: Commons file search
        if not picks:
            for term in [base, sci]:
                try:
                    picks = commons_search(term)
                except Exception as e:
                    picks = []
                if picks:
                    via = f"commons:{term}"; break
        if not picks:
            print(f"  – {common} ({sci}): still none")
            fail += 1; time.sleep(0.5); continue
        images, photo_sources = to_records(picks)
        existing = r.get("sources") or []
        have = {s[1] for s in existing if isinstance(s, list) and len(s) == 2}
        merged = existing + [s for s in photo_sources if s[1] not in have]
        ff.supabase_request(env, "PATCH", f"plants?id=eq.{r['id']}",
                            body={"images": images, "sources": merged},
                            extra_headers={"Prefer": "return=minimal"})
        print(f"  ✓ {common}: {len(images)} image(s)  [{via}]")
        done += 1; time.sleep(1.0)
    print(f"\ndone: {done} updated, {fail} still without images")


if __name__ == "__main__":
    main()
