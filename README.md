# suu-scrape

A modular scraper system for Students' Union UCL data, built with a plugin architecture and CLI.

## Installation

1. Clone the repository.
2. Install dependencies (preferably in a virtual environment):

```bash
pip install -e .
```

## Usage

The scraper provides a `suu-scrape` command-line interface.

---

### 1. Election Scraper

Scrape candidates and results for a specific election.

#### List / browse available elections interactively

```bash
suu-scrape election
```

Elections are listed one page at a time. Select a number to scrape it, or choose **Next Page** to load more.

#### Select an election by name

```bash
suu-scrape election "Leadership"
```

The tool searches page-by-page and stops as soon as it finds a unique match, so it avoids fetching pages it doesn't need. If multiple elections match the name you get a numbered list to choose from; if none match you fall back to the interactive browser.

#### Progress output

As the scrape runs, each listing page and each position is printed as it is fetched — no waiting for a full list to load first:

```
  [page 1] scanning positions...
    [1] President
    [2] Treasurer
  [page 2] scanning positions...
    [3] Welfare Officer
    ...
Done — 42 position(s) kept after filters.
```

---

#### Flags

| Flag | Description |
|------|-------------|
| `--rounds` | Include full per-round voting data for each position. |
| `--tallies` | Include first-round and final vote tallies per candidate. |
| `--csv` | Export results to a flat CSV file (one row per candidate) in addition to the default JSON output. |
| `--officers-only` | Keep only union-level officer roles (sabbatical officers + student officers). Network *committee* roles (Secretary, Treasurer, Social Secretary, Campaigns Representative, etc.) are excluded — only the union-level lead officer for each constituency counts. Positions belonging to clubs, societies, or network committees are skipped entirely — their result pages are never fetched. |
| `--key-roles` | Keep only President and Treasurer roles across all groups. Positions that don't match are skipped before their result pages are fetched. |
| `--winners-only` | Keep only winning candidates. Losers are stripped from each position and positions with no declared winner are dropped. Winners are printed live as each position is scraped: `WINNER  Group: Role — Name`. |

Flags can be combined freely:

```bash
# Print winners as they are found, with vote tallies
suu-scrape election "Summer Elections" --winners-only --tallies

# Officers only, export to CSV
suu-scrape election "Leadership" --officers-only --csv

# Key roles with full voting rounds
suu-scrape election "Annual Elections" --key-roles --rounds --tallies

# Winners from union officer roles only
suu-scrape election "Annual Elections" --winners-only --officers-only
```

#### `--winners-only` live output

When `--winners-only` is active, each winner is printed the moment their position page is scraped — you don't have to wait for the whole election to finish:

```
  [page 1] scanning positions...
    WINNER  President — Jane Smith
    WINNER  Treasurer — Alex Jones
  [page 2] scanning positions...
    WINNER  Computing Society: President — Sam Lee
    ...
Done — 3 position(s) kept after filters.
```

---

### 2. What's On Scraper

Scrape events from the What's On calendar.

```bash
# Scrape the current week
suu-scrape whatson

# Scrape a specific date range
suu-scrape whatson --start 2025-02-10 --end 2025-02-17
```

---

### 3. Session Management

The scraper uses Selenium with a persistent login session stored in `.suu_session.json`. If your session expires you will be prompted to log in via a visible browser window; the new session is then saved automatically.

To force a fresh login, clear the saved session:

```bash
suu-scrape logout
```

---

## Post-processing: `categorise/`

The `categorise/` folder contains a three-file pipeline that turns the raw scrape outputs into a single enriched results file.

```
categorise/
├── categories.py   # shared logic: corrections, category rules, ordering
├── combine.py      # step 1 — merge + categorise
├── enrich.py       # step 2 — fill campaign_points via OpenAI
└── pipeline.py     # runs both steps end-to-end
```

---

### Quick start

```bash
# Run the full pipeline (combine + enrich) in one command
python3 categorise/pipeline.py

# Combine only — skip OpenAI enrichment
python3 categorise/pipeline.py --skip-enrich

# Preview enrichment without making API calls
python3 categorise/pipeline.py --dry-run
```

---

### `pipeline.py` — full pipeline

Runs `combine.py` then `enrich.py` end-to-end.

```bash
# Auto-detect the two most recent scrape_election_*.json files
python3 categorise/pipeline.py

# Explicit input files
python3 categorise/pipeline.py file1.json file2.json

# Custom output name
python3 categorise/pipeline.py --out results.json

# Skip the enrichment step
python3 categorise/pipeline.py --skip-enrich

# Dry-run enrichment (no API calls)
python3 categorise/pipeline.py --dry-run

# Use a specific OpenAI model (default: gpt-4o-mini)
python3 categorise/pipeline.py --model gpt-4o

# Re-generate campaign_points even for winners that already have them
python3 categorise/pipeline.py --retry-existing
```

---

### `combine.py` — merge and categorise

Merges two scraped election JSONs, assigns a category to every position, applies manual corrections, and writes a combined JSON file. `campaign_points` is left as `null` for every winning candidate.

```bash
python3 categorise/combine.py
python3 categorise/combine.py file1.json file2.json
python3 categorise/combine.py --out results_combined.json
```

**Categories:**

| Category | What's included |
|---|---|
| `Sabbatical Officers` | The six paid full-time sabbatical roles (President, Education, Welfare & Community, Activities & Engagement, Equity & Inclusion, Postgraduate) |
| `Officers` | All other union-level student officers (Accommodation, Disabled Students', International, LGBTQ+, Mature, POC, Research, Social Class, Sustainability, Trans, UCL East, Women's, etc.) |
| `Student Trustees` | Student Trustee positions (title normalised to singular regardless of source) |
| `Sports` | Sports Officer + Sports Reps |
| `Arts` | Arts Officer + Societies Rep (Arts) |
| `Volunteering` | Volunteering Officer + Volunteering Reps |
| `Societies` | Societies Officer, Societies Rep (Non-portfolio), Societies Rep (Student Media), Welfare Reps (Societies) |
| `Hall & Community` | Hall Community Officers |
| `Faculty Reps` | All Faculty of … and Institute of … reps |

**Manual corrections baked in:**

- `"Student Trustees"` (plural) is normalised to `"Student Trustee"` (singular) across both source files.
- Hammad Khaled is marked `is_winner: false` (no longer a trustee post-election).

To add further corrections, edit `REMOVED_WINNERS` and `normalise_title()` in `categorise/categories.py`.

---

### `enrich.py` — fill campaign points via OpenAI

Reads a combined results JSON, calls the OpenAI API to extract a clean bullet-point list of campaign promises for every winning candidate whose `campaign_points` is `null`, and writes the result back.

**Setup:**

```bash
pip install openai
export OPENAI_API_KEY=sk-...
```

```bash
# Fill all null campaign_points (overwrites input file)
python3 categorise/enrich.py results_combined.json

# Write to a new file instead
python3 categorise/enrich.py results_combined.json --out enriched.json

# Preview which candidates would be processed without calling the API
python3 categorise/enrich.py results_combined.json --dry-run

# Use a different model (default: gpt-4o-mini)
python3 categorise/enrich.py results_combined.json --model gpt-4o

# Re-generate points even for winners that already have them
python3 categorise/enrich.py results_combined.json --retry-existing
```

Each winner's `election_statement` is sent to the model with a system prompt instructing it to return a JSON array of 4–8 concise campaign promises. The result is written directly into the `campaign_points` field for that candidate.

---

### `categories.py` — shared logic

Contains everything that both `combine.py` and `enrich.py` share: `normalise_title()`, `REMOVED_WINNERS`, `assign_category()`, and `CATEGORY_ORDER`. Edit this file to add new corrections or adjust category rules without touching the pipeline scripts.

---

## Output Files

All output is written to the current working directory.

| File | When created |
|------|-------------|
| `scrape_election_<name>_<timestamp>.json` | Always (JSON export plugin runs by default). |
| `scrape_election_<name>_<timestamp>.csv` | Only when `--csv` is passed. Columns: `position`, `group`, `group_type`, `candidate_name`, `pronouns`, `is_winner`, `initial_tally`, `final_tally`, `image_url`, `election_statement`, `group_link`. |

---

## Plugin Architecture

After a scrape completes, every plugin discovered in `suu_scrape/plugins/` is executed automatically.

- **Base class:** `suu_scrape.core.base.PluginBase`
- **Loader:** `suu_scrape.core.loader` — scans the plugins directory at runtime, no registration needed.

### Included plugins

| Plugin | File | Active by default | Notes |
|--------|------|-------------------|-------|
| JSON Export | `plugins/json_export.py` | Yes | Saves scraped data to a timestamped `.json` file. |
| CSV Export | `plugins/csv_export.py` | Only with `--csv` | Flat `.csv` with one row per candidate. |
| Supabase Upload | `plugins/supabase_upload.py` | Only when `.env.local` credentials are present | Upserts into Supabase / PostgreSQL tables. |
| Hello World | `plugins/hello_world.py` | Yes (demo) | Prints a confirmation to the console. Use as a template. |

### Supabase configuration

Create a `.env.local` file in the project root:

```bash
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

The upload plugin will activate automatically when both values are present.

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

The plugin is discovered and run automatically — no further registration needed.

#### `context` keys

| Key | Type | Description |
|-----|------|-------------|
| `scrape_type` | `str` | `"election"` or `"whatson"` |
| `election_name` | `str` | Name of the scraped election *(election scrapes only)* |
| `export_csv` | `bool` | `True` when `--csv` was passed *(election scrapes only)* |
| `app_name` | `str` | Always `"suu-scrape"` |
| `version` | `str` | Package version string |
```

Now let me apply this content to the actual file: