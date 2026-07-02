#!/usr/bin/env python3
"""
Populate plants.images (and append photo sources) from Wikimedia Commons.

For each plant it reads the ordered media list of the species' Wikipedia page,
skips SVG status icons / range maps, and keeps up to 3 photos — the lead image
(usually the whole plant) plus images whose captions mention an edible part
(fruit / flower / nut / seed / leaf / bark / root...). Each photo's Commons file
page (which carries author + license) is added to the plant's `sources`.

Usage:
    python3 fetch_images.py             # all plants missing images
    python3 fetch_images.py --force     # refetch all
    python3 fetch_images.py --limit 5   # first N (testing)
"""
import argparse, json, sys, time, urllib.parse, urllib.request
import foodforest_import as ff

MEDIA = "https://en.wikipedia.org/api/rest_v1/page/media-list/"
COMMONS = "https://commons.wikimedia.org/wiki/"
MAX_IMAGES = 3
EXCLUDE = ("range_map", "_map_", "status_", "distribution", "locator", "map.",
           "commons-logo", "wikispecies", "question_book", "edit-", "oojs",
           "loudspeaker", "gnome-", "increase", "decrease")
EDIBLE_KW = ("fruit", "flower", "nut", "seed", "leaf", "leaves", "berr", "bark",
             "root", "tuber", "pod", "cone", "shoot", "acorn", "foliage")


def media_list(title):
    url = MEDIA + urllib.parse.quote(title.replace(" ", "_"))
    req = urllib.request.Request(url, headers={
        "User-Agent": "food-forest-planner/1.0 (native plant education; contact via github.com/Borne33)"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode()).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(3 * (attempt + 1))  # 3,6,9,12s backoff
                continue
            raise


def pick_images(items):
    photos = []
    for it in items:
        if it.get("type") != "image":
            continue
        title = it.get("title", "")            # "File:Foo.jpg"
        low = title.lower()
        if low.endswith(".svg") or any(x in low for x in EXCLUDE):
            continue
        srcset = it.get("srcset") or []
        if not srcset:
            continue
        src = srcset[0]["src"]
        if src.startswith("//"):
            src = "https:" + src
        cap = ((it.get("caption") or {}).get("text") or "").strip()
        photos.append({"file": title, "caption": cap, "url": src})
    if not photos:
        return []
    lead, rest = photos[0], photos[1:]
    edible = [p for p in rest if any(k in p["caption"].lower() for k in EDIBLE_KW)]
    other = [p for p in rest if p not in edible]
    return ([lead] + edible + other)[:MAX_IMAGES]


def to_records(picks):
    """Build (images_json, photo_sources) from picked images."""
    images, sources = [], []
    for p in picks:
        fname = p["file"].split(":", 1)[-1]
        pretty = fname.rsplit(".", 1)[0].replace("_", " ")
        commons = COMMONS + urllib.parse.quote(p["file"].replace(" ", "_"))
        label = p["caption"] or pretty
        images.append({"url": p["url"], "title": label, "source": commons})
        short = (label[:60] + "…") if len(label) > 60 else label
        sources.append(["Photo — " + short, commons])
    return images, sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="refetch even if images exist")
    ap.add_argument("--limit", type=int, default=0, help="only first N plants")
    args = ap.parse_args()
    env = ff.load_env()

    rows = ff.supabase_request(env, "GET", "plants?select=id,common,sci,images,sources&order=id") or []
    if args.limit:
        rows = rows[:args.limit]

    done = fail = skip = 0
    for r in rows:
        if r.get("images") and not args.force:
            skip += 1
            continue
        try:
            picks = pick_images(media_list(r["sci"]))
            if not picks:  # try common name as fallback
                picks = pick_images(media_list(r["common"]))
        except Exception as e:
            print(f"  ✗ {r['common']}: {e}")
            fail += 1
            time.sleep(0.3)
            continue
        if not picks:
            print(f"  – {r['common']}: no usable images")
            fail += 1
            time.sleep(0.3)
            continue
        images, photo_sources = to_records(picks)
        # merge photo sources into existing, de-duped by url
        existing = r.get("sources") or []
        have = {s[1] for s in existing if isinstance(s, list) and len(s) == 2}
        merged = existing + [s for s in photo_sources if s[1] not in have]
        ff.supabase_request(env, "PATCH", f"plants?id=eq.{r['id']}",
                            body={"images": images, "sources": merged},
                            extra_headers={"Prefer": "return=minimal"})
        print(f"  ✓ {r['common']}: {len(images)} image(s)")
        done += 1
        time.sleep(0.8)

    print(f"\ndone: {done} updated, {skip} skipped (had images), {fail} without images")


if __name__ == "__main__":
    main()
