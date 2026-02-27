#!/usr/bin/env python3
"""
combine.py

Merges two scraped election JSON files, assigns a category to every
position, applies manual corrections, and writes a combined JSON file.

campaign_points is left as null for every winning candidate — run
enrich.py (or pipeline.py) afterwards to fill them in via an LLM.

Usage (from repo root):
    python3 categorise/combine.py
    python3 categorise/combine.py file1.json file2.json
    python3 categorise/combine.py --out results_combined.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from categories import (
    CATEGORY_ORDER,
    apply_corrections,
    assign_category,
    normalise_title,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_latest_two(directory: Path) -> list[Path]:
    """Return the two most recently modified scrape_election_*.json files."""
    candidates = sorted(
        directory.glob("scrape_election_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if len(candidates) < 2:
        raise FileNotFoundError(
            f"Need at least 2 scrape_election_*.json files in {directory}, "
            f"found {len(candidates)}."
        )
    return list(candidates[:2])


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge(files: list[Path], out_path: Path) -> Path:
    """
    Merge *files* into a single combined JSON at *out_path*.
    Returns out_path for chaining (e.g. straight into enrich()).
    """
    all_positions: list[dict[str, Any]] = []
    source_elections: list[dict[str, Any]] = []

    for fp in files:
        print(f"  Loading {fp.name} …")
        data = _load(fp)

        election_meta = dict(data.get("election", {}))
        election_meta["source_file"] = fp.name
        source_elections.append(election_meta)

        for pos in data.get("positions", []):
            title = normalise_title(pos.get("title", ""))
            category = assign_category(title)

            # Raw scrape files used "candidates"; new scrapes use "winners".
            # Accept either so old files on disk still combine cleanly.
            raw_candidates = pos.get("winners") or pos.get("candidates", [])
            winners = apply_corrections(title, raw_candidates)

            # Remove any raw 'candidates' sub-structures from candidate dicts
            # and stub campaign_points for winners — filled in by enrich.py
            for c in winners:
                # Defensive: drop any accidental nested 'candidates' data to avoid bloat
                c.pop("candidates", None)
                if c.get("is_winner"):
                    c["campaign_points"] = None

            # Build a lean position dict for the combined output:
            # copy everything except the raw 'candidates' and 'winners' keys to avoid
            # carrying through any un-normalised lists from the original scrape,
            # then set canonical fields explicitly.
            new_pos = {
                k: v for k, v in pos.items() if k not in ("candidates", "winners")
            }
            new_pos.update(
                {
                    "title": title,
                    "category": category,
                    "winners": winners,
                }
            )
            all_positions.append(new_pos)

    # Sort by category then title
    order_map = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    all_positions.sort(
        key=lambda p: (order_map.get(p["category"], 99), p.get("title", ""))
    )

    combined: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_elections": source_elections,
        "total_positions": len(all_positions),
        "positions": all_positions,
    }

    out_path.write_text(
        json.dumps(combined, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Written {len(all_positions)} positions → {out_path}")

    counts: Counter[str] = Counter(p["category"] for p in all_positions)
    print("\n  Category breakdown:")
    for cat in CATEGORY_ORDER:
        if counts[cat]:
            print(f"    {cat:<28} {counts[cat]:>3} position(s)")
    if counts.get("Other"):
        print(f"    {'Other':<28} {counts['Other']:>3} position(s)")

    null_count = sum(
        1
        for p in all_positions
        for c in p.get("winners", [])
        if c.get("is_winner") and c.get("campaign_points") is None
    )
    print(
        f"\n  {null_count} winner(s) have campaign_points: null"
        f" — run enrich.py to fill them in."
    )

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge two scraped election JSON files and assign categories. "
            "campaign_points is left as null; run enrich.py to fill them in."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help=(
            "Explicit JSON files to merge "
            "(default: two most recent scrape_election_*.json in the cwd)."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="OUTPUT",
        help="Output filename (default: results_combined_<timestamp>.json in cwd).",
    )
    args = parser.parse_args()

    cwd = Path.cwd()

    if args.files:
        files = [Path(f) for f in args.files]
        for f in files:
            if not f.exists():
                print(f"Error: file not found: {f}", file=sys.stderr)
                sys.exit(1)
    else:
        try:
            files = _find_latest_two(cwd)
            print("Auto-detected files:")
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

    print()
    merge(files, out_path)


if __name__ == "__main__":
    main()
