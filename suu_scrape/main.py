from __future__ import annotations

import os
from typing import Any, Optional

import click
from dotenv import load_dotenv

from suu_scrape.core.browser import clear_session, quit_driver
from suu_scrape.core.loader import discover_plugins
from suu_scrape.core.scrapers import GenericElectionScraper, get_all_elections

_ = load_dotenv(".env.local")


@click.group()
def cli() -> None:
    """SUU Scraper CLI"""
    pass


@cli.command()
@click.argument("name", required=False, default=None)
@click.option("--rounds", is_flag=True, help="Include voting rounds data.")
@click.option("--tallies", is_flag=True, help="Include final vote tallies.")
@click.option("--csv", is_flag=True, help="Export data to CSV.")
@click.option("--sheets", is_flag=True, help="Copy data as TSV to clipboard for pasting into Google Sheets.")
@click.option("--xlsx", is_flag=True, help="Export data to a .xlsx file (opens in Google Sheets or Excel).")
@click.option(
    "--upload",
    is_flag=True,
    help="Upload to Supabase (disabled by default).",
)
@click.option(
    "--officers-only",
    is_flag=True,
    help="Only include union-level officer roles (sabbs + student officers). Network committee roles (Secretary, Treasurer, Social Secretary, etc.) are excluded.",
)
@click.option(
    "--key-roles",
    is_flag=True,
    help="Only include President and Treasurer roles across all groups.",
)
@click.option(
    "--winners-only",
    is_flag=True,
    help="Only include winning candidates (strips losers from output).",
)
@click.option(
    "--workers",
    type=click.IntRange(1, 32),
    default=6,
    show_default=True,
    help="Worker threads for scraping result pages (higher is faster).",
)
@click.option(
    "--checkpoint-file",
    default=None,
    help="Path to incremental checkpoint JSON (defaults to .suu_checkpoint_<election>.json).",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from an existing checkpoint file.",
)
def election(
    name: Optional[str],
    rounds: bool,
    tallies: bool,
    csv: bool,
    sheets: bool,
    xlsx: bool,
    upload: bool,
    officers_only: bool,
    key_roles: bool,
    winners_only: bool,
    workers: int,
    checkpoint_file: Optional[str],
    resume: bool,
) -> None:
    """
    Scrape an election by name or direct URL.
    If a URL is given it is used immediately — no search is performed.
    If name is not provided or ambiguous, you will be prompted to select one.
    """
    click.echo("Fetching active elections...")

    selected_election: Optional[dict[str, str]] = None

    # Direct URL — skip the search entirely.
    if name and (name.startswith("http://") or name.startswith("https://")):
        selected_election = {"title": name, "url": name}
        click.echo(f"Using direct URL: {name}")

    # If a name was given, search page-by-page and stop as soon as we find
    # a unique match — avoids fetching pages we don't need.
    elif name:
        click.echo(f"Searching for '{name}'...")
        all_elections: list[dict[str, str]] = []
        p = 0
        matches: list[dict[str, str]] = []
        while True:
            page_results = get_all_elections(page=p)
            if not page_results:
                break
            all_elections.extend(page_results)
            matches = [e for e in all_elections if name.lower() in e["title"].lower()]
            # Stop early the moment we have exactly one match
            if len(matches) == 1:
                break
            p += 1

        if not all_elections:
            click.echo("No elections found.")
            quit_driver()
            return

        if len(matches) == 1:
            selected_election = matches[0]
            click.echo(f"Found: {selected_election['title']}")
        elif len(matches) > 1:
            click.echo(f"Multiple matches for '{name}':")
            for i, match in enumerate(matches):
                click.echo(f"  {i + 1}. {match['title']}")
            choice: int = click.prompt(
                "Please enter the number of the election to scrape", type=int
            )
            if 1 <= choice <= len(matches):
                selected_election = matches[choice - 1]
            else:
                click.echo("Invalid selection.")
                quit_driver()
                return
        else:
            click.echo(f"No matches found for '{name}' — listing all elections.")
            # Fall through to interactive mode below with all pages already loaded
            page = 0
            elections = all_elections

    # Interactive mode — page through and let the user pick
    if not selected_election and not name:
        page = 0
        elections = get_all_elections(page=page) if not name else all_elections  # type: ignore[possibly-undefined]

        if not elections:
            click.echo("No elections found on the list page.")
            quit_driver()
            return

        while True:
            if not elections:
                click.echo("No more elections found.")
                break

            click.echo(f"\nAvailable elections (Page {page}):")
            for i, e in enumerate(elections):
                click.echo(f"  {i + 1}. {e['title']}")
            click.echo(f"  {len(elections) + 1}. Next Page")

            choice = click.prompt(
                "Please enter the number of the election to scrape", type=int
            )

            if choice == len(elections) + 1:
                page += 1
                elections = get_all_elections(page=page)
                continue
            elif 1 <= choice <= len(elections):
                selected_election = elections[choice - 1]
                break
            else:
                click.echo("Invalid selection.")
                quit_driver()
                return

    if not selected_election:
        click.echo("Aborted.")
        quit_driver()
        return

    click.echo(
        f"Starting scrape for: {selected_election['title']} ({selected_election['url']})"
    )

    scraper = GenericElectionScraper(selected_election["url"])
    checkpoint_target = checkpoint_file or scraper.default_checkpoint_path()

    filters = []
    if officers_only:
        filters.append("union & network officers only")
    if key_roles:
        filters.append("presidents & treasurers only")
    if winners_only:
        filters.append("winners only")
    if filters:
        click.echo("Filters: " + ", ".join(filters))
    click.echo(f"Checkpoint: {checkpoint_target}")
    if resume:
        click.echo("Resume mode: enabled")
    click.echo(f"Workers: {workers}")
    if upload:
        click.echo("Supabase upload: enabled")

    click.echo("")

    current_page: list[int] = [-1]

    def on_page(page: int) -> None:
        if page != current_page[0]:
            current_page[0] = page
            click.echo(f"  [page {page + 1}] scanning positions...")

    position_count: list[int] = [0]

    def on_position(idx: int, title: str) -> None:
        position_count[0] = idx
        if not winners_only:
            click.echo(f"    [{idx}] {title}")

    def on_winner(role: str, group: str, winner_names: list[str]) -> None:
        label = f"{group}: {role}" if group and group != "Union" else role
        names = ", ".join(winner_names)
        click.echo(f"    WINNER  {label} — {names}")

    scraped_data: dict[str, Any] = scraper.scrape(
        include_rounds=rounds,
        include_tallies=tallies,
        officers_only=officers_only,
        key_roles_only=key_roles,
        winners_only=winners_only,
        progress_callback=on_position,
        page_callback=on_page,
        winner_callback=on_winner if winners_only else None,
        checkpoint_path=checkpoint_target,
        resume=resume,
        max_workers=workers,
    )

    quit_driver()

    count = len(scraped_data.get("positions", []))
    click.echo(f"\nDone — {count} position(s) kept after filters.")

    context: dict[str, Any] = {
        "app_name": "suu-scrape",
        "version": "0.1.0",
        "scrape_type": "election",
        "election_name": selected_election["title"],
        "export_csv": csv,
        "export_sheets": sheets,
        "export_xlsx": xlsx,
        "upload_supabase": upload,
    }

    run_plugins(scraped_data, context)


@cli.command()
def logout() -> None:
    """
    Clear the saved login session.
    You will be prompted to log in again on the next run.
    """
    clear_session()


@cli.command()
@click.option("--start", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end", default=None, help="End date (YYYY-MM-DD)")
@click.option(
    "--upload",
    is_flag=True,
    help="Upload to Supabase (disabled by default).",
)
def whatson(start: Optional[str], end: Optional[str], upload: bool) -> None:
    """
    Scrape What's On calendar events.
    """
    from suu_scrape.core.whatson import WhatsOnScraper

    click.echo("Starting What's On scraper...")
    scraper = WhatsOnScraper(start_date=start, end_date=end)
    scraped_data: dict[str, Any] = scraper.scrape()

    quit_driver()

    count = len(scraped_data.get("events", []))
    click.echo(f"Scraped {count} events.")

    context: dict[str, Any] = {
        "app_name": "suu-scrape",
        "scrape_type": "whatson",
        "upload_supabase": upload,
    }

    run_plugins(scraped_data, context)


def run_plugins(data: dict[str, Any], context: dict[str, Any]) -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plugins_dir = os.path.join(base_dir, "plugins")
    plugin_classes = discover_plugins(plugins_dir)

    for PluginClass in plugin_classes:
        try:
            module_name = str(getattr(PluginClass, "__module__", "")).lower()
            class_name = str(getattr(PluginClass, "__name__", "")).lower()
            is_supabase_plugin = "supabase" in module_name or "supabase" in class_name
            if is_supabase_plugin and not context.get("upload_supabase", False):
                click.echo(f"Skipping {PluginClass.__name__} (enable with --upload).")
                continue

            plugin_instance = PluginClass()
            plugin_instance.setup(config={})
            plugin_instance.run(data, context)
        except Exception as e:
            click.echo(f"Error running plugin {PluginClass.__name__}: {e}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
