#!/usr/bin/env python3
"""
Probe which vendors expose a PUBLIC product feed, and on what platform
(SHOPS_PLAN.md D4.1, STAGE_GATES.md S9 item 2).

Shopify, WooCommerce and Square publish machine-readable product endpoints
intended for client use. Reading those is a documented interface, not scraping —
it is the polite way to keep inventory fresh.

Two passes per vendor, both cheap:
  1. robots.txt          — and SKIP any path robots disallows. Non-negotiable.
  2. the homepage        — to identify the platform from its own markers
  3. feed candidates     — only the ones that platform could plausibly serve

Recording the PLATFORM separately from the FEED is the point of the rewrite.
"Shopify with products.json switched off" and "a hand-built HTML site with no
catalogue at all" both showed up as a bare null before, and they call for
completely different follow-ups: ask the owner to flip a setting, versus never
ask at all.

REQUEST BUDGET: at most 5 requests per vendor per run, 1.5 s apart, honest
User-Agent, no crawling of anything but these fixed paths. That is the number to
weigh in S9 item 3.

Usage:
  python3 probe_feeds.py                 # live vendors table
  python3 probe_feeds.py --limit 5       # a taste first
  python3 probe_feeds.py --seed          # the seed JSON instead of the DB
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from vendors_seed import load_env, supabase  # noqa: E402

OUT = HERE / "vendors" / "feed_probe.json"
UA = ("native-food-forest-planner/1.0 "
      "(+https://borne33.github.io/food-forest/; contact via site)")
PAUSE = 1.5
MAX_REQ_PER_VENDOR = 5

# Platform fingerprints, cheapest and most specific first. These are markers the
# platforms put in their own pages; none of it is guesswork about the business.
FINGERPRINTS = [
    ("shopify",     re.compile(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", re.I)),
    ("woocommerce", re.compile(r"woocommerce|wp-content/plugins/woocommerce", re.I)),
    ("square",      re.compile(r"square\.site|squareup\.com|square-web-", re.I)),
    ("squarespace", re.compile(r"squarespace\.com|static1\.squarespace", re.I)),
    ("wix",         re.compile(r"wixstatic\.com|_wixCssImports|wix\.com", re.I)),
    ("bigcommerce", re.compile(r"bigcommerce\.com|stencil-", re.I)),
]

# Which feed paths are worth trying for each platform. Nothing is tried against a
# platform that cannot serve it — that is the difference between 5 requests and 15.
FEEDS = {
    "shopify":     [("shopify_root", "/products.json?limit=5"),
                    ("shopify_all",  "/collections/all/products.json?limit=5")],
    "woocommerce": [("woocommerce",  "/wp-json/wc/store/products?per_page=5")],
    # Square Online has no documented public catalogue endpoint; the storefront is
    # rendered server-side. Recorded as a platform, never fetched beyond the page.
    "square":      [],
    "squarespace": [],
    "wix":         [],
    "bigcommerce": [("bigcommerce",  "/api/storefront/products?limit=5")],
    None:          [("shopify_root", "/products.json?limit=5"),
                    ("woocommerce",  "/wp-json/wc/store/products?per_page=5")],
}


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def robots_rules(origin):
    """The Disallow paths that apply to User-agent: *."""
    try:
        _, txt = get(origin + "/robots.txt", timeout=12)
    except Exception:                       # noqa: BLE001
        return []                           # no robots.txt = nothing disallowed
    rules, applies = [], False
    for line in txt.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            applies = v == "*"
        elif k == "disallow" and applies and v:
            rules.append(v)
    return rules


def blocked(path, rules):
    return any(path.startswith(r) for r in rules)


def identify(origin, budget):
    """Platform from the homepage's own markers. One request."""
    if budget[0] <= 0:
        return None, "request budget spent"
    budget[0] -= 1
    try:
        _, body = get(origin, timeout=20)
    except urllib.error.HTTPError as e:
        return None, "HTTP %s on the homepage" % e.code
    except Exception as e:                  # noqa: BLE001
        return None, "%s on the homepage" % type(e).__name__
    finally:
        time.sleep(PAUSE)
    head = body[:400000]
    for name, rx in FINGERPRINTS:
        if rx.search(head):
            return name, None
    return None, None


def probe(url):
    p = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    origin = p.scheme + "://" + p.netloc
    out = {"origin": origin, "robots_disallow": None, "platform": None,
           "feed": None, "kind": None, "count": None, "error": None, "sample": None}
    budget = [MAX_REQ_PER_VENDOR]

    budget[0] -= 1
    try:
        out["robots_disallow"] = robots_rules(origin)
    except Exception:                       # noqa: BLE001
        out["robots_disallow"] = []
    time.sleep(PAUSE)
    rules = out["robots_disallow"] or []

    platform, why = identify(origin, budget)
    out["platform"] = platform
    if why:
        out["error"] = why

    for kind, path in FEEDS.get(platform, FEEDS[None]):
        if budget[0] <= 0:
            break
        bare = path.split("?")[0]
        if blocked(bare, rules):
            out["error"] = "robots.txt disallows " + bare
            continue
        budget[0] -= 1
        try:
            _, body = get(origin + path)
        except urllib.error.HTTPError as e:
            out["error"] = "HTTP %s on %s" % (e.code, bare)
            time.sleep(PAUSE)
            continue
        except Exception as e:              # noqa: BLE001
            out["error"] = "%s on %s" % (type(e).__name__, bare)
            time.sleep(PAUSE)
            continue
        time.sleep(PAUSE)
        try:
            data = json.loads(body)
        except ValueError:
            out["error"] = "not JSON on " + bare
            continue
        items = data.get("products") if isinstance(data, dict) else data
        if isinstance(items, list) and items:
            first = items[0]
            out.update(feed=origin + bare, kind=kind, count=len(items), error=None,
                       sample=first.get("title") or first.get("name"))
            return out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--seed", action="store_true",
                    help="probe the seed JSON instead of the live vendors table")
    args = ap.parse_args()

    if args.seed:
        vendors = json.loads((HERE / "vendors" / "seed_vendors.json").read_text())
    else:
        env = load_env()
        vendors = supabase(env, "GET", "vendors?select=slug,name,url&order=slug") or []
    todo = [v for v in vendors if v.get("url")][: args.limit]
    print("probing %d vendors, at most %d requests each, %.1fs apart\n"
          % (len(todo), MAX_REQ_PER_VENDOR, PAUSE))

    results = {}
    for v in todo:
        r = probe(v["url"])
        results[v["slug"]] = r
        if r["feed"]:
            flag = "FEED %-12s %s" % (r["kind"], (r["sample"] or "")[:36])
        elif r["platform"]:
            flag = "%-12s no feed — %s" % (r["platform"], r["error"] or "not exposed")
        else:
            flag = "—            %s" % (r["error"] or "no platform markers")
        print("%-34s %s" % (v["slug"][:34], flag))

    OUT.write_text(json.dumps(results, indent=2) + "\n")

    feeds = {k: r for k, r in results.items() if r["feed"]}
    plats = {}
    for r in results.values():
        plats[r["platform"] or "none detected"] = plats.get(r["platform"] or "none detected", 0) + 1
    print("\n%d of %d vendors expose a public product feed:" % (len(feeds), len(todo)))
    for k, r in sorted(feeds.items()):
        print("   %-32s %s" % (k, r["feed"]))
    print("\nplatforms seen:")
    for k, n in sorted(plats.items(), key=lambda kv: -kv[1]):
        print("   %-16s %d" % (k, n))
    print("\nWrote", OUT)
    print("Requests made: at most %d" % (len(todo) * MAX_REQ_PER_VENDOR))


if __name__ == "__main__":
    main()
