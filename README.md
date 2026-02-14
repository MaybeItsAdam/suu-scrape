# suu-scrape

A modular scraper system for Students' Union UCL data, built with a plugin architecture and CLI.

## Installation

1.  Clone the repository.
2.  Install dependencies (preferably in a virtual environment):

```bash
pip install -e .
```

## Plugins & Data Output
The scraper uses a plugin system to handle data export. All active plugins in the `suu_scrape/plugins/` directory are automatically discovered and executed after a scrape completes.

### Included Plugins

#### 1. JSON Export (Default)
**File:** `suu_scrape/plugins/json_export.py`  
**Status:** Active  
**Description:** Saves all scraped data to a local JSON file. This is the primary way to access the data if you haven't configured a database.  
- **Output:** `scrape_election_<name>_<timestamp>.json`
- **Config:** None.
26: 
27: #### 2. CSV Export (Optional)
28: **File:** `suu_scrape/plugins/csv_export.py`
29: **Status:** Conditional (Runs only if `--csv` flag is used)
30: **Description:** Exports a flattened CSV file with one row per candidate. useful for spreadsheet analysis.
31: - **Output:** `scrape_election_<name>_<timestamp>.csv`
32: - **Columns:** position, group, candidate_name, is_winner, tallies, etc.

#### 2. Supabase / Postgres (Optional)
**File:** `suu_scrape/plugins/supabase_upload.py`  
**Status:** Conditional (Runs only if credentials are present)  
**Description:** Upserts scraped data into a Supabase (PostgreSQL) database. Segments data into `Society`, `ElectionPosition`, `Candidate`, or `AdhocEvent` tables.  
- **Config:** Create a `.env.local` file with:
    ```bash
    NEXT_PUBLIC_SUPABASE_URL=your_url
    SUPABASE_SERVICE_ROLE_KEY=your_key
    ```

#### 3. Hello World (Template)
**File:** `suu_scrape/plugins/hello_world.py`  
**Status:** Active (Demonstration)  
**Description:** A simple template plugin that prints receiving data to the console. Use this as a starting point for creating your own plugins.

### Adding Your Own Database
To add support for a different database (e.g., MongoDB, PostgreSQL, SQLite):
1.  Create a file in `suu_scrape/plugins/` (e.g., `my_db_plugin.py`).
2.  Inherit from `PluginBase` and implement the `run` method to insert data into your DB.
3.  The system will automatically discover and run your plugin.

## Usage

The scraper provides a command-line interface `suu-scrape`.

### 1. Election Scraper

Scrape candidates and results for specific elections.

**List all available elections:**
```bash
suu-scrape election
```

**Select a specific election by name (fuzzy match):**
```bash
suu-scrape election "Leadership"
```

If multiple elections match or none are found, you will be prompted to select from a list.

**Export Options & Data:**
```bash
# Include voting rounds and final vote tallies
suu-scrape election "Rep Elections" --rounds --tallies

# Export to CSV (in addition to JSON)
suu-scrape election "Rep Elections" --csv
```

### 2. What's On Scraper

Scrape events from the What's On calendar.

**Scrape current week:**
```bash
suu-scrape whatson
```

**Scrape specific date range:**
```bash
suu-scrape whatson --start 2025-02-10 --end 2025-02-17
```

## Plugin Architecture

The system uses plugins rooted in `suu_scrape/plugins/` to process scraped data.

-   **Base Class**: `suu_scrape.core.base.PluginBase`
-   **Loader**: `suu_scrape.core.loader` discovers plugins automatically.

### Creating a Plugin

1.  Create a new `.py` file in `suu_scrape/plugins/`.
2.  Inherit from `PluginBase`.
3.  Implement `run(self, data, context)`.

```python
from suu_scrape.core.base import PluginBase

class MyPlugin(PluginBase):
    def run(self, data: dict, context: dict) -> None:
        print(f"Received {len(data.get('events', []))} events")
```
