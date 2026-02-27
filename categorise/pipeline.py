#!/usr/bin/env python3
"""
pipeline.py

Runs the full categorisation pipeline in one command:
  1. combine.py  — merges two scraped election JSONs, assigns categories
  2. enrich.py   — fills campaign_points for every winner via the OpenAI API

Requirements for step 2:
    pip install openai
    export OPENAI_API_KEY=sk-...

Usage (from repo root):
    python3 categorise/pipeline.py
    python3 categorise/pipeline.py file1.json file2.json
    python3 categorise/pipeline.py --out results.json
    python3 categorise/pipeline.py --skip-enrich
    python3 categorise/pipeline.py --dry-run
    python3 categorise/pipeline.py --model gpt-4o
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Both sibling modules are in the same directory — make sure they can be found
# whether this script is run directly or via python3 categorise/pipeline.py.
sys.path.insert(0, str(Path(__file__).parent))

from combine import _find_latest_two, merge  # noqa: E402
from enrich import enrich  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Full categorisation pipeline: merge two scraped election JSONs, "
            "assign categories, then fill campaign_points via the OpenAI API."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "Scraped election JSON files to merge "
            "(default: two most recent scrape_election_*.json in cwd)."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="OUTPUT",
        help="Output filename (default: results_combined_<timestamp>.json in cwd).",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Run combine only — skip the OpenAI enrichment step.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run combine normally, then walk enrich without making any API calls.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        metavar="MODEL",
        help="OpenAI model to use for enrichment (default: gpt-4o-mini).",
    )
    parser.add_argument(
        "--retry-existing",
        action="store_true",
        help="Re-generate campaign_points even for winners that already have them.",
    )
    args = parser.parse_args()

    cwd = Path.cwd()

    # ------------------------------------------------------------------
    # Resolve input files
    # ------------------------------------------------------------------
    if args.files:
        files = [Path(f) for f in args.files]
        for f in files:
            if not f.exists():
                print(f"Error: file not found: {f}", file=sys.stderr)
                sys.exit(1)
    else:
        try:
            files = _find_latest_two(cwd)
            print("Auto-detected input files:")
            for f in files:
                print(f"  {f.name}")
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    out_path = (
        Path(args.out)
        if args.out
        else cwd / f"results_combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    # ------------------------------------------------------------------
    # Step 1: combine
    # ------------------------------------------------------------------
    print("\n── Step 1: combine ─────────────────────────────────────────")
    merge(files, out_path)

    if args.skip_enrich:
        print("\nSkipping enrichment (--skip-enrich).")
        print(f"\nDone → {out_path}")
        return

    # ------------------------------------------------------------------
    # Step 2: enrich
    # ------------------------------------------------------------------
    print("\n── Step 2: enrich ──────────────────────────────────────────")

    try:
        from openai import OpenAI
    except ImportError:
        print(
            "Error: openai package not found. Run: pip install openai\n"
            "Or re-run with --skip-enrich to produce the combined file without campaign points.",
            file=sys.stderr,
        )
        sys.exit(1)

    with out_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    total_winners = sum(
        1
        for p in data.get("positions", [])
        for c in p.get("winners", [])
        if c.get("is_winner")
    )
    null_count = sum(
        1
        for p in data.get("positions", [])
        for c in p.get("winners", [])
        if c.get("is_winner") and c.get("campaign_points") is None
    )
    print(f"  {total_winners} winner(s) total, {null_count} with campaign_points: null")
    print(f"  Model: {args.model}")
    if args.dry_run:
        print("  Mode: dry-run (no API calls)")
    print()

    client = None if args.dry_run else OpenAI()

    enriched_data, filled, skipped = enrich(
        data,
        client=client,
        model=args.model,
        dry_run=args.dry_run,
        retry_existing=args.retry_existing,
    )

    if not args.dry_run:
        out_path.write_text(
            json.dumps(enriched_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nSaved → {out_path}")

    print(f"Enrichment done — {filled} filled, {skipped} skipped.")
    print(f"\nDone → {out_path}")


if __name__ == "__main__":
    main()
