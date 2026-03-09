#!/usr/bin/env python3
"""
enrich.py

Reads a combined results JSON produced by combine.py and uses Groq's
OpenAI-compatible Responses API (via the OpenAI-compatible Python client)
to extract a clean bullet-point list of campaign promises for every winning
candidate whose `campaign_points` field is null, then writes the enriched
data back to the same file (or a new file when `--out` is provided).

This script implements batching to reduce HTTP calls (fewer 429s) and
incremental writes so progress is persisted as the script runs.

Usage:
    python3 categorise/enrich.py results_combined.json
    python3 categorise/enrich.py results_combined.json --out enriched.json --batch-size 8
    python3 categorise/enrich.py results_combined.json --dry-run --debug

Environment:
    - GROQ_API_KEY : your Groq API key (can be in .env at repo root or exported into the shell)
    - Optionally put GROQ_API_KEY in /path/to/suu-scrape/.env and install python-dotenv

Requirements:
    pip install openai
    (optional) pip install python-dotenv
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional .env loading (repo root)
# ---------------------------------------------------------------------------
_repo_root = Path(__file__).resolve().parents[1]  # /.../suu-scrape
_dotenv_path = _repo_root / ".env"
try:
    from dotenv import load_dotenv  # type: ignore

    if _dotenv_path.exists():
        try:
            load_dotenv(dotenv_path=str(_dotenv_path))
        except Exception:
            # ignore dotenv errors
            pass
except Exception:
    # very small fallback parser for KEY=VALUE lines
    if _dotenv_path.exists():
        try:
            with _dotenv_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Try to import the OpenAI-compatible client (used for Groq)
# ---------------------------------------------------------------------------
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore

# ---------------------------------------------------------------------------
# Configuration (tunable)
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "llama-3.1-8b-instant"

# Prompt pieces
SYSTEM_PROMPT = (
    "You are a precise assistant that extracts campaign promises from student "
    "election manifestos.\n\n"
    "Given the full election statement for a winning candidate, return ONLY a "
    "JSON array of strings — each string is one distinct, concrete campaign "
    "promise. Follow these rules strictly:\n\n"
    "1. SPECIFIC AND ACTIONABLE: Each point must describe something the "
    "candidate can actually do in the role — a tangible action, initiative, or "
    "change. Exclude vague aspirations like 'make things better' or broad "
    "values statements.\n"
    "2. PRESENT CONTINUOUS TENSE: Phrase every point using a gerund (–ing form) "
    "as the first word. Examples: 'Introducing a student discount scheme', "
    "'Lobbying management to extend library hours', "
    "'Running monthly feedback sessions with staff'.\n"
    "3. CONCISE: Each point should be one short clause (under 15 words).\n"
    "4. Aim for 3–6 points. Omit background, personal qualities, and reasons "
    "to vote for the candidate.\n\n"
    "Respond with valid JSON only — no markdown fences, no explanation."
)

USER_TEMPLATE = "Role: {role}\nCandidate: {name}\n\nElection statement:\n{statement}\n"

# Backoff/retry configuration
CALL_MAX_RETRIES = 5
CALL_INITIAL_BACKOFF = 1.0
CALL_BACKOFF_MULT = 2.0
CALL_BACKOFF_JITTER = 0.3
TRANSIENT_PHRASES = (
    "429",
    "too many requests",
    "rate limit",
    "rate_limited",
    "timeout",
    "temporarily unavailable",
    "502",
    "503",
    "504",
)


# ---------------------------------------------------------------------------
# Response parsing helper
# ---------------------------------------------------------------------------
def _response_to_text(resp: Any) -> str:
    """
    Try common shapes for SDK responses and return a string.
    """
    try:
        raw = getattr(resp, "output_text", None)
        if raw:
            return str(raw).strip()
    except Exception:
        pass

    try:
        out = getattr(resp, "output", None)
        if out:
            try:
                return str(out[0].content[0].text).strip()  # type: ignore
            except Exception:
                pass
            try:
                return str(out[0]["content"][0]["text"]).strip()  # type: ignore
            except Exception:
                pass
    except Exception:
        pass

    try:
        choices = getattr(resp, "choices", None)
        if choices:
            try:
                return str(choices[0].message.content).strip()  # type: ignore
            except Exception:
                pass
            try:
                return str(choices[0]["message"]["content"]).strip()  # type: ignore
            except Exception:
                pass
    except Exception:
        pass

    try:
        return str(resp).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Transient / Retry helpers
# ---------------------------------------------------------------------------
def _is_transient_error(exc: BaseException) -> bool:
    txt = str(exc).lower()
    return any(p in txt for p in TRANSIENT_PHRASES)


def _extract_retry_after_seconds(exc: BaseException) -> Optional[float]:
    # Try to extract Retry-After int from exception text or attributes
    txt = str(exc)
    m = re.search(r"retry-after[:= ]+(\d+)", txt, re.I)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    # common header extraction from nested response-like objects
    for attr in ("response", "resp", "http_response"):
        nested = getattr(exc, attr, None)
        if nested is None:
            continue
        headers = getattr(nested, "headers", None)
        if headers and isinstance(headers, dict):
            ra = headers.get("Retry-After") or headers.get("retry-after")
            if ra:
                try:
                    return float(ra)
                except Exception:
                    pass
    return None


# ---------------------------------------------------------------------------
# Low-level call wrapper: attempt multiple shapes and handle transient errors
# ---------------------------------------------------------------------------
def _call_responses_with_retries(client: Any, kwargs_list: List[dict]) -> Optional[Any]:
    """
    Try a series of kwargs shapes in order. For each shape, retry on transient errors
    with exponential backoff. Returns the first successful response object or None.
    """
    last_exc: Optional[BaseException] = None
    for shape_no, kwargs in enumerate(kwargs_list, start=1):
        attempt = 0
        backoff = CALL_INITIAL_BACKOFF
        while attempt <= CALL_MAX_RETRIES:
            attempt += 1
            try:
                logging.debug(
                    "LLM call shape %d attempt %d kwargs=%s", shape_no, attempt, kwargs
                )
                resp = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
                logging.debug(
                    "LLM call succeeded (shape %d attempt %d)", shape_no, attempt
                )
                return resp
            except TypeError as te:
                # signature mismatch -> try the next shape
                last_exc = te
                logging.info("Groq SDK rejected kwargs for shape %d: %s", shape_no, te)
                break
            except Exception as exc:
                last_exc = exc
                if _is_transient_error(exc) and attempt <= CALL_MAX_RETRIES:
                    retry_after = _extract_retry_after_seconds(exc)
                    jitter = backoff * CALL_BACKOFF_JITTER
                    if retry_after:
                        wait = retry_after + random.uniform(0, jitter)
                    else:
                        wait = max(0.1, backoff + random.uniform(-jitter, jitter))
                    logging.info(
                        "Transient error (%s). Retrying in %.2f s (attempt %d/%d)",
                        exc,
                        wait,
                        attempt,
                        CALL_MAX_RETRIES,
                    )
                    time.sleep(wait)
                    backoff *= CALL_BACKOFF_MULT
                    continue
                else:
                    logging.error("Non-transient error for shape %d: %s", shape_no, exc)
                    break
    logging.error("All call shapes failed; last error: %s", last_exc)
    return None


# ---------------------------------------------------------------------------
# Single-item extraction (uses the low-level wrapper)
# ---------------------------------------------------------------------------
def _extract_via_llm_single(
    client: Any, model: str, role: str, name: str, statement: str
) -> Optional[List[str]]:
    if client is None:
        logging.error("LLM client not initialised for single extraction")
        return None

    user_content = USER_TEMPLATE.format(role=role, name=name, statement=statement)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    kwargs_list = [
        {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 512},
        {"model": model, "messages": messages, "temperature": 0.2},
        {"model": model, "messages": messages},
    ]

    resp = _call_responses_with_retries(client, kwargs_list)
    if resp is None:
        return None

    raw = _response_to_text(resp)
    if not raw:
        logging.warning("Empty response text for %s (%s)", name, role)
        return None

    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(
            "Could not parse single-item LLM output as JSON for %s. First 200 chars: %s",
            name,
            raw[:200],
        )
        return None

    if not isinstance(parsed, list):
        logging.warning(
            "Expected list for single-item extraction for %s; got %s",
            name,
            type(parsed).__name__,
        )
        return None

    return [str(item).strip() for item in parsed if str(item).strip()]


# ---------------------------------------------------------------------------
# Batch extraction: send multiple candidates in one request and parse mapping
# ---------------------------------------------------------------------------
def _batch_extract_via_llm(
    client: Any, model: str, items: List[Dict[str, str]]
) -> Optional[Dict[str, List[str]]]:
    """
    items: list of dicts with keys: 'id', 'name', 'role', 'statement'
    Returns mapping id -> list[str] or None on failure.
    """
    if client is None:
        logging.error("LLM client not initialised for batch extraction")
        return None

    # Build batch instruction: reuse SYSTEM_PROMPT but require a JSON object mapping id -> array
    batch_instruction = (
        SYSTEM_PROMPT
        + "\n\n"
        + "Now process the items below and return a SINGLE valid JSON object mapping each"
        + " item id to an array of campaign-point strings. Example:\n"
        + '{"item-1": ["point a", "point b"], "item-2": ["point x"]}\n\n'
        + "Respond with JSON only — no markdown fences or extra text."
    )

    parts = []
    for it in items:
        iid = str(it["id"])
        parts.append(
            f"ID: {iid}\nRole: {it.get('role', '')}\nCandidate: {it.get('name', '')}\nElection statement:\n{it.get('statement', '')}\n---\n"
        )

    batch_user_content = "\n".join(parts)
    messages = [
        {"role": "system", "content": batch_instruction},
        {"role": "user", "content": batch_user_content},
    ]

    kwargs_list = [
        {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 2048},
        {"model": model, "messages": messages, "temperature": 0.2},
        {"model": model, "messages": messages},
    ]

    resp = _call_responses_with_retries(client, kwargs_list)
    if resp is None:
        return None

    raw = _response_to_text(resp)
    if not raw:
        logging.warning(
            "Batch response empty; raw: %s", getattr(resp, "__dict__", str(resp))
        )
        return None

    # strip fences
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("```")
        ).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(
            "Could not parse batch output as JSON. First 300 chars: %s", raw[:300]
        )
        return None

    if not isinstance(parsed, dict):
        logging.warning(
            "Batch JSON must be an object mapping id->array; got %s",
            type(parsed).__name__,
        )
        return None

    result: Dict[str, List[str]] = {}
    for k, v in parsed.items():
        if isinstance(v, list):
            result[str(k)] = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str):
            # split lines as fallback
            result[str(k)] = [s.strip() for s in v.splitlines() if s.strip()]
        else:
            result[str(k)] = []

    return result


# ---------------------------------------------------------------------------
# Enrichment loop (batching + incremental writes)
# ---------------------------------------------------------------------------
def enrich(
    data: dict,
    client: Optional[Any],
    model: str,
    dry_run: bool,
    retry_existing: bool,
    out_path: Optional[Path],
    batch_size: int = 8,
) -> Tuple[dict, int, int]:
    """
    Walk positions and winners, fill campaign_points for winners.
    Persist incremental progress to out_path (atomic replace) after each batch.
    Returns (data, filled_count, skipped_count).
    """
    filled = 0
    skipped = 0

    # Lazy client init if needed
    if client is None and not dry_run:
        groq_key = os.environ.get("GROQ_API_KEY")
        if not groq_key:
            logging.error(
                "GROQ_API_KEY not set; set it in env or place in .env at repo root"
            )
            sys.exit(1)
        if OpenAI is None:
            logging.error(
                "OpenAI-compatible client not available. Please pip install openai"
            )
            sys.exit(1)
        client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")

    # Build flat list of (pos, cand) tuples we should process to make batching straightforward
    tasks: List[Tuple[dict, dict]] = []
    for pos in data.get("positions", []):
        for cand in pos.get("winners", []):
            if not cand.get("is_winner"):
                continue
            existing = cand.get("campaign_points")
            if existing is not None and not retry_existing:
                skipped += 1
                continue
            tasks.append((pos, cand))

    total = len(tasks)
    logging.info("Will process %d candidate(s) (skipped %d)", total, skipped)

    # Process in batches
    idx = 0
    uid_counter = 0
    while idx < total:
        batch_tasks = tasks[idx : idx + batch_size]
        batch_items = []
        id_map: Dict[str, Tuple[dict, dict]] = {}
        for pos, cand in batch_tasks:
            uid_counter += 1
            item_id = f"item-{uid_counter}"
            id_map[item_id] = (pos, cand)
            batch_items.append(
                {
                    "id": item_id,
                    "name": cand.get("name", "Unknown"),
                    "role": pos.get("title", "Unknown role"),
                    "statement": cand.get("election_statement", "") or "",
                }
            )

        logging.info(
            "Processing batch %d - items %d..%d",
            (idx // batch_size) + 1,
            idx + 1,
            min(idx + batch_size, total),
        )

        if dry_run:
            logging.info("Dry-run: would call batch LLM for %d items", len(batch_items))
            filled += len(batch_items)
            # set empty arrays to show they'd be processed in dry-run
            for it in batch_items:
                pos, cand = id_map[it["id"]]
                cand["campaign_points"] = []
            # persist progress
            if out_path and not dry_run:
                pass
            idx += batch_size
            continue

        # Attempt batch call
        mapping = _batch_extract_via_llm(client, model, batch_items)
        if mapping is None:
            logging.warning(
                "Batch failed; falling back to single-item calls for this batch"
            )
            # Try single-item extraction for each item
            for it in batch_items:
                pos, cand = id_map[it["id"]]
                name = it["name"]
                role = it["role"]
                statement = it["statement"]
                logging.info("Single-call fallback for %s | %s", name, role)
                points = _extract_via_llm_single(client, model, role, name, statement)
                if points is None:
                    logging.warning(
                        "Failed to extract points for %s; leaving as null", name
                    )
                    # leave as null to indicate failure
                else:
                    cand["campaign_points"] = points
                    filled += 1
                # persist after each single item to minimise loss
                if out_path:
                    try:
                        tmp_path = out_path.with_suffix(".tmp")
                        tmp_path.write_text(
                            json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        os.replace(str(tmp_path), str(out_path))
                        logging.debug("Wrote progress to %s", out_path)
                    except Exception as e:
                        logging.warning("Failed to write progress: %s", e)
                # small pause per item
                time.sleep(0.2)
        else:
            # Apply mapping to candidates
            for iid, (pos, cand) in id_map.items():
                pts = mapping.get(iid)
                if pts is None:
                    # If a single item missing, fall back to individual call for that item
                    logging.warning(
                        "Batch response missing id %s; falling back to single call", iid
                    )
                    points = _extract_via_llm_single(
                        client,
                        model,
                        pos.get("title", ""),
                        cand.get("name", ""),
                        cand.get("election_statement", "") or "",
                    )
                    if points is None:
                        logging.warning(
                            "Failed to extract %s after fallback; leaving null",
                            cand.get("name", "Unknown"),
                        )
                    else:
                        cand["campaign_points"] = points
                        filled += 1
                        time.sleep(0.2)
                else:
                    cand["campaign_points"] = pts
                    filled += 1
            # Persist batch result atomically
            if out_path:
                try:
                    tmp_path = out_path.with_suffix(".tmp")
                    tmp_path.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    os.replace(str(tmp_path), str(out_path))
                    logging.debug("Wrote batch progress to %s", out_path)
                except Exception as e:
                    logging.warning("Failed to write batch progress: %s", e)

        # Respectful pause between batches
        time.sleep(0.5)
        idx += batch_size

    logging.info("Enrichment complete: %d filled, %d skipped", filled, skipped)
    return data, filled, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill campaign_points for winners using Groq's Responses API with batching."
    )
    parser.add_argument(
        "input",
        metavar="INPUT_JSON",
        help="Combined results JSON produced by combine.py",
    )
    parser.add_argument(
        "--out",
        default=None,
        metavar="OUTPUT_JSON",
        help="Output path (default: overwrite input)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="MODEL",
        help=f"Model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        metavar="N",
        help="Number of candidates to batch per request (default: 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call the API; just show who would be processed",
    )
    parser.add_argument(
        "--retry-existing",
        action="store_true",
        help="Re-generate campaign_points even if present",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug or os.environ.get("DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    input_path = Path(args.input)
    if not input_path.exists():
        logging.error("Input file not found: %s", input_path)
        sys.exit(1)

    out_path = Path(args.out) if args.out else input_path

    logging.info("Loading %s", input_path.name)
    with input_path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except Exception as exc:
            logging.error("Failed to parse input JSON: %s", exc)
            sys.exit(1)

    logging.info("Model: %s, batch-size: %d", args.model, args.batch_size)
    client = None  # let enrich() create Groq client when needed

    enriched_data, filled, skipped = enrich(
        data,
        client=client,
        model=args.model,
        dry_run=args.dry_run,
        retry_existing=args.retry_existing,
        out_path=out_path,
        batch_size=args.batch_size,
    )

    if not args.dry_run:
        try:
            out_path.write_text(
                json.dumps(enriched_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logging.info("Saved → %s", out_path)
        except Exception as exc:
            logging.error("Failed to write final output: %s", exc)
            sys.exit(1)

    logging.info("Done — %d filled, %d skipped.", filled, skipped)


if __name__ == "__main__":
    main()
