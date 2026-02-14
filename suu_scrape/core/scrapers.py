from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time
import re

class ScraperBase(ABC):
    """
    Abstract base class for all scrapers.
    """
    @abstractmethod
    def scrape(self) -> Any:
        """
        Perform the scraping and return the data.
        """
        pass

def get_all_elections(page: int = 0) -> List[Dict[str, str]]:
    """
    Fetches the list of all elections from the SUUCL website.
    Returns a list of dicts with 'title' and 'url'.
    """
    url = "https://studentsunionucl.org/election/list"
    if page > 0:
        url += f"?page={page}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        elections = []
        # The list is usually in a view-content or similar. 
        # Inspecting standard drupal views structure or just finding all links in main content.
        # Based on typical SUUCL structure:
        
        # Look for the main content area
        content = soup.find('section', id='block-system-main')
        if not content:
            content = soup # Fallback
            
        # Find headers or links that look like elections
        # Usually they are in <h2><a>...</a></h2> or similar list items
        # Let's try finding links that start with /election/
        
        for a in content.find_all('a', href=True):
            href = a['href']
            # Normalized check
            if href.startswith('/election/') and 'list' not in href:
                title = a.get_text(strip=True)
                full_url = "https://studentsunionucl.org" + href
                
                # Deduplicate
                if not any(e['url'] == full_url for e in elections):
                    elections.append({'title': title, 'url': full_url})
                    
        return elections
        
    except Exception as e:
        print(f"Error fetching election list: {e}")
        return []

class GenericElectionScraper(ScraperBase):
    """
    Scrapes a specific election given its URL.
    """
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
    }

    def __init__(self, election_url: str):
        self.base_url = election_url
        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update(self.HEADERS)
        
        self.network_links_map = None # Lazy load
        self.societies_map = {}
        self.officials_list = []
        self.processed_links = set()
        self.network_links_map = None

    def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def get_network_links_map(self) -> Dict[str, str]:
        if self.network_links_map is not None:
             return self.network_links_map
             
        print("Fetching /networks to build link map...")
        url = "https://studentsunionucl.org/networks"
        soup = self.get_soup(url)
        network_map = {}
        if not soup:
            self.network_links_map = network_map
            return network_map

        cards = soup.find_all(class_='card')
        for card in cards:
            title_div = card.find(class_='card_title_field')
            link_tag = card.find('a', class_='card-link')
            
            if title_div and link_tag:
                name = title_div.get_text(strip=True)
                href = link_tag.get('href')
                if href:
                    full_link = "https://studentsunionucl.org" + href if href.startswith('/') else href
                    network_map[name.lower()] = full_link
        
        self.network_links_map = network_map
        return network_map

    # ... (methods 117-283 remain unchanged, effectively, but this tool replaces blocks so I must be careful not to consume them if I can avoid it.
    # Actually, I can just replace __init__ and get_network_links_map, and then scrape separately?
    # No, scrape uses it.
    
    # Let's replace __init__ first to add the None init.
    
    # ... wait, I can do it in one go if I include enough context, but the file is large.
    # I will replace __init__ and get_network_links_map.
    
    # And then I will replace scrape to remove the initial call and use the getter (or just call get_network_links_map() which now caches).
    
    # Let's do the scrape method modification first? Or __init__?
    # I'll do __init__ and get_network_links_map first.
    
    
    
    # actually, I will just modify scrape to NOT call it at start.
    # And modify the loop to call it if needed.
    
    # But first, I need `self.network_links_map` to be stored in the instance if I want to cache it.
    # The current code didn't store it in self, it returned it.
    
    # So:
    # 1. Update __init__ to set self.network_links_map = None
    # 2. Update get_network_links_map to check self.network_links_map
    # 3. Update scrape to NOT call it at top, and call it when needed.
    
    # Step 1 & 2:
    pass

    # The tool input above was getting messy. Let's restart the tool input construction.
    # target: __init__ lines 82-84
    # target: get_network_links_map lines 95-96
    
    # I'll do __init__ first.
    pass

    def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def get_network_links_map(self) -> Dict[str, str]:
        if self.network_links_map is not None:
            return self.network_links_map
            
        print("Fetching /networks to build link map...")
        url = "https://studentsunionucl.org/networks"
        soup = self.get_soup(url)
        network_map = {}
        if not soup:
            return network_map

        cards = soup.find_all(class_='card')
        for card in cards:
            title_div = card.find(class_='card_title_field')
            link_tag = card.find('a', class_='card-link')
            
            if title_div and link_tag:
                name = title_div.get_text(strip=True)
                href = link_tag.get('href')
                if href:
                    full_link = "https://studentsunionucl.org" + href if href.startswith('/') else href
                    network_map[name.lower()] = full_link
        
        self.network_links_map = network_map
        return network_map

    def parse_profile_for_pronouns(self, url: str) -> str:
        soup = self.get_soup(url)
        if not soup:
            return "Unknown"
    
        pronoun_field = soup.find(class_=re.compile(r'field--name-field-pronouns|pronouns', re.I))
        if pronoun_field:
            text = pronoun_field.get_text(strip=True)
            clean_text = re.sub(r'^.*?Preferred\s*pronouns?[\W_]*', '', text, flags=re.IGNORECASE|re.DOTALL).strip()
            return clean_text
            
        text = soup.get_text()
        match = re.search(r'\((she/her|he/him|they/them|he/they|she/they)\)', text, re.IGNORECASE)
        if match:
            return match.group(1)
            
        return "Unknown"

    def extract_society_link(self, soup: BeautifulSoup) -> Optional[str]:
        field = soup.find(class_=re.compile(r'field--name-field-related-groups|field--name-field-election-post-club-society'))
        if field:
            link = field.find('a')
            if link:
                href = link.get('href')
                if href and "clubs-societies" in href:
                     return "https://studentsunionucl.org" + href

        labels = soup.find_all(string=re.compile(r'Clubs/Societies|Club and Society positions'))
        for label in labels:
            container = label.find_parent('div', class_=re.compile(r'field'))
            if container:
                link = container.find('a')
                if link:
                    href = link.get('href')
                    if "election-post-categories" in href:
                        continue
                    return "https://studentsunionucl.org" + href
        return None

    def parse_page_data(self, soup: BeautifulSoup, role_title: str, include_rounds: bool = False, include_tallies: bool = False) -> Tuple[List[Dict], Optional[str], List[Dict], Dict[str, float]]:
        candidates_data = []
        
        rounds_data = []
        final_tallies = {}

        if include_rounds or include_tallies:
            round_divs = soup.find_all('div', class_='election__round')
            for r_div in round_divs:
                header = r_div.find(class_='election__round_header')
                round_name = header.get_text(strip=True) if header else "Unknown Round"
                
                table = r_div.find('table', class_='election__single_round_table')
                votes = {}
                if table:
                    rows = table.find_all('tr')
                    for row in rows:
                        th = row.find('th')
                        td = row.find('td')
                        if th and td:
                            # Clean name: "Name [ID]" -> "Name"
                            raw_name = th.get_text(strip=True)
                            c_name = re.sub(r'\s*\[\d+\]$', '', raw_name)
                            try:
                                vote_count = float(td.get_text(strip=True))
                            except ValueError:
                                vote_count = 0.0
                            votes[c_name] = vote_count
                
                rounds_data.append({
                    "round": round_name,
                    "votes": votes
                })
            
            # If tallies requested, get the last round's votes
            if include_tallies and rounds_data:
                final_tallies = rounds_data[-1]['votes']
                # Try to find Round 1
                for r in rounds_data:
                    if "Round 1" in r['round']:
                        initial_tallies = r['votes']
                        break
                else:
                    # Fallback if "Round 1" not named exactly or missing, use first round?
                    # valid rounds usually start with Round 1.
                    initial_tallies = rounds_data[0]['votes'] if rounds_data else {}

        # 1. Identify Winners
        winner_names = set()
        winner_block = soup.find(class_='field--name-count-candidates-elected')
        if winner_block:
            winner_links = winner_block.find_all('a')
            for link in winner_links:
                winner_names.add(link.get_text(strip=True))

        # 2. Identify All Candidates (from the list)
        candidates_list_section = soup.find(class_='candidates_list')
        all_candidate_names = []
        is_active_election = False
        
        if candidates_list_section:
            is_active_election = True 
            cand_rows = candidates_list_section.find_all(class_='views-row')
            for row in cand_rows:
                # prioritize field--name-name to avoid pronouns
                name_el = row.find(class_='field--name-name')
                if not name_el:
                     name_el = row.find(class_=re.compile(r'candidate-name-container|field--name-name|candidate_name'))
                
                if name_el:
                    all_candidate_names.append(name_el.get_text(strip=True))
        
        # If no candidate list found, falling back to just winners (if any)
        if not all_candidate_names:
            all_candidate_names = list(winner_names)

        if not all_candidate_names:
             # Check for RON completion if no candidates found either
             if "Re-open nominations is a winner" in soup.get_text() and "Yes" in soup.get_text():
                  return [], None, [], {}
             return [], None, [], {}

        society_link = self.extract_society_link(soup)

        # 3. Extract Data for Each Candidate
        for c_name in all_candidate_names:
            if c_name.lower() == "ron (re-open nominations)":
                continue

            is_winner = c_name in winner_names
            
            profile_url = None
            
            # Try to find profile URL from winner block if present
            if winner_block:
                winner_links = winner_block.find_all('a')
                for link in winner_links:
                    if link.get_text(strip=True) == c_name:
                         href = link.get('href')
                         if href:
                             profile_url = "https://studentsunionucl.org" + href
                         break
            
            # If not in winner block, or no winner block, try to find in candidate list
            row_element = None
            if candidates_list_section:
                 cand_rows = candidates_list_section.find_all(class_='views-row')
                 for row in cand_rows:
                    row_name = None
                    n_el = row.find(class_='field--name-name')
                    if not n_el:
                         n_el = row.find(class_=re.compile(r'candidate-name-container|field--name-name|candidate_name'))
                    if n_el:
                        row_name = n_el.get_text(strip=True)
                    
                    if row_name == c_name:
                        row_element = row
                        # Seek profile link in the row if we haven't found it yet
                        if not profile_url:
                            # Sometimes the name itself is a link or there is a link in the row
                            link = row.find('a', href=True) # This might be too broad, but let's see
                            # Usually candidate list doesn't link to profile in the same way, 
                            # but sometimes the image is a link.
                            pass
                        break

            pronouns = "Unknown"
            if profile_url:
                # time.sleep(0.1) # Be nice
                pronouns = self.parse_profile_for_pronouns(profile_url) # This effectively does a fetch
                
            image_url = None
            statement = "Statement not found"
            
            if row_element:
                img_tag = row_element.find('img')
                if img_tag:
                    src = img_tag.get('src')
                    if src.startswith('/'):
                        image_url = "https://studentsunionucl.org" + src
                    else:
                        image_url = src
                
                text_section = row_element.find(class_='text_section')
                if not text_section:
                    text_section = row_element.find(class_=re.compile(r'field--name-field-manifesto'))
                
                if text_section:
                    full_text = text_section.get_text(separator='\n', strip=True)
                    # Clean up if name is prefixed
                    if full_text.startswith(c_name):
                        full_text = full_text[len(c_name):].strip()
                    statement = full_text

            cand_dict = {
                "name": c_name,
                "pronouns": pronouns,
                "image_url": image_url,
                "election_statement": statement,
                "role": role_title,
                "is_winner": is_winner
            }
            
            if include_tallies:
                cand_dict['initial_tally'] = initial_tallies.get(c_name, 0.0)
                cand_dict['final_tally'] = final_tallies.get(c_name, 0.0)

            candidates_data.append(cand_dict)

        return candidates_data, society_link, rounds_data, final_tallies

    def parse_candidate_page(self, url: str, role_title: str, include_rounds: bool = False, include_tallies: bool = False) -> Tuple[List[Dict], List[Dict]]:
        soup = self.get_soup(url)
        if not soup:
            return [], []
            
        winners, society_link, rounds, tallies = self.parse_page_data(soup, role_title, include_rounds, include_tallies)
        for w in winners:
            w['meta_society_link'] = society_link
            
        return winners, rounds

    def get_result_links(self) -> List[Tuple[str, str]]:
        links = []
        page = 0
        MAX_PAGES = 80 
        
        while page < MAX_PAGES:
            # print(f"  Scanning Listing Page {page}...")
            url = f"{self.base_url}?page={page}"
            soup = self.get_soup(url)
            
            if not soup:
                page += 1
                continue
                
            table = soup.find('table', class_='views-table')
            if not table:
                break
                
            rows = table.find_all('tr')
            if not rows:
                break
                
            for row in rows:
                name_td = row.find('td', class_='views-field-name')
                if not name_td: continue
                name_link = name_td.find('a')
                if not name_link: continue
                    
                full_title = name_link.get_text(strip=True)
                
                actions_td = row.find('td', class_='views-field-election-post-actions')
                result_link = None
                if actions_td:
                    link_tag = actions_td.find('a', href=re.compile(r'\?results='))
                    if link_tag:
                        result_link = "https://studentsunionucl.org" + link_tag.get('href')
                
                # Use the main position link as fallback
                if not result_link and name_link:
                     href = name_link.get('href')
                     if href:
                         result_link = "https://studentsunionucl.org" + href

                if result_link:
                    links.append((full_title, result_link))
                    
            page += 1
            
        return links

    def scrape(self, include_rounds: bool = False, include_tallies: bool = False) -> Dict[str, Any]:
        
        links = self.get_result_links()
        
        positions = []
        
        for i, (full_title, result_link) in enumerate(links):
            if result_link in self.processed_links:
                continue

            # print(f"[{i+1}/{len(links)}] {full_title} -> {result_link}")
            
            group_name = "Union"
            group_type = "Union"
            role = full_title
            
            if ":" in full_title:
                parts = full_title.split(":", 1)
                group_name = parts[0].strip()
                role = parts[1].strip()
                
                if "Network" in group_name:
                    group_type = "Network"
                elif "Club" in group_name:
                    group_type = "Club"
                elif "Society" in group_name:
                    group_type = "Society"
                else:
                    group_type = "Other"
            
            # Scrape candidates/options
            candidates_data, rounds_data = self.parse_candidate_page(result_link, role, include_rounds=include_rounds, include_tallies=include_tallies)
            
            # Extract meta_society_link if present (for the group)
            group_link = None
            for cand in candidates_data:
                if 'meta_society_link' in cand and cand['meta_society_link']:
                    group_link = cand['meta_society_link']
                    break
            
            # If no link found and it's a network, try lazy load
            if not group_link and group_type == "Network":
                 network_links_map = self.get_network_links_map()
                 s_lower = group_name.lower()
                 for net_name, net_url in network_links_map.items():
                     if net_name.lower() in s_lower or s_lower in net_name.lower():
                         group_link = net_url
                         break

            # Clean up candidate data
            clean_candidates = []
            for cand in candidates_data:
                c_copy = cand.copy()
                c_copy.pop('meta_society_link', None)
                c_copy.pop('role', None) # Role is on the position now
                clean_candidates.append(c_copy)

            pos_dict = {
                "title": role,
                "group": group_name,
                "group_type": group_type,
                "group_link": group_link,
                "candidates": clean_candidates
            }
            
            if include_rounds:
                pos_dict['voting_rounds'] = rounds_data

            positions.append(pos_dict)
            
            self.processed_links.add(result_link)
            
        print("Scrape complete.")
        return {
            "election": {
                "name": "Scraped Election", 
                "url": self.base_url
            },
            "positions": positions
        }
