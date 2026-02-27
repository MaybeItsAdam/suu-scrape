import csv
import os
from datetime import datetime

from suu_scrape.core.base import PluginBase


class CsvExportPlugin(PluginBase):
    """
    Plugin to export scraped election data as a flat CSV file.
    Each row represents one candidate, with position and group info included.
    """

    # Column order for the CSV
    COLUMNS = [
        "position",
        "group",
        "group_type",
        "candidate_name",
        "pronouns",
        "is_winner",
        "initial_tally",
        "final_tally",
        "image_url",
        "election_statement",
        "group_link",
    ]

    def run(self, data: any, context: dict) -> None:
        scrape_type = context.get("scrape_type", "unknown")

        # Only run if explicitly requested via --csv flag
        if not context.get("export_csv"):
            return

        # Only run for election scrapes
        if scrape_type != "election":
            print("CsvExportPlugin: Skipping (not an election scrape).")
            return

        positions = data.get("positions", [])
        if not positions:
            print("CsvExportPlugin: No positions found, skipping.")
            return

        # Build filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_part = ""
        if "election_name" in context:
            safe_name = "_".join(
                filter(
                    None,
                    "".join(
                        c if c.isalnum() else "_" for c in context["election_name"]
                    ).split("_"),
                )
            )[:50]
            name_part = f"_{safe_name.lower()}"

        filename = f"scrape_{scrape_type}{name_part}_{timestamp}.csv"

        rows = []
        for pos in positions:
            for cand in pos.get("winners", []):
                rows.append(
                    {
                        "position": pos.get("title", ""),
                        "group": pos.get("group", ""),
                        "group_type": pos.get("group_type", ""),
                        "candidate_name": cand.get("name", ""),
                        "pronouns": cand.get("pronouns", ""),
                        "is_winner": cand.get("is_winner", False),
                        "initial_tally": cand.get("initial_tally", ""),
                        "final_tally": cand.get("final_tally", ""),
                        "image_url": cand.get("image_url", ""),
                        "election_statement": cand.get("election_statement", ""),
                        "group_link": pos.get("group_link", ""),
                    }
                )

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"Saved {len(rows)} winners to {filename}")
        except Exception as e:
            print(f"Error saving CSV: {e}")
