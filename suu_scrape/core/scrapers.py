from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar, Optional

import requests
from bs4 import BeautifulSoup, Tag
from typing_extensions import override

from suu_scrape.core.browser import get_soup

BASE_URL = "https://studentsunionucl.org"

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ScraperBase(ABC):
    """Abstract base class for all scrapers."""

    @abstractmethod
    def scrape(self) -> dict[str, Any]:
        """Perform the scraping and return the data."""
        ...


# ---------------------------------------------------------------------------
# Election list helper
# ---------------------------------------------------------------------------


# Roles that count as "union officers" (sabbs + non-society elected officers).
# Only pure Union positions (sabbatical + student officers) count — network
# committee roles (Secretary, Treasurer, Social Secretary, etc.) do NOT.
_UNION_GROUP_TYPES = {"Union"}

# Known suffixes that identify a network-level committee role.
# These appear in titles like "POC Network Treasurer" or
# "Disabled Students' Network Social Secretary" — no colon, no group prefix.
_NETWORK_COMMITTEE_SUFFIXES = (
    "secretary",
    "treasurer",
    "welfare officer",
    "social secretary",
    "campaigns representative",
    "media rep",
    "neurodivergent rep",
    "qtpoc",
    "representative",
)

# Role keywords for the --key-roles filter (president / treasurer of any group)
_KEY_ROLE_KEYWORDS = ("president", "treasurer")
_HTTP_TIMEOUT = 20.0
_CHECKPOINT_VERSION = 1


def is_officer_position(pos: dict[str, Any]) -> bool:
    """Return True if *pos* is a union-level officer (sabb or student officer).

    Network *committee* roles (Secretary, Treasurer, Social Secretary, etc.)
    are classified as group_type "NetworkCommittee" and are excluded.
    """
    return pos.get("group_type") in _UNION_GROUP_TYPES


def is_key_role_position(pos: dict[str, Any]) -> bool:
    """Return True if *pos* is a President or Treasurer of any group."""
    role: str = pos.get("title", "").lower()
    return any(kw in role for kw in _KEY_ROLE_KEYWORDS)


def is_winners_only_position(pos: dict[str, Any]) -> bool:
    """Return True if *pos* has at least one winner."""
    return any(c.get("is_winner") for c in pos.get("winners", []))


def filter_position(
    pos: dict[str, Any],
    officers_only: bool = False,
    key_roles_only: bool = False,
    winners_only: bool = False,
) -> Optional[dict[str, Any]]:
    """
    Apply optional filters to a single position dict.

    Returns the (possibly modified) position if it passes all filters,
    or None if it should be dropped.

    officers_only  — keep only union / network officer roles (sabbs + non-society officers)
    key_roles_only — keep only President and Treasurer roles across all groups
    winners_only   — strip losing candidates; drop the position if nobody won yet
    """
    if officers_only and not is_officer_position(pos):
        return None
    if key_roles_only and not is_key_role_position(pos):
        return None
    if winners_only:
        if not is_winners_only_position(pos):
            return None
        winners = [c for c in pos.get("winners", []) if c.get("is_winner")]
        pos = {**pos, "winners": winners}
    return pos


def filter_positions(
    positions: list[dict[str, Any]],
    officers_only: bool = False,
    key_roles_only: bool = False,
    winners_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Apply optional filters to a list of position dicts.
    Delegates to filter_position for each entry.
    """
    result: list[dict[str, Any]] = []
    for pos in positions:
        filtered = filter_position(
            pos,
            officers_only=officers_only,
            key_roles_only=key_roles_only,
            winners_only=winners_only,
        )
        if filtered is not None:
            result.append(filtered)
    return result


def _http_get_soup(
    url: str,
    headers: Optional[dict[str, str]] = None,
    session: Optional[requests.Session] = None,
    timeout: float = _HTTP_TIMEOUT,
) -> Optional[BeautifulSoup]:
    requester = session.get if session is not None else requests.get
    try:
        resp = requester(url, headers=headers, timeout=timeout)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    if "/user/login" in str(resp.url):
        return None
    return BeautifulSoup(resp.text, "html.parser")


def get_all_elections(page: int = 0) -> list[dict[str, str]]:
    """
    Fetch the list of active elections.
    Returns a list of dicts with 'title' and 'url'.
    """
    url = f"{BASE_URL}/election/list"
    if page > 0:
        url += f"?page={page}"

    soup = _http_get_soup(url)
    if not soup:
        soup = get_soup(url)
    if not soup:
        print("Error: could not fetch election list.")
        return []

    content = soup.find("section", id="block-system-main")
    if not isinstance(content, Tag):
        content = soup

    elections: list[dict[str, str]] = []
    for a in content.find_all("a", href=True):
        href: str = str(a.get("href", ""))
        if href.startswith("/election/") and "list" not in href:
            title: str = a.get_text(strip=True)
            full_url = BASE_URL + href
            if not any(e["url"] == full_url for e in elections):
                elections.append({"title": title, "url": full_url})

    return elections


@dataclass
class _PendingPosition:
    full_title: str
    result_link: str
    group_name: str
    group_type: str
    role: str


# ---------------------------------------------------------------------------
# Generic election scraper
# ---------------------------------------------------------------------------


class GenericElectionScraper(ScraperBase):
    """Scrapes a specific election given its URL."""

    _SCRAPER_UA: ClassVar[str] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    )

    base_url: str
    network_links_map: Optional[dict[str, str]]
    societies_map: dict[str, object]
    officials_list: list[object]
    processed_links: set[str]
    _http_local: threading.local

    def __init__(self, election_url: str) -> None:
        self.base_url = election_url
        self.network_links_map = None  # lazily populated
        self.societies_map = {}
        self.officials_list = []
        self.processed_links = set()
        self._http_local = threading.local()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_http_session(self) -> requests.Session:
        session = getattr(self._http_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self._SCRAPER_UA})
            self._http_local.session = session
        return session

    def _get_soup_http(self, url: str) -> Optional[BeautifulSoup]:
        return _http_get_soup(url, session=self._get_http_session())

    def _get_soup(self, url: str) -> Optional[BeautifulSoup]:
        # HTTP is much faster than Selenium for static pages; if blocked,
        # we fall back to browser automation.
        soup = self._get_soup_http(url)
        if soup:
            return soup
        return get_soup(url)

    def _safe_checkpoint_name(self) -> str:
        slug = "".join(
            c if c.isalnum() else "_" for c in self.base_url.lower()
        ).strip("_")
        slug = "_".join(filter(None, slug.split("_")))
        return slug[:80] or "election"

    def default_checkpoint_path(self) -> str:
        return f".suu_checkpoint_{self._safe_checkpoint_name()}.json"

    def get_network_links_map(self) -> dict[str, str]:
        if self.network_links_map is not None:
            return self.network_links_map

        print("Fetching /networks to build link map...")
        soup = self._get_soup(f"{BASE_URL}/networks")
        network_map: dict[str, str] = {}

        if soup:
            for card in soup.find_all(class_="card"):
                if not isinstance(card, Tag):
                    continue
                title_div = card.find(class_="card_title_field")
                link_tag = card.find("a", class_="card-link")
                if title_div and link_tag and isinstance(link_tag, Tag):
                    name: str = title_div.get_text(strip=True)
                    href: str = str(link_tag.get("href", ""))
                    if href:
                        full_link = BASE_URL + href if href.startswith("/") else href
                        network_map[name.lower()] = full_link

        self.network_links_map = network_map
        return network_map

    def _load_checkpoint(
        self, checkpoint_path: Path, expected_options: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        if not checkpoint_path.exists():
            return None
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != _CHECKPOINT_VERSION:
            return None
        if payload.get("base_url") != self.base_url:
            return None
        if payload.get("options") != expected_options:
            return None
        return payload

    def _write_checkpoint(
        self,
        checkpoint_path: Path,
        *,
        options: dict[str, Any],
        positions: list[dict[str, Any]],
        completed: bool,
    ) -> None:
        payload: dict[str, Any] = {
            "version": _CHECKPOINT_VERSION,
            "base_url": self.base_url,
            "options": options,
            "processed_links": sorted(self.processed_links),
            "positions": positions,
            "completed": completed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temp_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temp_path.replace(checkpoint_path)

    def _completed_checkpoint_path(self, checkpoint_path: Path) -> Path:
        if checkpoint_path.suffix:
            return checkpoint_path.with_name(
                f"{checkpoint_path.stem}_completed{checkpoint_path.suffix}"
            )
        return checkpoint_path.with_name(f"{checkpoint_path.name}_completed")

    def _mark_checkpoint_complete(self, checkpoint_path: Path) -> Path:
        completed_path = self._completed_checkpoint_path(checkpoint_path)
        if completed_path == checkpoint_path:
            return checkpoint_path
        try:
            if completed_path.exists():
                completed_path.unlink()
            checkpoint_path.replace(completed_path)
            return completed_path
        except OSError as exc:
            print(f"Warning: failed to rename checkpoint {checkpoint_path}: {exc}")
            return checkpoint_path

    def parse_profile_for_pronouns(
        self,
        url: str,
        soup_fetcher: Optional[Callable[[str], Optional[BeautifulSoup]]] = None,
    ) -> str:
        fetcher = soup_fetcher or self._get_soup
        soup = fetcher(url)
        if not soup:
            return "Unknown"

        pronoun_field = soup.find(
            class_=re.compile(r"field--name-field-pronouns|pronouns", re.I)
        )
        if pronoun_field:
            text: str = pronoun_field.get_text(strip=True)
            clean = re.sub(
                r"^.*?Preferred\s*pronouns?[\W_]*",
                "",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()
            return clean

        body = soup.get_text()
        match = re.search(
            r"\((she/her|he/him|they/them|he/they|she/they)\)",
            body,
            re.IGNORECASE,
        )
        return match.group(1) if match else "Unknown"

    def extract_society_link(self, soup: BeautifulSoup) -> Optional[str]:
        field = soup.find(
            class_=re.compile(
                r"field--name-field-related-groups|field--name-field-election-post-club-society"
            )
        )
        if field and isinstance(field, Tag):
            link = field.find("a")
            if link and isinstance(link, Tag):
                href: str = str(link.get("href", ""))
                if href and "clubs-societies" in href:
                    return BASE_URL + href

        for label in soup.find_all(
            string=re.compile(r"Clubs/Societies|Club and Society positions")
        ):
            container = label.find_parent("div", class_=re.compile(r"field"))
            if container and isinstance(container, Tag):
                link = container.find("a")
                if link and isinstance(link, Tag):
                    href = str(link.get("href", ""))
                    if "election-post-categories" in href:
                        continue
                    return BASE_URL + href
        return None

    # ------------------------------------------------------------------
    # Page parsing
    # ------------------------------------------------------------------

    def parse_page_data(
        self,
        soup: BeautifulSoup,
        role_title: str,
        include_rounds: bool = False,
        include_tallies: bool = False,
        soup_fetcher: Optional[Callable[[str], Optional[BeautifulSoup]]] = None,
    ) -> tuple[
        list[dict[str, Any]], Optional[str], list[dict[str, Any]], dict[str, float]
    ]:
        candidates_data: list[dict[str, Any]] = []
        rounds_data: list[dict[str, Any]] = []
        final_tallies: dict[str, float] = {}
        initial_tallies: dict[str, float] = {}

        if include_rounds or include_tallies:
            for r_div in soup.find_all("div", class_="election__round"):
                if not isinstance(r_div, Tag):
                    continue
                header = r_div.find(class_="election__round_header")
                round_name: str = (
                    header.get_text(strip=True) if header else "Unknown Round"
                )

                votes: dict[str, float] = {}
                table = r_div.find("table", class_="election__single_round_table")
                if table and isinstance(table, Tag):
                    for row in table.find_all("tr"):
                        if not isinstance(row, Tag):
                            continue
                        th = row.find("th")
                        td = row.find("td")
                        if th and td:
                            raw_name: str = th.get_text(strip=True)
                            c_name: str = re.sub(r"\s*\[\d+\]$", "", raw_name)
                            try:
                                vote_count = float(td.get_text(strip=True))
                            except ValueError:
                                vote_count = 0.0
                            votes[c_name] = vote_count

                rounds_data.append({"round": round_name, "votes": votes})

            if include_tallies and rounds_data:
                final_tallies = dict(rounds_data[-1]["votes"])
                for r in rounds_data:
                    if "Round 1" in r["round"]:
                        initial_tallies = dict(r["votes"])
                        break
                else:
                    initial_tallies = (
                        dict(rounds_data[0]["votes"]) if rounds_data else {}
                    )

        # --- Winners ---
        winner_names: set[str] = set()
        winner_block = soup.find(class_="field--name-count-candidates-elected")
        if winner_block and isinstance(winner_block, Tag):
            for link in winner_block.find_all("a"):
                winner_names.add(link.get_text(strip=True))

        # --- All candidates ---
        candidates_list_section = soup.find(class_="candidates_list")
        all_candidate_names: list[str] = []

        if candidates_list_section and isinstance(candidates_list_section, Tag):
            for row in candidates_list_section.find_all(class_="views-row"):
                if not isinstance(row, Tag):
                    continue
                name_el = row.find(class_="field--name-name") or row.find(
                    class_=re.compile(
                        r"candidate-name-container|field--name-name|candidate_name"
                    )
                )
                if name_el:
                    all_candidate_names.append(name_el.get_text(strip=True))

        if not all_candidate_names:
            all_candidate_names = list(winner_names)

        if not all_candidate_names:
            return [], None, [], {}

        society_link = self.extract_society_link(soup)

        # --- Per-candidate data ---
        for c_name in all_candidate_names:
            if c_name.lower() == "ron (re-open nominations)":
                continue

            is_winner = c_name in winner_names
            profile_url: Optional[str] = None

            if winner_block and isinstance(winner_block, Tag):
                for link in winner_block.find_all("a"):
                    if link.get_text(strip=True) == c_name:
                        href = str(link.get("href", ""))
                        if href:
                            profile_url = BASE_URL + href
                        break

            row_element: Optional[Tag] = None
            if candidates_list_section and isinstance(candidates_list_section, Tag):
                for row in candidates_list_section.find_all(class_="views-row"):
                    if not isinstance(row, Tag):
                        continue
                    n_el = row.find(class_="field--name-name") or row.find(
                        class_=re.compile(
                            r"candidate-name-container|field--name-name|candidate_name"
                        )
                    )
                    if n_el and n_el.get_text(strip=True) == c_name:
                        row_element = row
                        break

            pronouns = "Unknown"
            if profile_url:
                pronouns = self.parse_profile_for_pronouns(
                    profile_url, soup_fetcher=soup_fetcher
                )

            image_url: Optional[str] = None
            statement = "Statement not found"

            if row_element:
                img_tag = row_element.find("img")
                if img_tag and isinstance(img_tag, Tag):
                    src: str = str(img_tag.get("src", ""))
                    image_url = BASE_URL + src if src.startswith("/") else src

                text_section = row_element.find(
                    class_="text_section"
                ) or row_element.find(class_=re.compile(r"field--name-field-manifesto"))
                if text_section:
                    full_text: str = text_section.get_text(separator="\n", strip=True)
                    if full_text.startswith(c_name):
                        full_text = full_text[len(c_name) :].strip()
                    statement = full_text

            cand_dict: dict[str, Any] = {
                "name": c_name,
                "pronouns": pronouns,
                "image_url": image_url,
                "election_statement": statement,
                "role": role_title,
                "is_winner": is_winner,
            }

            if include_tallies:
                cand_dict["initial_tally"] = initial_tallies.get(c_name, 0.0)
                cand_dict["final_tally"] = final_tallies.get(c_name, 0.0)

            candidates_data.append(cand_dict)

        return candidates_data, society_link, rounds_data, final_tallies

    def parse_candidate_page(
        self,
        url: str,
        role_title: str,
        include_rounds: bool = False,
        include_tallies: bool = False,
        soup_fetcher: Optional[Callable[[str], Optional[BeautifulSoup]]] = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        fetcher = soup_fetcher or self._get_soup
        soup = fetcher(url)
        if not soup:
            return [], []

        winners, society_link, rounds, _ = self.parse_page_data(
            soup,
            role_title,
            include_rounds,
            include_tallies,
            soup_fetcher=fetcher,
        )
        for w in winners:
            w["meta_society_link"] = society_link

        return winners, rounds

    def _iter_result_links(
        self,
        page_callback: Optional[Any] = None,
    ):
        """
        Yield ``(full_title, result_link)`` tuples one page at a time.

        *page_callback(page_num)* is called as each listing page is fetched,
        so callers can show live progress without pre-fetching everything.
        """
        MAX_PAGES = 80

        for page in range(MAX_PAGES):
            if page_callback is not None:
                page_callback(page)

            soup = self._get_soup(f"{self.base_url}?page={page}")
            if not soup:
                continue

            table = soup.find("table", class_="views-table")
            if not table or not isinstance(table, Tag):
                break

            rows = table.find_all("tr")
            if not rows:
                break

            found_any = False
            for row in rows:
                if not isinstance(row, Tag):
                    continue
                name_td = row.find("td", class_="views-field-name")
                if not name_td or not isinstance(name_td, Tag):
                    continue
                name_link = name_td.find("a")
                if not name_link or not isinstance(name_link, Tag):
                    continue

                full_title: str = name_link.get_text(strip=True)
                result_link: Optional[str] = None

                actions_td = row.find("td", class_="views-field-election-post-actions")
                if actions_td and isinstance(actions_td, Tag):
                    link_tag = actions_td.find("a", href=re.compile(r"\?results="))
                    if link_tag and isinstance(link_tag, Tag):
                        result_link = BASE_URL + str(link_tag.get("href", ""))

                if not result_link:
                    href = str(name_link.get("href", ""))
                    if href:
                        result_link = BASE_URL + href

                if result_link:
                    found_any = True
                    yield (full_title, result_link)

            if not found_any:
                break

    def get_result_links(self) -> list[tuple[str, str]]:
        """Return all result links as a flat list (used externally if needed)."""
        return list(self._iter_result_links())

    def _classify_position(self, full_title: str) -> tuple[str, str, str]:
        group_name = "Union"
        group_type = "Union"
        role = full_title

        if ":" in full_title:
            # Club / Society positions: "Group Name: Role"
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
        elif "Network" in full_title:
            # Network committee roles have no colon and contain "Network":
            #   "POC Network Treasurer"
            #   "Disabled Students' Network Social Secretary"
            role_lower = full_title.lower()
            if any(role_lower.endswith(suf) for suf in _NETWORK_COMMITTEE_SUFFIXES):
                group_type = "NetworkCommittee"
                for suf in _NETWORK_COMMITTEE_SUFFIXES:
                    if role_lower.endswith(suf):
                        group_name = full_title[: len(full_title) - len(suf)].strip()
                        role = full_title[len(group_name) :].strip()
                        break
            else:
                group_type = "NetworkCommittee"
                group_name = full_title

        return group_name, group_type, role

    def _build_position_dict(
        self,
        *,
        candidates_data: list[dict[str, Any]],
        rounds_data: list[dict[str, Any]],
        role: str,
        group_name: str,
        group_type: str,
        include_rounds: bool,
    ) -> dict[str, Any]:
        group_link: Optional[str] = None
        for cand in candidates_data:
            if cand.get("meta_society_link"):
                group_link = cand["meta_society_link"]
                break

        if not group_link and group_type == "Network":
            network_map = self.get_network_links_map()
            s_lower = group_name.lower()
            for net_name, net_url in network_map.items():
                if net_name in s_lower or s_lower in net_name:
                    group_link = net_url
                    break

        clean_candidates: list[dict[str, Any]] = [
            {
                k: v
                for k, v in cand.items()
                if k not in ("meta_society_link", "role")
            }
            for cand in candidates_data
        ]

        pos_dict: dict[str, Any] = {
            "title": role,
            "group": group_name,
            "group_type": group_type,
            "group_link": group_link,
            "winners": clean_candidates,
        }
        if include_rounds:
            pos_dict["voting_rounds"] = rounds_data
        return pos_dict

    def _parse_candidate_page_http(
        self,
        url: str,
        role_title: str,
        include_rounds: bool,
        include_tallies: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self.parse_candidate_page(
            url,
            role_title,
            include_rounds=include_rounds,
            include_tallies=include_tallies,
            soup_fetcher=self._get_soup_http,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    @override
    def scrape(
        self,
        include_rounds: bool = False,
        include_tallies: bool = False,
        officers_only: bool = False,
        key_roles_only: bool = False,
        winners_only: bool = False,
        progress_callback: Optional[Any] = None,
        page_callback: Optional[Any] = None,
        winner_callback: Optional[Any] = None,
        checkpoint_path: Optional[str] = None,
        resume: bool = False,
        max_workers: int = 1,
    ) -> dict[str, Any]:
        """
        Scrape the election position by position.

        Progress is saved to a checkpoint file after each processed position.
        If ``resume`` is True and the checkpoint matches this election +
        scrape options, processing continues from where it left off.

        Callbacks
        ---------
        progress_callback(idx, title)
            Called for every position that passes filters, with its
            1-based index and display title.
        page_callback(page_num)
            Called each time a new listing page is fetched.
        winner_callback(position_title, group_name, winner_names)
            Called immediately after a position is scraped when
            winners_only is True and at least one winner was found.
            winner_names is a list[str] of winning candidate names.
        """
        positions: list[dict[str, Any]] = []
        idx = 0
        max_workers = max(1, int(max_workers))

        checkpoint_file = Path(checkpoint_path or self.default_checkpoint_path())
        checkpoint_options = {
            "include_rounds": include_rounds,
            "include_tallies": include_tallies,
            "officers_only": officers_only,
            "key_roles_only": key_roles_only,
            "winners_only": winners_only,
        }

        if resume:
            loaded_from = checkpoint_file
            payload = self._load_checkpoint(checkpoint_file, checkpoint_options)
            if not payload:
                completed_file = self._completed_checkpoint_path(checkpoint_file)
                payload = self._load_checkpoint(completed_file, checkpoint_options)
                if payload:
                    loaded_from = completed_file

            if payload:
                stored_positions = payload.get("positions", [])
                if isinstance(stored_positions, list):
                    positions = [p for p in stored_positions if isinstance(p, dict)]
                stored_links = payload.get("processed_links", [])
                if isinstance(stored_links, list):
                    self.processed_links = {str(link) for link in stored_links}
                idx = len(positions)
                print(
                    f"Resuming from {loaded_from} "
                    f"({idx} position(s) already saved)."
                )
                if bool(payload.get("completed")):
                    print("Checkpoint already complete.")
                    return {
                        "election": {"name": "Scraped Election", "url": self.base_url},
                        "positions": positions,
                    }
            elif checkpoint_file.exists():
                print(
                    "Checkpoint exists but does not match this scrape config; "
                    "starting fresh."
                )
        else:
            self.processed_links = set()

        def write_progress(*, completed: bool = False) -> None:
            try:
                self._write_checkpoint(
                    checkpoint_file,
                    options=checkpoint_options,
                    positions=positions,
                    completed=completed,
                )
            except OSError as exc:
                print(f"Warning: failed to write checkpoint {checkpoint_file}: {exc}")

        jobs: list[_PendingPosition] = []
        for full_title, result_link in self._iter_result_links(
            page_callback=page_callback
        ):
            if result_link in self.processed_links:
                continue

            group_name, group_type, role = self._classify_position(full_title)
            probe: dict[str, Any] = {
                "title": role,
                "group": group_name,
                "group_type": group_type,
                "group_link": None,
                "winners": [],
            }
            if (
                filter_position(
                    probe,
                    officers_only=officers_only,
                    key_roles_only=key_roles_only,
                    winners_only=False,  # need candidate page to know winners
                )
                is None
            ):
                self.processed_links.add(result_link)
                write_progress()
                continue

            jobs.append(
                _PendingPosition(
                    full_title=full_title,
                    result_link=result_link,
                    group_name=group_name,
                    group_type=group_type,
                    role=role,
                )
            )

        if max_workers > 1 and len(jobs) > 1:
            print(f"Using {max_workers} worker threads for result pages...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                parsed_iter = executor.map(
                    self._parse_candidate_page_http,
                    [j.result_link for j in jobs],
                    [j.role for j in jobs],
                    [include_rounds] * len(jobs),
                    [include_tallies] * len(jobs),
                )

                for pending, parsed in zip(jobs, parsed_iter):
                    candidates_data, rounds_data = parsed
                    if not candidates_data:
                        # Fallback to browser fetch for pages blocked in plain HTTP.
                        candidates_data, rounds_data = self.parse_candidate_page(
                            pending.result_link,
                            pending.role,
                            include_rounds=include_rounds,
                            include_tallies=include_tallies,
                        )

                    pos_dict = self._build_position_dict(
                        candidates_data=candidates_data,
                        rounds_data=rounds_data,
                        role=pending.role,
                        group_name=pending.group_name,
                        group_type=pending.group_type,
                        include_rounds=include_rounds,
                    )
                    filtered = filter_position(
                        pos_dict,
                        winners_only=winners_only,
                    )
                    self.processed_links.add(pending.result_link)

                    if filtered is None:
                        write_progress()
                        continue

                    idx += 1
                    if progress_callback is not None:
                        progress_callback(idx, pending.full_title)

                    if winners_only and winner_callback is not None:
                        winner_names = [
                            c["name"]
                            for c in filtered.get("winners", [])
                            if c.get("is_winner")
                        ]
                        if winner_names:
                            winner_callback(pending.role, pending.group_name, winner_names)

                    positions.append(filtered)
                    write_progress()
        else:
            for pending in jobs:
                candidates_data, rounds_data = self.parse_candidate_page(
                    pending.result_link,
                    pending.role,
                    include_rounds=include_rounds,
                    include_tallies=include_tallies,
                )
                pos_dict = self._build_position_dict(
                    candidates_data=candidates_data,
                    rounds_data=rounds_data,
                    role=pending.role,
                    group_name=pending.group_name,
                    group_type=pending.group_type,
                    include_rounds=include_rounds,
                )
                filtered = filter_position(
                    pos_dict,
                    winners_only=winners_only,
                )
                self.processed_links.add(pending.result_link)
                if filtered is None:
                    write_progress()
                    continue

                idx += 1
                if progress_callback is not None:
                    progress_callback(idx, pending.full_title)

                if winners_only and winner_callback is not None:
                    winner_names = [
                        c["name"] for c in filtered.get("winners", []) if c.get("is_winner")
                    ]
                    if winner_names:
                        winner_callback(pending.role, pending.group_name, winner_names)

                positions.append(filtered)
                write_progress()

        write_progress(completed=True)
        final_checkpoint = self._mark_checkpoint_complete(checkpoint_file)
        if final_checkpoint != checkpoint_file:
            print(f"Checkpoint renamed to {final_checkpoint}.")

        print("Scrape complete.")
        return {
            "election": {"name": "Scraped Election", "url": self.base_url},
            "positions": positions,
        }
