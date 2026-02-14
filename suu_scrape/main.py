import os
import sys
import click
from dotenv import load_dotenv
from suu_scrape.core.loader import discover_plugins
from suu_scrape.core.scrapers import GenericElectionScraper, get_all_elections

# Load environment variables
load_dotenv('.env.local')

@click.group()
def cli():
    """SUU Scraper CLI"""
    pass

@cli.command()
@click.argument('name', required=False)
@click.option('--rounds', is_flag=True, help="Include voting rounds data.")
@click.option('--tallies', is_flag=True, help="Include final vote tallies.")
@click.option('--csv', is_flag=True, help="Export data to CSV.")
def election(name, rounds, tallies, csv):
    """
    Scrape an election by name.
    If name is not provided or ambiguous, you will be prompted to select one.
    """
    click.echo("Fetching active elections...")
    page = 0
    while True:
        elections = get_all_elections(page=page)
        
        if not elections and page == 0:
            click.echo("No elections found on the list page.")
            return

        if not elections:
            click.echo("No more elections found.")
            # If we were paging, maybe go back or exit? 
            # For simplicity, let's just break or offer to go back. 
            # But the user logic below handles selection.
            # If page > 0 and no elections, we should probably just say so and exit loop?
            break

        # If name was provided and matches found on first page, we handled it above.
        # But if we are paging, we are likely in interactive mode.
        
        # We need to handle the "name" argument logic carefully with pagination.
        # If name is provided, we only search page 0 (current behavior) or we'd need to scrape all pages.
        # Let's assume pagination is for interactive browsing when name is NOT provided or ambiguous.
        
        selected_election = None
        
        if name and page == 0:
             # Fuzzy match only on first page for now
            matches = [e for e in elections if name.lower() in e['title'].lower()]
            
            if len(matches) == 1:
                selected_election = matches[0]
                click.echo(f"Found election: {selected_election['title']}")
                break
            elif len(matches) > 1:
                click.echo(f"Multiple matches found for '{name}':")
                for i, match in enumerate(matches):
                    click.echo(f"{i+1}. {match['title']}")
                
                choice = click.prompt("Please enter the number of the election to scrape", type=int)
                if 1 <= choice <= len(matches):
                    selected_election = matches[choice-1]
                    break
                else:
                    click.echo("Invalid selection.")
                    return
            else:
                click.echo(f"No matches found for '{name}' on page {page}.")
                # Fall through to list all? Or exit?
                # Current behavior was fall through.
        
        if not selected_election:
             click.echo(f"\nAvailable elections (Page {page}):")
             for i, e in enumerate(elections):
                 click.echo(f"{i+1}. {e['title']}")
             
             click.echo(f"{len(elections)+1}. Next Page")
             
             choice = click.prompt("Please enter the number of the election to scrape", type=int)
             
             if choice == len(elections) + 1:
                 page += 1
                 continue
             elif 1 <= choice <= len(elections):
                 selected_election = elections[choice-1]
                 break
             else:
                 click.echo("Invalid selection.")
                 return

    if not selected_election:
        click.echo("Aborted.")
        return

    click.echo(f"Starting scrape for: {selected_election['title']} ({selected_election['url']})")

    # Initialize scraper
    scraper = GenericElectionScraper(selected_election['url'])
    
    # Run scraper
    scraped_data = scraper.scrape(include_rounds=rounds, include_tallies=tallies)
    
    count = 0
    if isinstance(scraped_data, dict):
        count = len(scraped_data.get('societies', [])) + len(scraped_data.get('officials', [])) + len(scraped_data.get('positions', []))
    elif isinstance(scraped_data, list):
        count = len(scraped_data)
        
    click.echo(f"Scraped {count} items.")

    # Context to pass to plugins
    context = {
        "app_name": "suu-scrape",
        "version": "0.1.0",
        "scrape_type": "election",
        "election_name": selected_election['title'],
        "export_csv": csv
    }

    run_plugins(scraped_data, context)

@cli.command()
@click.option('--start', help='Start date (YYYY-MM-DD)')
@click.option('--end', help='End date (YYYY-MM-DD)')
def whatson(start, end):
    """
    Scrape What's On calendar events.
    """
    from suu_scrape.core.whatson import WhatsOnScraper
    
    click.echo(f"Starting What's On scraper...")
    scraper = WhatsOnScraper(start_date=start, end_date=end)
    scraped_data = scraper.scrape()
    
    count = len(scraped_data.get('events', []))
    click.echo(f"Scraped {count} events.")
    
    context = {
        "app_name": "suu-scrape",
        "scrape_type": "whatson"
    }
    
    # Discover and run plugins (reusing logic or extracting to helper)
    run_plugins(scraped_data, context)

def run_plugins(data, context):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plugins_dir = os.path.join(base_dir, 'plugins')
    # click.echo(f"Discovering plugins in {plugins_dir}...")
    plugin_classes = discover_plugins(plugins_dir)
    
    for PluginClass in plugin_classes:
        try:
            plugin_instance = PluginClass()
            # click.echo(f"\n--- Running {PluginClass.__name__} ---")
            plugin_instance.setup(config={}) 
            plugin_instance.run(data, context)
        except Exception as e:
            click.echo(f"Error running plugin {PluginClass.__name__}: {e}")

def main():
    cli()

if __name__ == "__main__":
    main()
