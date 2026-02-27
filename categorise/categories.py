"""
categories.py

Shared data and logic for the categorisation pipeline:
  - title normalisation
  - manual winner corrections
  - category assignment
  - canonical category order
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Title normalisation
# ---------------------------------------------------------------------------


# Trustee position titles have appeared as both "Student Trustee" (singular)
# and "Student Trustees" (plural) across elections.  Normalise to singular.
def normalise_title(title: str) -> str:
    if title.strip() == "Student Trustees":
        return "Student Trustee"
    return title


# ---------------------------------------------------------------------------
# Manual winner corrections
# ---------------------------------------------------------------------------

# Candidates who should be removed from the winners list due to known
# post-election changes.  Key is (normalised_title, candidate_name).
REMOVED_WINNERS: set[tuple[str, str]] = {
    ("Student Trustee", "Hammad Khaled"),
}


def apply_corrections(
    title: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Return a new list of candidate dicts with any manual corrections applied.
    Currently handles removing specific winners from REMOVED_WINNERS.
    Prints a message for each correction made.
    """
    result = []
    for cand in candidates:
        c = dict(cand)
        if c.get("is_winner") and (title, c.get("name", "")) in REMOVED_WINNERS:
            print(f"  [correction] Removing {c['name']} from winners ({title})")
            c["is_winner"] = False
        result.append(c)
    return result


# ---------------------------------------------------------------------------
# Category assignment
# ---------------------------------------------------------------------------

# The six paid full-time sabbatical officer roles.
_SABBS: set[str] = {
    "students' union president",
    "president",
    "activities & engagement officer",
    "education officer",
    "equity & inclusion officer",
    "postgraduate officer",
    "welfare & community officer",
}


def assign_category(title: str) -> str:
    """
    Return the category name for a given position title.
    The first matching rule wins.
    """
    t = title.lower()

    # Sabbatical Officers — the six paid full-time roles
    if t in _SABBS:
        return "Sabbatical Officers"

    # Student Trustees
    if "trustee" in t:
        return "Student Trustees"

    # Sports — officer and reps
    if "sports officer" in t or "sports rep" in t or t.startswith("sport"):
        return "Sports"

    # Arts — officer and societies rep for arts
    if "arts officer" in t or "societies rep (arts)" in t:
        return "Arts"

    # Volunteering — officer and reps
    if "volunteering officer" in t or "volunteering rep" in t:
        return "Volunteering"

    # Societies — non-portfolio, media, welfare reps for societies
    if (
        "societies rep" in t
        or "societies officer" in t
        or "welfare rep" in t
        or "student media" in t
        or "media rep" in t
    ):
        return "Societies"

    # Hall & Community
    if "hall community" in t:
        return "Hall & Community"

    # Faculty Reps — Faculty of … and Institute of …
    if t.startswith("faculty of") or t.startswith("institute of"):
        return "Faculty Reps"

    # Officers — all remaining union-level student officer roles
    # (Accommodation, Disabled Students', International, LGBTQ+, Mature,
    #  POC, Research, Social Class, Sustainability, Trans, UCL East, Women's, etc.)
    if "officer" in t:
        return "Officers"

    return "Other"


# ---------------------------------------------------------------------------
# Canonical category order (used for sorting and display)
# ---------------------------------------------------------------------------

CATEGORY_ORDER: list[str] = [
    "Sabbatical Officers",
    "Officers",
    "Student Trustees",
    "Sports",
    "Arts",
    "Volunteering",
    "Societies",
    "Hall & Community",
    "Faculty Reps",
    "Other",
]
