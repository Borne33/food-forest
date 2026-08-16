#!/usr/bin/env python3
"""
Probe which seeded vendors expose a PUBLIC product feed (SHOPS_PLAN.md D4.1).

Shopify, Square-hosted and WooCommerce stores publish machine-readable product
endpoints intended for client use. Reading those is a documented interface, not
scraping — it is the polite way to keep inventory fresh.

For every vendor with a URL this checks, in order:
  1. robots.txt — and SKIPS any path robots disallows. Non-negotiable.
  2. /products.json           (Shopify)
  3. /collections/all/products.json (Shopify, when the root is a landing page)
  4. /wp-json/wc/store/products    (WooCommerce Store API, public)

One request per candidate, 1.5 s apart, honest User-Agent. Results go to
importer/vendors/feed_probe.json so this never needs re-running blind.

Usage: python3 probe_feeds.py [--limit N]
"""
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "vendors" / "feed_probe.json"
UA = "native-food-forest-planner/1.0 (+https://borne33.github.io/food-forest/; contact via site)"

CANDIDATES = [
    ("shopify_root", "/products.json?limit=5"),
    ("shopify_all", "/collections/all/products.json?limit=5"),
    ("woocommerce", "/wp-json/wc/store/products?per_page=5"),
]


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def robots_rules(origin):
    """Return the list of Disallow paths that apply to us (User-agent: *)."""
    try:
        _, txt = get(origin + "/robots.txt", timeout=12)
    except Exception:
        return []          # no robots.txt = nothing disallowed
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


def probe(url):
    p = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    origin = p.scheme + "://" + p.netloc
    out = {"origin": origin, "robots_disallow": None, "feed": None,
           "kind": None, "count": None, "error": None, "sample": None}
    try:
        rules = robots_rules(origin)
        out["robots_disallow"] = rules
    except Exception as e:      # noqa: BLE001
        rules = []
    time.sleep(1.5)

    for kind, path in CANDIDATES:
        bare = path.split("?")[0]
        if blocked(bare, rules):
            out["error"] = "robots.txt disallows " + bare
            continue
        try:
            status, body = get(origin + path)
        except urllib.error.HTTPError as e:
            out["error"] = "HTTP %s on %s" % (e.code, bare)
            time.sleep(1.5)
            continue
        except Exception as e:  # noqa: BLE001
            out["error"] = "%s on %s" % (type(e).__name__, bare)
            time.sleep(1.5)
            continue
        time.sleep(1.5)
        try:
            data = json.loads(body)
        except ValueError:
            out["error"] = "not JSON on " + bare
            continue
        items = data.get("products") if isinstance(data, dict) else data
        if isinstance(items, list) and items:
            out.update(feed=origin + bare, kind=kind, count=len(items), error=None)
            first = items[0]
            out["sample"] = first.get("title") or first.get("name")
            return out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    vendors = json.loads((HERE / "vendors" / "seed_vendors.json").read_text())
    todo = [v for v in vendors if v.get("url")][: args.limit]
    results = {}
    for v in todo:
        r = probe(v["url"])
        results[v["slug"]] = r
        flag = ("FEED %s (%s)" % (r["kind"], r["sample"])) if r["feed"] else (r["error"] or "no feed")
        print("%-34s %s" % (v["slug"][:34], flag))
    OUT.write_text(json.dumps(results, indent=2) + "\n")
    hits = [k for k, r in results.items() if r["feed"]]
    print("\n%d of %d vendors expose a public product feed: %s"
          % (len(hits), len(todo), ", ".join(hits) or "none"))
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
