#!/usr/bin/env python3
"""Run the post-import backfill pipeline in the CORRECT order.

Rule-based trait backfills run first; the authoritative USDA PLANTS pass runs
LAST so its soil_texture / soil_drainage / nf override the rule-based estimates
(re-running populate_soildims.py after USDA would otherwise clobber them).

Run this after `foodforest_import.py apply` whenever you add a batch of plants.

Order:
  1. populate_traits.py      hardiness zones + deer resistance
  2. populate_soil.py        soil N/P/K
  3. populate_soildims.py    soil texture/drainage        (rule-based)
  4. populate_fruit.py       fruit traits
  5. usda_enrich.py --apply  USDA authoritative override   (runs LAST)
  6. (optional) images       Wikimedia + Commons/iNat fallback

Usage:
  python3 backfill.py                # steps 1-5
  python3 backfill.py --with-images  # steps 1-6
  python3 backfill.py --no-usda      # rule backfills only (skip step 5)
  python3 backfill.py --usda-dry-run # step 5 as a dry-run (report, no writes)
  python3 backfill.py --plan         # print the ordered steps and exit
"""
import subprocess, sys, os, argparse, time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(step, args):
    print(f"\n{'='*64}\n▶ {step}\n  $ python3 {' '.join(args)}\n{'='*64}", flush=True)
    t = time.time()
    rc = subprocess.run([PY] + args, cwd=HERE).returncode
    dt = time.time() - t
    if rc != 0:
        print(f"✗ {step} exited {rc} after {dt:.0f}s", flush=True)
        return False
    print(f"✓ {step} done ({dt:.0f}s)", flush=True)
    return True


def build_steps(a):
    steps = [
        ("Hardiness zones + deer resistance", ["populate_traits.py"]),
        ("Soil N/P/K",                        ["populate_soil.py"]),
        ("Soil texture/drainage (rule-based)", ["populate_soildims.py"]),
        ("Fruit traits",                      ["populate_fruit.py"]),
        ("Uses: food/material types, lifecycle, eco/material split", ["populate_uses.py"]),
    ]
    if not a.no_usda:
        usda = ["usda_enrich.py"]
        usda += [] if a.usda_dry_run else ["--apply"]
        usda += [] if a.usda_all else ["--only-new"]   # default: only the current batch
        scope = "all plants" if a.usda_all else "current batch (new only)"
        steps.append((f"USDA PLANTS enrichment — authoritative, LAST, {scope}", usda))
    if a.with_images:
        steps.append(("Images — Wikimedia",              ["fetch_images.py"]))
        steps.append(("Images — Commons/iNaturalist fallback", ["fetch_images_fallback.py"]))
    return steps


def main():
    ap = argparse.ArgumentParser(description="Ordered post-import backfill pipeline.")
    ap.add_argument("--with-images", action="store_true", help="also fetch missing images at the end")
    ap.add_argument("--no-usda", action="store_true", help="skip the USDA enrichment step")
    ap.add_argument("--usda-dry-run", action="store_true", help="run USDA as a dry-run (no writes)")
    ap.add_argument("--usda-all", action="store_true",
                    help="re-enrich ALL plants (default: only new/unenriched plants)")
    ap.add_argument("--plan", action="store_true", help="print the ordered steps and exit")
    a = ap.parse_args()

    steps = build_steps(a)
    if a.plan:
        print("Backfill pipeline order:")
        for i, (name, args) in enumerate(steps, 1):
            print(f"  {i}. {name:52} -> python3 {' '.join(args)}")
        return

    # sanity: every script exists before starting
    missing = [args[0] for _, args in steps if not os.path.exists(os.path.join(HERE, args[0]))]
    if missing:
        print("Missing scripts:", missing); sys.exit(1)

    t0 = time.time()
    for name, args in steps:
        if not run(name, args):
            print("\nStopping — a step failed. Fix and re-run.", flush=True)
            sys.exit(1)
    print(f"\n✅ Backfill pipeline complete in {time.time()-t0:.0f}s.", flush=True)


if __name__ == "__main__":
    main()
