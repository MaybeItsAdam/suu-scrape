from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup
import concurrent.futures
from .browser import get_selenium_driver

BASE_URL = "https://studentsunionucl.org/whats-on"
UK_TZ = ZoneInfo("Europe/London")

class WhatsOnScraper:
    def __init__(self, start_date=None, end_date=None):
        uk_now = datetime.now(UK_TZ)
        self.start_date = start_date or uk_now.strftime("%Y-%m-%d")
        self.end_date = end_date or (uk_now + timedelta(days=7)).strftime("%Y-%m-%d")
        self.events = []

    def fetch_description(self, session, event):
        """
        Helper to fetch description for a single event.
        """
        try:
            url = event['link']
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                print(f"Failed to fetch {url}: {resp.status_code}")
                return
                
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Strategy 1: Standard Body
            body = soup.select_one(".field--name-body")
            if body:
                text = body.get_text(separator='\n', strip=True)
                if text:
                    event['description'] = text
                    return
    
            # Strategy 2: Node Content fallback
            content = soup.select_one(".node__content")
            if content:
                text = content.get_text(separator='\n', strip=True)
                if text:
                    event['description'] = text
    
        except Exception as e:
            print(f"Error fetching description for {event.get('title')}: {e}")

    def enrich_event_details(self, events):
        """
        Visit each event link PARALLELLY to extract full description.
        """
        if not events: return
        
        print(f"Enriching {len(events)} events with details in parallel...")
        
        with requests.Session() as session:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(self.fetch_description, session, event) for event in events]
                concurrent.futures.wait(futures)

    def scrape(self):
        print(f"Scraping What's On from {self.start_date} to {self.end_date}...")
        driver = get_selenium_driver(headless=True)
        wait = WebDriverWait(driver, 10)
        
        url = f"{BASE_URL}?s={self.start_date}&e={self.end_date}"
        
        try:
            driver.get(url)
            time.sleep(5) # Let JS load
            
            # Wait for React to mount
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".whats-on-container")))
            except:
                print("Container not found within 10s.")
            
            # 1. Force Date Update
            try:
                date_input = driver.find_element(By.CSS_SELECTOR, "input.whats-on-datepicker")
                if date_input:
                    driver.execute_script("""
                        let input = arguments[0];
                        let dateStr = arguments[1];
                        let lastValue = input.value;
                        input.value = dateStr;
                        let event = new Event('input', { bubbles: true });
                        event.simulated = true;
                        let tracker = input._valueTracker;
                        if (tracker) {
                            tracker.setValue(lastValue);
                        }
                        input.dispatchEvent(event);
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    """, date_input, self.start_date)
                    time.sleep(3) # Wait for update
            except Exception as e:
                print(f"Failed to set date input: {e}")
    
            # 2. Switch to List View
            try:
                list_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'List')]")
                list_btn.click()
                time.sleep(2)
            except:
                print("Could not find/click List button. Staying in Week view.")
            
            # 3. Navigate to the correct week (Basic attempt, might need robust logic if date set failed)
            
            # 4. Extract Events from List View
            max_pages = 200 # Safety limit
            page_count = 0
            
            while page_count < max_pages:
                page_count += 1
                print(f"Scraping Page {page_count}...")
                
                rows = driver.find_elements(By.CSS_SELECTOR, ".rbc-list-content .rbc-list-table > tbody > div")
                
                current_date_obj = None
                last_event_date = None
                
                for row in rows:
                    try:
                        class_attr = row.get_attribute("class")
                        
                        if "day-header" in class_attr:
                            header_text = row.text.strip()
                            try:
                                current_date_obj = datetime.strptime(header_text, "%A %d %B %Y").date()
                                last_event_date = current_date_obj
                            except Exception as e:
                                print(f"Failed to parse date header '{header_text}': {e}")
                            continue
                        
                        if "card-grid" in class_attr:
                            if not current_date_obj:
                                continue 
                            
                            try:
                                link_el = row.find_element(By.TAG_NAME, "a")
                                link = link_el.get_attribute("href")
                            except: 
                                continue
                            
                            if any(e['link'] == link for e in self.events):
                                continue
                            
                            time_str = "00:00"
                            title_str = ""
                            try:
                                title_container = row.find_element(By.CSS_SELECTOR, ".MuiListItemText-primary")
                                title_text_full = title_container.text
                                title_str = title_text_full
                                try:
                                    time_div = title_container.find_element(By.CSS_SELECTOR, ".list-item--time")
                                    time_str = time_div.text.strip()
                                    title_str = title_text_full.replace(time_str, "").strip()
                                except:
                                    pass
                            except:
                                continue
                            
                            # Parse times
                            start_time_iso = datetime.combine(current_date_obj, datetime.strptime("00:00", "%H:%M").time(), tzinfo=UK_TZ).isoformat()
                            end_time_iso = datetime.combine(current_date_obj, datetime.strptime("23:59", "%H:%M").time(), tzinfo=UK_TZ).isoformat()

                            if "–" in time_str or "-" in time_str:
                                parts = time_str.replace("–", "-").split("-")
                                if len(parts) >= 1:
                                    s_time = parts[0].strip()
                                    try:
                                        start_dt = datetime.combine(current_date_obj, datetime.strptime(s_time, "%H:%M").time(), tzinfo=UK_TZ)
                                        start_time_iso = start_dt.isoformat()
                                    except: pass
                                if len(parts) >= 2:
                                    e_time = parts[1].strip()
                                    try:
                                        end_dt = datetime.combine(current_date_obj, datetime.strptime(e_time, "%H:%M").time(), tzinfo=UK_TZ)
                                        end_time_iso = end_dt.isoformat()
                                    except: pass
                            
                            location = ""
                            society = ""
                            try:
                                meta_container = row.find_element(By.CSS_SELECTOR, ".MuiListItemText-secondary")
                                try:
                                    loc_span = meta_container.find_element(By.CSS_SELECTOR, ".list-item--location span")
                                    location = loc_span.text.strip()
                                except: pass
                                try:
                                    group_span = meta_container.find_element(By.CSS_SELECTOR, ".list-item--group span")
                                    society = group_span.text.strip()
                                except: pass
                            except: pass
                                
                            self.events.append({
                                "title": title_str,
                                "link": link,
                                "start_time": start_time_iso,
                                "end_time": end_time_iso,
                                "location": location,
                                "host_name": society,
                                "description": "" # Will be enriched
                            })
                                
                    except Exception as row_e:
                        pass
                
                target_end_date = datetime.strptime(self.end_date, "%Y-%m-%d").date()
                if last_event_date and last_event_date >= target_end_date:
                    print(f"Reached target date {last_event_date}, stopping pagination.")
                    break
                
                # Pagination
                try:
                    toolbar_next = driver.find_element(By.XPATH, "//span[@class='rbc-btn-group']/button[contains(text(), 'Next')]")
                    if toolbar_next and toolbar_next.is_displayed():
                        toolbar_next.click()
                        time.sleep(3)
                    else:
                        break
                except:
                    break
            
            self.enrich_event_details(self.events)
                    
        except Exception as e:
            print(f"Failed during scrape: {e}")
        finally:
            if driver:
                driver.quit()
                
        return {"events": self.events}
