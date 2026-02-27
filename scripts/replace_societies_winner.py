#!/usr/bin/env python3
"""
replace_societies_winner.py

Robust helper script to replace the Societies Officer winners in an existing
combined results JSON with the winner(s) from a Societies Officer by-election
scrape file.

Typical usage (from project root):
    python3 scripts/replace_societies_winner.py
    python3 scripts/replace_societies_winner.py \
        --combined results_combined.json \
        --by-election scrape_election_https_studentsunionucl_org_election_societies_offi_20260227_152244.json

Behavior:
- Auto-detects by-election file if not supplied (looks for files with 'societies' in
  the filename and 'scrape_election' prefix).
- Reads winners from the by-election file (supports both 'winners' and legacy 'candidates'
  keys).
- Finds the Societies Officer position(s) in the combined file:
    * If a position contains a winner with name matching the `--target-name`
      (default: "Weining Pan"), that position will have its winners replaced.
    * Otherwise, the first Societies Officer position found will be replaced.
- Makes a timestamped backup of the combined file before writing.
- Ensures the inserted winners have `campaign_points` explicitly set to null
  (JSON `null`) to indicate they need enrichment.
- Prints a concise summary of actions taken.

Notes:
- This script modifies the combined JSON in-place by default (after creating a backup).
- It is defensive and will not overwrite files if required data cannot be found.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_by_election_file(patterns: List[str]) -> Optional[Path]:
    """Find the most recently modified file matching any of the given glob patterns."""
    candidates: List[Path] = []
    for pat in patterns:
        for p in glob.glob(pat):
            candidates.append(Path(p))
    if not candidates:
        return None
    # pick most recently modified
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def extract_winners_from_position(pos: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the list of candidate dicts from a position (support winners or candidates)."""
    # Prefer 'winners' key, fall back to legacy 'candidates'.
    raw = pos.get("winners")
    if raw is None:
        raw = pos.get("candidates", [])
    return list(raw or [])


def find_position_by_title(
    positions: List[Dict[str, Any]], title_match: str
) -> List[Dict[str, Any]]:
    """Return list of positions whose title matches title_match (case-insensitively)."""
    out: List[Dict[str, Any]] = []
    for p in positions:
        t = p.get("title", "")
        if t and t.strip().lower() == title_match.strip().lower():
            out.append(p)
    return out


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{ts}")
    shutil.copy2(path, backup)
    return backup


def normalize_insert_winner(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure the candidate dict is safe to insert into the combined file."""
    c = dict(candidate)  # shallow copy
    # Ensure required keys exist; leave most fields as-is.
    if "is_winner" not in c:
        c["is_winner"] = True
    # Mark campaign_points explicitly as null for later enrichment.
    c["campaign_points"] = None
    return c


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace Societies Officer winners in the combined results with the by-election winner(s)."
    )
    parser.add_argument(
        "--combined",
        default="results_combined.json",
        help="Path to combined results JSON (default: results_combined.json).",
    )
    parser.add_argument(
        "--by-election",
        default=None,
        help="Path to the by-election scrape JSON. If omitted the script will try to auto-detect one.",
    )
    parser.add_argument(
        "--position",
        default="Societies Officer",
        help="Position title to replace (default: 'Societies Officer').",
    )
    parser.add_argument(
        "--target-name",
        default="Weining Pan",
        help="Replace the Societies Officer position that currently contains this winner name if found (default: 'Weining Pan').",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a backup of the combined file (not recommended).",
    )
    args = parser.parse_args()

    combined_path = Path(args.combined)
    if not combined_path.exists():
        print(f"Error: combined file not found: {combined_path}", file=sys.stderr)
        sys.exit(2)

    # Resolve by-election file
    by_path: Optional[Path]
    if args.by_election:
        by_path = Path(args.by_election)
        if not by_path.exists():
            print(
                f"Error: specified by-election file not found: {by_path}",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        # Auto-detect likely by-election files: contain 'societies' and start with 'scrape_election'
        candidates = []
        # common patterns to try
        patterns = [
            "scrape_election_*societies*.json",
            "*societies*.json",
            "scrape_election_*societ*.json",
        ]
        by_path = find_by_election_file(patterns)
        if by_path is None:
            print(
                "Error: could not auto-detect a by-election file (no '*societies*.json' matches).",
                file=sys.stderr,
            )
            print(
                "Please pass --by-election <path> to specify the file.", file=sys.stderr
            )
            sys.exit(2)

    print(f"Using combined file: {combined_path}")
    print(f"Using by-election file: {by_path}")

    # Load by-election and extract Societies Officer winners
    by_data = load_json(by_path)
    by_positions = by_data.get("positions", [])
    by_pos = None
    for p in by_positions:
        if p.get("title", "").strip().lower() == args.position.strip().lower():
            by_pos = p
            break

    if by_pos is None:
        print(
            f"Error: by-election file does not contain a position titled '{args.position}'.",
            file=sys.stderr,
        )
        sys.exit(3)

    by_winners = extract_winners_from_position(by_pos)
    by_winner_names = [c.get("name") for c in by_winners if c.get("name")]
    if not by_winners:
        print("Error: no winners found in by-election position.", file=sys.stderr)
        sys.exit(4)

    print(f"By-election winner(s) found: {by_winner_names}")

    # Load combined file
    combined = load_json(combined_path)
    positions = combined.get("positions", [])
    if not isinstance(positions, list):
        print(
            "Error: combined file format unexpected: 'positions' is not a list.",
            file=sys.stderr,
        )
        sys.exit(5)

    # Find Societies Officer positions in combined file
    target_positions = find_position_by_title(positions, args.position)
    if not target_positions:
        print(
            f"No position titled '{args.position}' found in combined file. Aborting.",
            file=sys.stderr,
        )
        sys.exit(6)

    # Decide which combined position to replace:
    replaced = False
    # Try to find the position that contains the target existing winner name (Weining Pan)
    for p in target_positions:
        current_winners = extract_winners_from_position(p)
        names = [c.get("name") for c in current_winners if c.get("name")]
        if args.target_name in names:
            # Replace this position's winners
            new_winners = [normalize_insert_winner(c) for c in by_winners]
            # Replace in-place in the combined structure; maintain key 'winners'
            p["winners"] = new_winners
            # Also remove legacy 'candidates' key if present to avoid ambiguity
            if "candidates" in p:
                try:
                    del p["candidates"]
                except Exception:
                    pass
            replaced = True
            print(
                f"Replaced winners in position containing target '{args.target_name}'."
            )
            break

    if not replaced:
        # Fallback: replace the first Societies Officer position found
        p = target_positions[0]
        new_winners = [normalize_insert_winner(c) for c in by_winners]
        p["winners"] = new_winners
        if "candidates" in p:
            try:
                del p["candidates"]
            except Exception:
                pass
        replaced = True
        print(
            "Target name not found; replaced the first Societies Officer position in the combined file."
        )

    if not replaced:
        print("No replacement performed.", file=sys.stderr)
        sys.exit(7)

    # Backup combined file
    if not args.no_backup:
        backup = backup_file(combined_path)
        print(f"Backup created: {backup}")

    # Write updated combined file
    write_json(combined_path, combined)
    print(f"Updated combined file written: {combined_path}")

    # Summary
    print("Summary:")
    print(f"  By-election winners inserted: {by_winner_names}")
    print(f"  Combined file modified: {combined_path}")
    if not args.no_backup:
        print(f"  Backup file: {backup}")

    print("Done.")


if __name__ == "__main__":
    main()
