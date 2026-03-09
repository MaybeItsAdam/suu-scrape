# suu-scrape

A modular scraper system for Students' Union UCL data, built with a plugin architecture and CLI.

## Installation

1. Clone the repository.
2. Install dependencies (preferably in a virtual environment):

```bash
pip install -e .
```

---

## Election Scraper

Scrape candidates and results for a specific election.

### Browse elections interactively

```bash
suu-scrape election
```

Elections are listed one page at a time. Select a number to scrape it, or choose **Next Page** to load more.

### Select by name

```bash
suu-scrape election "Leadership"
```

Searches page-by-page and stops as soon as it finds a unique match. If multiple elections match you get a numbered list; if none match you fall back to the interactive browser.

### Use a direct URL

```bash
suu-scrape election https://studentsunionucl.org/election/leadership-race-2026
```

Skips the search entirely and scrapes that URL directly.

### Progress output

```
  [page 1] scanning positions...
    [1] Students' Union President
    [2] Education Officer
  [page 2] scanning positions...
    [3] Welfare & Community Officer
    ...
Done — 42 position(s) kept after filters.
```

---

### Flags

| Flag | Description |
|------|-------------|
| `--rounds` | Include full per-round voting data for each position. |
| `--tallies` | Include first-round and final vote tallies per candidate. |
| `--officers-only` | Keep only union-level officer roles (sabbatical officers + student officers). Network committee roles (Secretary, Treasurer, Social Secretary, etc.) and club/society positions are excluded entirely — their result pages are never fetched. |
| `--key-roles` | Keep only President and Treasurer roles across all groups. |
| `--winners-only` | Strip losing candidates. Positions with no declared winner are dropped. Winners are printed live as each position is scraped. |
| `--csv` | Export results to a flat `.csv` file (one row per candidate). |
| `--xlsx` | Export results to a `.xlsx` file, ready to upload to Google Sheets. |
| `--sheets` | Copy results as TSV to the clipboard — paste directly into Google Sheets with Cmd+V. |

Flags can be combined freely:

```bash
# Officers only, export to xlsx
suu-scrape election "Leadership" --officers-only --xlsx

# Winners only with vote tallies, exported to CSV
suu-scrape election "Leadership" --winners-only --tallies --csv

# Copy to clipboard for Google Sheets
suu-scrape election "Leadership" --officers-only --sheets

# Full data with rounds, saved as both JSON and xlsx
suu-scrape election "Leadership" --rounds --tallies --xlsx
```

### `--winners-only` live output

```
  [page 1] scanning positions...
    WINNER  Students' Union President — Jane Smith
    WINNER  Education Officer — Alex Jones
  [page 2] scanning positions...
    WINNER  Computing Society: President — Sam Lee
    ...
Done — 3 position(s) kept after filters.
```

---

## Output Files

All output is written to the **current working directory**.

| File | When created |
|------|-------------|
| `scrape_election_<name>_<timestamp>.json` | Always — JSON export runs by default. |
| `scrape_election_<name>_<timestamp>.csv` | Only with `--csv`. One row per candidate. |
| `scrape_election_<name>_<timestamp>.xlsx` | Only with `--xlsx`. Styled spreadsheet with frozen header row, column widths, and a `Photo` column containing `=IMAGE()` formulas that render candidate photos inline when opened in Google Sheets. |

### CSV / XLSX columns

`position`, `group`, `group_type`, `candidate_name`, `pronouns`, `is_winner`, `initial_tally`, `final_tally`, `image_url`, `photo` *(xlsx only — IMAGE formula)*, `election_statement`, `group_link`

---

## What's On Scraper

Scrape events from the What's On calendar.

```bash
# Scrape the current week
suu-scrape whatson

# Scrape a specific date range
suu-scrape whatson --start 2025-02-10 --end 2025-02-17
```

---

## Session Management

The scraper uses Selenium with a persistent login session stored in `.suu_session.json`. If your session expires you will be prompted to log in via a visible browser window; the new session is saved automatically.

To force a fresh login:

```bash
suu-scrape logout
```

---

## Post-processing: `categorise/`

A three-step pipeline that merges raw scrape outputs into a single enriched results file.

```
categorise/
├── categories.py   # shared logic: corrections, category rules, ordering
├── combine.py      # step 1 — merge + categorise
├── enrich.py       # step 2 — fill campaign_points via OpenAI
└── pipeline.py     # runs both steps end-to-end
```

### Quick start

```bash
# Full pipeline (combine + enrich)
python3 categorise/pipeline.py

# Combine only
python3 categorise/pipeline.py --skip-enrich

# Dry-run enrichment (no API calls)
python3 categorise/pipeline.py --dry-run
```

### `pipeline.py`

```bash
# Auto-detect the two most recent scrape_election_*.json files
python3 categorise/pipeline.py

# Explicit input files
python3 categorise/pipeline.py file1.json file2.json

# Custom output name
python3 categorise/pipeline.py --out results.json

# Use a specific OpenAI model (default: gpt-4o-mini)
python3 categorise/pipeline.py --model gpt-4o

# Re-generate campaign_points even for winners that already have them
python3 categorise/pipeline.py --retry-existing
```

### `combine.py`

Merges two election JSONs, assigns a category to every position, applies manual corrections.

```bash
python3 categorise/combine.py
python3 categorise/combine.py file1.json file2.json
python3 categorise/combine.py --out results_combined.json
```

**Categories:** `Sabbatical Officers`, `Officers`, `Student Trustees`, `Sports`, `Arts`, `Volunteering`, `Societies`, `Hall & Community`, `Faculty Reps`

### `enrich.py`

Calls OpenAI to extract clean bullet-point campaign promises for every winning candidate whose `campaign_points` is `null`.

```bash
pip install openai
export OPENAI_API_KEY=sk-...

python3 categorise/enrich.py results_combined.json
python3 categorise/enrich.py results_combined.json --out enriched.json
python3 categorise/enrich.py results_combined.json --dry-run
python3 categorise/enrich.py results_combined.json --model gpt-4o
python3 categorise/enrich.py results_combined.json --retry-existing
```

---

## Plugin Architecture

After a scrape completes, every plugin in `suu_scrape/plugins/` runs automatically — no registration needed.

### Included plugins

| Plugin | File | Active by default | Notes |
|--------|------|-------------------|-------|
| JSON Export | `json_export.py` | Always | Saves to a timestamped `.json` file. |
| CSV Export | `csv_export.py` | `--csv` only | Flat `.csv`, one row per candidate. |
| XLSX Export | `xlsx_export.py` | `--xlsx` only | Styled spreadsheet with IMAGE formulas for Google Sheets. |
| Clipboard Export | `clipboard_export.py` | `--sheets` only | Copies TSV to clipboard for direct paste into Google Sheets. |
| Supabase Upload | `supabase_upload.py` | When `.env.local` credentials present | Upserts into Supabase tables. |
| Hello World | `hello_world.py` | Always (demo) | Prints a confirmation. Use as a template. |

### Supabase configuration

Create a `.env.local` file in the project root:

```bash
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

### Writing your own plugin

1. Create a `.py` file in `suu_scrape/plugins/`.
2. Subclass `PluginBase` and implement `run(self, data, context)`.

```python
from suu_scrape.core.base import PluginBase

class MyPlugin(PluginBase):
    def run(self, data: dict, context: dict) -> None:
        # data["positions"] for elections, data["events"] for whatson
        print(f"Got {len(data.get('positions', []))} positions")
```

#### `context` keys

| Key | Type | Description |
|-----|------|-------------|
| `scrape_type` | `str` | `"election"` or `"whatson"` |
| `election_name` | `str` | Name/URL of the scraped election *(election only)* |
| `export_csv` | `bool` | `True` when `--csv` was passed |
| `export_xlsx` | `bool` | `True` when `--xlsx` was passed |
| `export_sheets` | `bool` | `True` when `--sheets` was passed |
| `app_name` | `str` | Always `"suu-scrape"` |
| `version` | `str` | Package version string |

---

## .gitignore

Scrape output files and session data are excluded from version control:

```
scrape_election_*
*_emails_*/
.suu_session.json
.env.local
```
