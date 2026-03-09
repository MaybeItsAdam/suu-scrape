import io
import csv
import subprocess
import sys

from suu_scrape.core.base import PluginBase


class ClipboardExportPlugin(PluginBase):
    """
    Plugin to copy scraped election data as TSV to the clipboard.
    Paste directly into Google Sheets with Cmd+V / Ctrl+V.
    Activated via the --sheets flag (export_sheets in context).
    """

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
        if not context.get("export_sheets"):
            return

        if context.get("scrape_type") != "election":
            print("ClipboardExportPlugin: Skipping (not an election scrape).")
            return

        positions = data.get("positions", [])
        if not positions:
            print("ClipboardExportPlugin: No positions found, skipping.")
            return

        rows = []
        for pos in positions:
            for cand in pos.get("winners", []):
                # Flatten newlines in election_statement so each candidate
                # stays on a single row when pasted into Sheets.
                statement = (cand.get("election_statement") or "").replace("\n", " ").replace("\r", "")
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
                        "election_statement": statement,
                        "group_link": pos.get("group_link", ""),
                    }
                )

        # Build TSV in memory
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=self.COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
        tsv = buf.getvalue()

        # Copy to clipboard
        try:
            if sys.platform == "darwin":
                proc = subprocess.run(["pbcopy"], input=tsv.encode("utf-8"), check=True)
            elif sys.platform == "win32":
                # clip.exe expects UTF-16LE with BOM on Windows
                proc = subprocess.run(
                    ["clip"],
                    input=tsv.encode("utf-16-le"),
                    check=True,
                    shell=True,
                )
            else:
                # Linux — try xclip then xsel as fallback
                try:
                    proc = subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=tsv.encode("utf-8"),
                        check=True,
                    )
                except FileNotFoundError:
                    proc = subprocess.run(
                        ["xsel", "--clipboard", "--input"],
                        input=tsv.encode("utf-8"),
                        check=True,
                    )

            print(f"Copied {len(rows)} rows to clipboard — paste into Google Sheets with Cmd+V.")

        except FileNotFoundError as e:
            print(f"ClipboardExportPlugin: clipboard tool not found ({e}). Printing TSV to stdout instead.\n")
            print(tsv)
        except subprocess.CalledProcessError as e:
            print(f"ClipboardExportPlugin: failed to copy to clipboard ({e}). Printing TSV to stdout instead.\n")
            print(tsv)