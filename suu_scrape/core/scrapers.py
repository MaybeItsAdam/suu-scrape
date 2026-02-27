from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional

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


def get_all_elections(page: int = 0) -> list[dict[str, str]]:
    """
    Fetch the list of active elections.
    Returns a list of dicts with 'title' and 'url'.
    """
    url = f"{BASE_URL}/election/list"
    if page > 0:
        url += f"?page={page}"

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

    def __init__(self, election_url: str) -> None:
        self.base_url = election_url
        self.network_links_map = None  # lazily populated
        self.societies_map = {}
        self.officials_list = []
        self.processed_links = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_soup(self, url: str) -> Optional[BeautifulSoup]:
        return get_soup(url)

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

    def parse_profile_for_pronouns(self, url: str) -> str:
        soup = self._get_soup(url)
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
                pronouns = self.parse_profile_for_pronouns(profile_url)

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
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        soup = self._get_soup(url)
        if not soup:
            return [], []

        winners, society_link, rounds, _ = self.parse_page_data(
            soup, role_title, include_rounds, include_tallies
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
    ) -> dict[str, Any]:
        """
        Scrape the election position by position.

        Filters are applied inline as each position is fetched, so
        progress_callback / winner_callback fire only for positions that
        pass the active filters.

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

        for full_title, result_link in self._iter_result_links(
            page_callback=page_callback
        ):
            if result_link in self.processed_links:
                continue

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
                # The lead officer for each network is a union-level role and
                # does NOT contain "Network" in the title (e.g. "Disabled
                # Students' Officer") so we can safely classify anything with
                # "Network" in the unprefixed title as a committee role.
                role_lower = full_title.lower()
                if any(role_lower.endswith(suf) for suf in _NETWORK_COMMITTEE_SUFFIXES):
                    group_type = "NetworkCommittee"
                    # Best-effort: strip the trailing role word(s) to get the
                    # network name, e.g. "POC Network Treasurer" -> "POC Network"
                    for suf in _NETWORK_COMMITTEE_SUFFIXES:
                        if role_lower.endswith(suf):
                            group_name = full_title[
                                : len(full_title) - len(suf)
                            ].strip()
                            role = full_title[len(group_name) :].strip()
                            break
                else:
                    # "Network" in title but no known committee suffix —
                    # treat conservatively as NetworkCommittee to avoid false
                    # positives in --officers-only.
                    group_type = "NetworkCommittee"
                    group_name = full_title

            # Apply position-level filters (officers_only / key_roles_only)
            # before making any HTTP requests for the individual result page.
            _probe: dict[str, Any] = {
                "title": role,
                "group": group_name,
                "group_type": group_type,
                "group_link": None,
                "winners": [],
            }
            if (
                filter_position(
                    _probe,
                    officers_only=officers_only,
                    key_roles_only=key_roles_only,
                    winners_only=False,  # can't check winners yet — need to fetch the page
                )
                is None
            ):
                continue

            candidates_data, rounds_data = self.parse_candidate_page(
                result_link,
                role,
                include_rounds=include_rounds,
                include_tallies=include_tallies,
            )

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

            # Apply winners_only filter inline now that we have candidate data.
            filtered = filter_position(
                pos_dict,
                officers_only=False,  # already applied above
                key_roles_only=False,  # already applied above
                winners_only=winners_only,
            )
            if filtered is None:
                self.processed_links.add(result_link)
                continue

            pos_dict = filtered
            idx += 1

            if progress_callback is not None:
                progress_callback(idx, full_title)

            # Fire winner_callback immediately so callers can print live output.
            if winners_only and winner_callback is not None:
                winner_names = [
                    c["name"] for c in pos_dict.get("winners", []) if c.get("is_winner")
                ]
                if winner_names:
                    winner_callback(role, group_name, winner_names)

            positions.append(pos_dict)
            self.processed_links.add(result_link)

        print("Scrape complete.")
        return {
            "election": {"name": "Scraped Election", "url": self.base_url},
            "positions": positions,
        }
