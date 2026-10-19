"""Small text helpers shared by the pipeline."""

from __future__ import annotations

import html
import re

# Generic sentences that every SBIR announcement repeats. They say nothing about the opportunity.
BOILERPLATE = re.compile(
    r"purpose of the federal sbir program|stimulate technological innovation|strengthen(?:ing)? the role of small business"
    r"|program helps (?:united states )?small business|invests in scientific discoveries|our ability to support that mission"
    r"|assistance listing|eligibility:|this sam notice is to highlight|click here"
    r"|\b(?:sbir|sttr) topic [a-z0-9-]+ \((?:open|pre-release)",
    re.I,
)
EM_DASH, EN_DASH, NBSP, ELLIPSIS = chr(0x2014), chr(0x2013), chr(0xA0), chr(0x2026)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def clean_text(value: str) -> str:
    """Unescape, collapse whitespace and keep the house style (no em or en dashes)."""
    text = html.unescape(value or "")
    text = text.replace(EM_DASH, ", ").replace(EN_DASH, "-").replace(NBSP, " ")
    text = re.sub(r"\s*,\s*,", ",", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


ABBREVIATION_END = re.compile(r"(?:\b[A-Z]|\bU\.S|\bInc|\bCorp|\bCo|\bLtd|\bNo|\bDr|\bSt|\bvs|\be\.g|\bi\.e|\bJr|\bSr)\.$")


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text or "").strip()
    merged: list[str] = []
    for piece in (s.strip() for s in SENTENCE_END.split(flat)):
        if not piece:
            continue
        if merged and ABBREVIATION_END.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {piece}"  # "U.S. Army" is not a sentence break
        else:
            merged.append(piece)
    return merged


SECTION_RE = re.compile(
    # A heading at the start of a line, followed by a colon or the end of that line.
    r"\n\s*(Eligibility|Assistance listings?|Purpose|Description|Objective|Phase III dual-use applications|Phase I{1,3})"
    r"(?=[ \t]*:|[ \t]*\n)[ \t]*:?\s*",
    re.I,
)
INTENT_RE = re.compile(
    r"\b(intends? to|will (?:make|fund|support|award)|seeks?|seeking|requests proposals|invites?|solicits?|supports?|encourages|is conducting"
    r"|to (?:fund|develop|evaluate|acquire)|aims? to|helps?|purpose of [\w'\u2019 ]+ is to|bridges)\b",
    re.I,
)
GENERIC_ELIGIBILITY = re.compile(
    r"only united states small business concerns|must qualify at the time of the award as a small business"
    r"|as defined by the small business administration",
    re.I,
)


def split_sections(text: str) -> tuple[str, dict[str, str]]:
    """'Main text\\n\\nEligibility: ...' -> ('Main text', {'eligibility': '...'})."""
    parts = SECTION_RE.split(text or "")
    main, sections = parts[0], {}
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i].lower().split()[0]] = parts[i + 1].strip()
    if any(k in sections for k in ("objective", "purpose", "description")):
        main = " ".join([main, sections.get("objective", ""), sections.get("purpose", ""), sections.get("description", "")])
    return main, sections


def trim(sentence: str, limit: int) -> str:
    if len(sentence) <= limit:
        return sentence
    cut = sentence[: limit - 1]
    pos = cut.rfind("; ")
    if pos > limit * 0.55:
        return cut[:pos].rstrip(",;: ") + "."
    return cut.rsplit(" ", 1)[0].rstrip(",;:(") + ELLIPSIS


def first_useful_sentence(text: str, limit: int = 240) -> str:
    """The most specific early sentence about this opportunity, trimmed for an email."""
    main, _ = split_sections(text)
    pool = [s for s in sentences(main) if len(s) > 40 and "http" not in s and " | " not in s]
    scored = []
    for index, sentence in enumerate(pool[:8]):
        score = 2 if INTENT_RE.search(sentence) else 0
        score -= 3 if BOILERPLATE.search(sentence) else 0
        score -= 1 if re.match(r"The purpose", sentence) else 0
        scored.append((-score, index, sentence))
    if scored:
        best = min(scored)
        chosen = best[2]
        if best[0] > 0:  # only boilerplate was available: keep it short
            limit = min(limit, 160)
    else:
        chosen = (sentences(main)[:1] or [""])[0]
    return trim(chosen, limit)


def who_can_apply(text: str, limit: int = 170) -> str | None:
    """The specific eligibility rule, if the notice has one beyond the standard small-business test."""
    _, sections = split_sections(text)
    eligibility = sections.get("eligibility")
    if not eligibility:
        return None
    for sentence in sentences(eligibility)[:3]:
        if not GENERIC_ELIGIBILITY.search(sentence) and len(sentence) > 30:
            return trim(sentence, limit)
    return None
