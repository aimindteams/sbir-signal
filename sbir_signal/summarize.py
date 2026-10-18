"""One-line plain-English summaries from the Gemini API (free tier), with a safe fallback.

If there is no API key, the call fails, or a summary mentions a number that is not in the source
material, the deterministic summary from normalize.py is kept. The newsletter never depends on the AI.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from . import config
from .normalize import Opportunity
from .text import clean_text

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You write the weekly SBIR Signal newsletter for small technology companies that apply for
SBIR and STTR funding. For each opportunity below, write ONE plain-English sentence (at most 30 words)
that says what the agency wants to fund and who can apply. Then write a two-sentence intro for the issue.

Rules:
- Use only facts in the input. Never add dates, dollar amounts, page counts or requirements that are not there.
- No hype, no exclamation marks, no em dashes or en dashes.
- Do not repeat the agency name or the deadline in the sentence; they are shown next to it.
- The intro may use these counts exactly: {counts}.

Return JSON only, in this shape:
{{"intro": "...", "summaries": {{"<id>": "...", "...": "..."}}}}

Opportunities:
{items}
"""

NUMBER_RE = re.compile(r"\d[\d,.]*")


def _compact(opp: Opportunity) -> dict:
    return {
        "id": opp.id,
        "title": opp.title,
        "agency": opp.agency,
        "status": opp.kind_label,
        "program": opp.program,
        "phase": opp.phase,
        "funding": opp.funding,
        "facts": opp.facts,
        "description": opp.description[:900],
    }


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,").replace(",", "") for n in NUMBER_RE.findall(text or "")}


def _grounded(summary: str, opp: Opportunity) -> bool:
    """Every number in the summary must appear somewhere in the source material."""
    source = " ".join([opp.title, opp.description, " ".join(opp.facts), " ".join(opp.funding), opp.phase or ""])
    return _numbers(summary) <= _numbers(source)


def _call_gemini(prompt: str) -> dict:
    url = GEMINI_URL.format(model=config.GEMINI_MODEL)
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = httpx.post(url, json=body, headers={"x-goog-api-key": config.GEMINI_API_KEY}, timeout=90)
            if response.status_code in (429, 500, 503):
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Gemini call failed: {last_error}")


def summarize(opportunities: list[Opportunity], counts: str) -> str | None:
    """Fill opp.summary in place where Gemini gives a grounded answer. Returns the intro, if any."""
    if not config.GEMINI_API_KEY or not opportunities:
        log.info("No Gemini key or nothing to summarize; keeping the built-in summaries.")
        return None
    prompt = PROMPT.format(counts=counts, items=json.dumps([_compact(o) for o in opportunities], indent=1))
    try:
        result = _call_gemini(prompt)
    except RuntimeError as exc:
        log.warning("%s; keeping the built-in summaries.", exc)
        return None

    summaries = result.get("summaries") if isinstance(result, dict) else None
    if isinstance(summaries, dict):
        by_id = {o.id: o for o in opportunities}
        for opp_id, text in summaries.items():
            opp = by_id.get(opp_id)
            if not opp or not isinstance(text, str):
                continue
            text = clean_text(text)
            if 20 <= len(text) <= 320 and _grounded(text, opp):
                opp.summary = text
            else:
                log.info("Kept the built-in summary for %s (AI text failed the checks).", opp_id)

    intro = result.get("intro") if isinstance(result, dict) else None
    if isinstance(intro, str):
        intro = clean_text(intro)
        allowed = _numbers(counts)
        if 20 <= len(intro) <= 500 and _numbers(intro) <= allowed:
            return intro
    return None
