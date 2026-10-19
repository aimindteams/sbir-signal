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
FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]


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


def _models() -> list[str]:
    """The configured model first, then current free-tier models in case one is retired."""
    return list(dict.fromkeys([config.GEMINI_MODEL, *FALLBACK_MODELS]))


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("message", "")[:200]
    except ValueError:
        return response.text[:200]


def _call_gemini(prompt: str) -> tuple[dict, str]:
    """Returns (parsed JSON, model used). Raises RuntimeError with a readable reason."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    reasons = []
    for model in _models():
        for attempt in range(3):
            try:
                response = httpx.post(
                    GEMINI_URL.format(model=model), json=body,
                    headers={"x-goog-api-key": config.GEMINI_API_KEY}, timeout=120,
                )
            except httpx.HTTPError as exc:
                reasons.append(f"{model}: network error {exc.__class__.__name__}")
                time.sleep(5 * (attempt + 1))
                continue
            if response.status_code == 404:
                reasons.append(f"{model}: model not available")
                break  # try the next model
            if response.status_code in (400, 401, 403):
                raise RuntimeError(f"Gemini rejected the key or request ({response.status_code}): {_error_message(response)}")
            if response.status_code in (429, 500, 502, 503, 504):
                reasons.append(f"{model}: HTTP {response.status_code}")
                time.sleep(10 * (attempt + 1))
                continue
            try:
                text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                return _parse(text), model
            except (ValueError, KeyError, IndexError) as exc:
                reasons.append(f"{model}: unreadable answer ({exc.__class__.__name__})")
                continue
    raise RuntimeError("Gemini call failed: " + "; ".join(reasons[-4:]))


def summarize(opportunities: list[Opportunity], counts: str) -> tuple[str | None, str]:
    """Fill opp.summary in place where Gemini gives a grounded answer.

    Returns (intro or None, a one-line status for the review issue).
    """
    if not opportunities:
        return None, "AI summaries: nothing new to summarize."
    if not config.GEMINI_API_KEY:
        log.info("No Gemini key; keeping the built-in summaries.")
        return None, "AI summaries: off (no GEMINI_API_KEY secret), so the built-in summaries were used."
    prompt = PROMPT.format(counts=counts, items=json.dumps([_compact(o) for o in opportunities], indent=1))
    try:
        result, model = _call_gemini(prompt)
    except RuntimeError as exc:
        log.warning("%s; keeping the built-in summaries.", exc)
        return None, f"AI summaries: failed, so the built-in summaries were used. {exc}"

    used = 0
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
                used += 1
            else:
                log.info("Kept the built-in summary for %s (AI text failed the checks).", opp_id)
    status = f"AI summaries: on ({model}); {used} of {len(opportunities)} passed the fact checks."

    intro = result.get("intro") if isinstance(result, dict) else None
    if isinstance(intro, str):
        intro = clean_text(intro)
        if 20 <= len(intro) <= 500 and _numbers(intro) <= _numbers(counts):
            return intro, status
    return None, status
