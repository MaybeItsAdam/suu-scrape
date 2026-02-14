import json
import os
from datetime import datetime
from suu_scrape.core.base import PluginBase

class JsonExportPlugin(PluginBase):
    """
    Plugin to save scraped data to a JSON file.
    """
    def run(self, data: any, context: dict) -> None:
        print("--- Running JsonExportPlugin ---")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        scrape_type = context.get('scrape_type', 'unknown')
        
        name_part = ""
        if 'election_name' in context:
            # Simple sanitization
            safe_name = "".join([c if c.isalnum() else "_" for c in context['election_name']]).strip('_')
            # Truncate if too long and remove duplicate underscores
            safe_name = "_".join(filter(None, safe_name.split('_')))[:50]
            name_part = f"_{safe_name.lower()}"
            
        filename = f"scrape_{scrape_type}{name_part}_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, default=str)
            print(f"Saved data to {filename}")
        except Exception as e:
            print(f"Error saving JSON: {e}")
