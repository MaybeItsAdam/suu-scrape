#!/usr/bin/env python3
"""
committee_export.py

Turns a raw `scrape_election_*.json` (from `suu-scrape election`) into the
`committee_data_to_seed.json` consumed by society-tracker's
`scripts/seed_committees.ts`.

It keeps only society/club/network-committee positions (the actual society
committees — union officers are dropped), groups them by society, keeps the
elected winners, and emits one entry per society with its roles.

Usage (from the suu-scrape repo root):
    # auto-detect the most recent scrape_election_*.json
    python3 categorise/committee_export.py --year 2025-26

    # explicit input / output
    python3 categorise/committee_export.py scrape_election_xxx.json \
        --year 2025-26 --out committee_data_to_seed.json

Then copy the output to society-tracker's repo root and run
`npx tsx scripts/seed_committees.ts --replace`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Only these group types are real society committees. Union officers (and the
# generic "Other"/"Network" buckets) are intentionally excluded.
COMMITTEE_GROUP_TYPES = {"Society", "Club", "NetworkCommittee"}


def _latest_scrape(directory: Path) -> Path:
    candidates = sorted(
        directory.glob("scrape_election_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No scrape_election_*.json found in {directory}."
        )
    return candidates[0]


def build(raw: dict[str, Any], year: str) -> dict[str, Any]:
    election = raw.get("election") or {}
    source = (
        election.get("url") or election.get("name")
        if isinstance(election, dict)
        else election
    )

    # Group positions by society name, preserving first-seen order.
    societies: dict[str, dict[str, Any]] = {}
    for pos in raw.get("positions", []):
        if pos.get("group_type") not in COMMITTEE_GROUP_TYPES:
            continue
        name = pos.get("group")
        if not name:
            continue
        entry = societies.setdefault(
            name,
            {"societyName": name, "groupType": pos["group_type"], "roles": []},
        )
        for w in pos.get("winners", []):
            if not w.get("is_winner"):
                continue
            entry["roles"].append(
                {
                    "role": pos.get("title", ""),
                    "memberName": w.get("name", ""),
                    "pronouns": (
                        None
                        if w.get("pronouns") in (None, "", "Unknown")
                        else w.get("pronouns")
                    ),
                    "imageUrl": w.get("image_url"),
                }
            )

    # Drop societies that ended up with no elected holders.
    out_societies = [s for s in societies.values() if s["roles"]]

    return {
        "year": year,
        "sourceElection": source,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "societies": out_societies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Raw scrape_election_*.json (default: most recent in cwd).",
    )
    parser.add_argument(
        "--year",
        required=True,
        help='Academic year for these rows, e.g. "2025-26".',
    )
    parser.add_argument(
        "--out",
        default="committee_data_to_seed.json",
        help="Output path (default: committee_data_to_seed.json).",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    in_path = Path(args.file) if args.file else _latest_scrape(cwd)
    if not in_path.exists():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    with in_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    result = build(raw, args.year)
    role_count = sum(len(s["roles"]) for s in result["societies"])

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Input:  {in_path.name}")
    print(
        f"Output: {out_path}  "
        f"({len(result['societies'])} societies, {role_count} roles, year {args.year})"
    )


if __name__ == "__main__":
    main()
