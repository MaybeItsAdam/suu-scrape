import os
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from cuid import cuid
from suu_scrape.core.base import PluginBase

class SupabasePlugin(PluginBase):
    """
    Plugin to upload scraped data to Supabase.
    """
    
    def setup(self, config: dict) -> None:
        self.supabase_url = os.getenv('NEXT_PUBLIC_SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        
        if not self.supabase_key:
            self.supabase_key = os.getenv('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY')
            
        if not self.supabase_url or not self.supabase_key:
            print("Warning: Supabase credentials not found. Plugin will skip upload.")
            self.client = None
        else:
            self.client = create_client(self.supabase_url, self.supabase_key)

    def scrape_union_page(self, union_url):
        """Helper to scrape logo and IG from union page."""
        if not union_url:
            return None, None
        
        logo_url = None
        instagram_url = None
        
        try:
            print(f"  Scraping metadata from {union_url}...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get(union_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"  Failed to fetch: Status {resp.status_code}")
                return None, None
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Logo
            logo_div = soup.find('div', class_='header-logo')
            if logo_div and logo_div.has_attr('style'):
                style = logo_div['style']
                if 'url(' in style:
                    start = style.find('url(') + 4
                    end = style.find(')', start)
                    relative_url = style[start:end].strip("'").strip('"')
                    if relative_url.startswith('/'):
                        logo_url = f"https://studentsunionucl.org{relative_url}"
                    else:
                        logo_url = relative_url
                        
            # Instagram
            social_links = soup.find_all('a', href=True)
            for a in social_links:
                href = a['href']
                if 'instagram.com' in href:
                    if 'studentsunionucl' in href:
                        continue
                    instagram_url = href
                    break
                    
        except Exception as e:
            print(f"  Error scraping metadata: {e}")
            
        return logo_url, instagram_url

    def run(self, data: any, context: dict) -> None:
        if not self.client:
            print("Supabase client not initialized. Skipping upload.")
            return

        print("--- Running SupabasePlugin ---")
        
        # Handle Elections Data
        societies = data.get('societies', [])
        if societies:
            self.process_societies(societies)
            
        # Handle WhatsOn Events
        events = data.get('events', [])
        if events:
            self.process_events(events)
            
        print("Supabase upload complete.")

    def process_societies(self, societies):
        for soc in societies:
            name = soc.get('name')
            union_url = soc.get('link')
            soc_type = soc.get('type', 'Society')
            
            # Basic data
            db_data = {
                "name": name,
                "unionUrl": union_url,
                # "email": ... (if scraped)
            }
            
            logo_url, scraped_ig = self.scrape_union_page(union_url)
            
            if logo_url:
                db_data["logoUrl"] = logo_url
            if scraped_ig:
                db_data["instagram"] = scraped_ig
                
            table_name = 'Network' if soc_type == 'Network' else 'Society'
            
            try:
                # Upsert logic
                existing = self.client.table(table_name).select('id').eq('name', name).execute()
                if existing.data and len(existing.data) > 0:
                    print(f"  Updating {name} in {table_name}")
                    self.client.table(table_name).update(db_data).eq('name', name).execute()
                else:
                    db_data['id'] = cuid()
                    print(f"  Inserting new {name} into {table_name}")
                    self.client.table(table_name).insert(db_data).execute()
                    
            except Exception as e:
                print(f"  Error uploading {name}: {e}")
                
            time.sleep(1) # Be nice

    def process_events(self, events):
        table_name = 'AdhocEvent'
        
        for event in events:
            try:
                # Basic mapping
                db_data = {
                    "title": event.get('title'),
                    "description": event.get('description'),
                    "startTime": event.get('start_time'),
                    "endTime": event.get('end_time'),
                    "location": event.get('location'),
                    "originalPostUrl": event.get('link'),
                    "society": event.get('host_name'),
                    # "hostId": ... need to resolve host if possible
                    "updatedAt": datetime.now().isoformat()
                }
                
                # Check duplication by link/sourceId
                source_id = event.get('link')
                if source_id:
                    db_data['sourceId'] = source_id
                    
                    # Check existence
                    existing = self.client.table(table_name).select('id').eq('sourceId', source_id).execute()
                    if existing.data and len(existing.data) > 0:
                         print(f"  Updating Event: {event['title']}")
                         self.client.table(table_name).update(db_data).eq('sourceId', source_id).execute()
                    else:
                         db_data['id'] = cuid()
                         print(f"  Inserting Event: {event['title']}")
                         self.client.table(table_name).insert(db_data).execute()
                
            except Exception as e:
                print(f"  Error uploading event {event.get('title')}: {e}")
            time.sleep(0.1)
