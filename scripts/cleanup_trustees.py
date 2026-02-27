#!/usr/bin/env python3
"""
cleanup_trustees.py

Utility to consolidate and clean Student Trustee entries in a combined
results JSON (produced by the categorisation pipeline).

What it does
- Finds all positions in the combined JSON whose title contains "trustee"
  (case-insensitive).
- Gathers all candidate/winner records from those positions (supports both
  legacy `candidates` key and current `winners` key).
- Deduplicates records by name (case-insensitive), merging fields sensibly:
    - keeps the most complete non-empty values for `pronouns`, `image_url`,
      `election_statement`.
    - preserves `is_winner` as True if any appearance had it True.
    - uses the maximum `final_tally` and `initial_tally` values if present.
    - preserves `campaign_points` if present on any copy (otherwise null).
- Replaces the multiple Student Trustee positions with a single consolidated
  position named "Student Trustee" (singular), category "Student Trustees".
- Ensures the consolidated position uses the `winners` key (the canonical
  output), and removes legacy `candidates` keys.
- Writes back the combined file (creates a timestamped backup by default).

Usage (run from project root):
    python3 scripts/cleanup_trustees.py
    python3 scripts/cleanup_trustees.py --combined results_combined.json
    python3 scripts/cleanup_trustees.py --combined results_combined.json --out results_combined.fixed.json
    python3 scripts/cleanup_trustees.py --no-backup

Notes
- The script is defensive and will not destroy data — it creates a backup
  unless --no-backup is used.
- The merging heuristics are simple; review the consolidated `winners`
  afterwards to confirm correctness.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{ts}")
    shutil.copy2(path, backup)
    return backup


def iter_position_candidates(pos: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Yield candidate dicts from a position. Supports both 'winners' (preferred)
    and legacy 'candidates' keys.
    """
    if "winners" in pos and pos.get("winners") is not None:
        for c in pos.get("winners", []):
            yield dict(c)
    elif "candidates" in pos and pos.get("candidates") is not None:
        for c in pos.get("candidates", []):
            yield dict(c)
    else:
        # No candidate-like field; nothing to yield
        return
        yield  # pragma: no cover


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    return " ".join(name.split()).strip()


def merge_candidate_records(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge multiple candidate dicts for the same person into one record.

    Heuristics:
    - Keep non-empty pronouns / image_url / election_statement preferring the
      longest non-empty value.
    - is_winner is True if any rec has it True.
    - initial_tally and final_tally: take max if numeric, prefer present values.
    - campaign_points: keep the first non-null value, otherwise None.
    """
    out: Dict[str, Any] = {}
    # Basic identity
    names = [r.get("name") for r in recs if r.get("name")]
    out["name"] = names[0] if names else None

    # pronouns / image_url / election_statement: choose longest non-empty
    for key in ("pronouns", "image_url", "election_statement"):
        vals = [str(r.get(key)).strip() for r in recs if r.get(key)]
        vals = [v for v in vals if v and v.lower() not in ("none", "unknown")]
        out[key] = max(vals, key=len) if vals else (recs[0].get(key) if recs else None)

    # is_winner
    out["is_winner"] = any(bool(r.get("is_winner")) for r in recs)

    # tallies: choose max if present and numeric
    def _num(v):
        try:
            return float(v)
        except Exception:
            return None

    initial_vals = [
        _num(r.get("initial_tally")) for r in recs if r.get("initial_tally") is not None
    ]
    final_vals = [
        _num(r.get("final_tally")) for r in recs if r.get("final_tally") is not None
    ]
    if initial_vals:
        initial_vals = [v for v in initial_vals if v is not None]
        out["initial_tally"] = max(initial_vals) if initial_vals else None
    if final_vals:
        final_vals = [v for v in final_vals if v is not None]
        out["final_tally"] = max(final_vals) if final_vals else None

    # campaign_points: first non-null
    cp = next(
        (
            r.get("campaign_points")
            for r in recs
            if r.get("campaign_points") is not None
        ),
        None,
    )
    out["campaign_points"] = cp

    # pronouns maybe None -> ensure exists
    if out.get("pronouns") is None:
        out["pronouns"] = None
    if out.get("image_url") is None:
        out["image_url"] = None
    if out.get("election_statement") is None:
        out["election_statement"] = ""

    return out


def consolidate_trustees(
    positions: List[Dict[str, Any]], position_title: str = "Student Trustee"
) -> (List[Dict[str, Any]], Optional[Dict[str, Any]]):
    """
    Consolidate all positions whose title contains 'trustee' (case-insensitive)
    into a single canonical Student Trustee position.

    Returns (new_positions_list, consolidated_position) where consolidated_position
    is None if no trustee positions were found.
    """
    trustee_indices: List[int] = []
    for idx, pos in enumerate(positions):
        title = pos.get("title", "") or ""
        if "trustee" in title.lower():
            trustee_indices.append(idx)

    if not trustee_indices:
        return positions, None

    # collect all candidate records from the trustee positions
    bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    original_records_count = 0
    for idx in trustee_indices:
        pos = positions[idx]
        for cand in iter_position_candidates(pos):
            original_records_count += 1
            name_norm = normalize_name(cand.get("name"))
            key = name_norm.lower()
            bucket[key].append(cand)

    # Merge per unique person
    merged_list: List[Dict[str, Any]] = []
    for key, recs in bucket.items():
        merged = merge_candidate_records(recs)
        # Ensure `is_winner` is boolean
        merged["is_winner"] = bool(merged.get("is_winner"))
        # Ensure campaign_points present (explicit null if not provided)
        if "campaign_points" not in merged:
            merged["campaign_points"] = None
        merged_list.append(merged)

    # Sort merged list: winners first (is_winner True), then by name
    merged_list.sort(
        key=lambda r: (not r.get("is_winner"), (r.get("name") or "").lower())
    )

    # Build consolidated position dict
    consolidated: Dict[str, Any] = {
        "title": position_title,
        "group": "Union",
        "group_type": "Union",
        "group_link": None,
        # keep a legacy 'candidates' block with full list for backward compatibility,
        # but the canonical list for downstream processing is 'winners' (only winners).
        "candidates": merged_list.copy(),
        "category": "Student Trustees",
    }
    # canonical winners list should include all merged_list items but keep is_winner flags
    consolidated["winners"] = merged_list.copy()

    # Remove original trustee positions and insert consolidated at the first index found
    first_idx = trustee_indices[0]
    new_positions = [p for i, p in enumerate(positions) if i not in trustee_indices]
    # Insert consolidated position at original first index (or at end if out-of-range)
    if first_idx <= len(new_positions):
        new_positions.insert(first_idx, consolidated)
    else:
        new_positions.append(consolidated)

    return new_positions, consolidated


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate Student Trustee positions in a combined results JSON."
    )
    parser.add_argument(
        "--combined",
        default="results_combined.json",
        help="Path to the combined results JSON (default: results_combined.json).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path (default: overwrite the combined file).",
    )
    parser.add_argument(
        "--position-title",
        default="Student Trustee",
        help="Canonical position title to use (default: 'Student Trustee').",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a timestamped backup of the combined file.",
    )
    args = parser.parse_args(argv)

    combined_path = Path(args.combined)
    if not combined_path.exists():
        print(f"Error: combined file not found: {combined_path}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else combined_path

    data = load_json(combined_path)
    positions = data.get("positions")
    if not isinstance(positions, list):
        print("Error: combined JSON has no 'positions' list.", file=sys.stderr)
        return 3

    # Find trustee positions and consolidate
    print("Scanning for Student Trustee positions...")
    new_positions, consolidated = consolidate_trustees(
        positions, position_title=args.position_title
    )

    if consolidated is None:
        print("No trustee positions found — nothing to do.")
        return 0

    # Prepare new document
    new_data = dict(data)
    new_data["positions"] = new_positions

    # Backup if requested
    backup = None
    if not args.no_backup:
        backup = backup_file(combined_path)
        print(f"Created backup: {backup}")

    # Write output
    write_json(out_path, new_data)
    print(f"Wrote consolidated combined file: {out_path}")

    # Summary
    print("\nSummary:")
    print(
        f"  Consolidated Student Trustee position inserted with {len(consolidated.get('winners', []))} unique candidate(s)."
    )
    if backup:
        print(f"  Backup: {backup}")
    print(
        "  You may now run the enrichment step (categorise/enrich.py) to fill campaign_points for winners."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
