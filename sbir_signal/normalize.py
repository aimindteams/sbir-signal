"""Turn raw Actor dataset items into clean Opportunity records for the newsletter."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from .config import TIMEZONE
from .text import clean_text, first_useful_sentence, who_can_apply

SOURCE_LABELS = {"sam.gov": "SAM.gov", "grants.gov": "Grants.gov", "sbir.gov": "SBIR.gov"}

# SAM.gov writes agency names in capitals; these read better in an email.
AGENCY_NAMES = {
    "DEPT OF DEFENSE": "Department of Defense",
    "DEPT OF THE ARMY": "Army",
    "DEPT OF THE NAVY": "Navy",
    "DEPT OF THE AIR FORCE": "Air Force",
    "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY (DARPA)": "DARPA",
    "MISSILE DEFENSE AGENCY (MDA)": "Missile Defense Agency",
    "NATIONAL AERONAUTICS AND SPACE ADMINISTRATION": "NASA",
    "ENERGY, DEPARTMENT OF": "Department of Energy",
    "HOMELAND SECURITY, DEPARTMENT OF": "Department of Homeland Security",
    "ENVIRONMENTAL PROTECTION AGENCY": "Environmental Protection Agency",
    "U.S. National Science Foundation": "National Science Foundation",
}

# Agencies that SAM.gov sometimes leaves blank; found in the title, description or solicitation number.
AGENCY_HINTS = [
    (re.compile(r"\bEPA\b|^68H", re.I), "Environmental Protection Agency"),
    (re.compile(r"\bNASA\b|^80[A-Z]{3}", re.I), "NASA"),
    (re.compile(r"\bDOE\b|Department of Energy", re.I), "Department of Energy"),
    (re.compile(r"\bNOAA\b", re.I), "Department of Commerce"),
    (re.compile(r"\bNIST\b", re.I), "Department of Commerce"),
    (re.compile(r"\bDHS\b|Homeland Security", re.I), "Department of Homeland Security"),
    (re.compile(r"\bDOT\b|Department of Transportation", re.I), "Department of Transportation"),
    (re.compile(r"\bUSDA\b", re.I), "Department of Agriculture"),
    (re.compile(r"\bDo[DW]\b|Department of (?:Defense|War)|\bArmy\b|\bNavy\b|Air Force|DARPA", re.I), "Department of Defense"),
]

# Groups used for the "New this week" headings.
AGENCY_GROUPS = [
    ("Defense", re.compile(r"Defense|Army|Navy|Air Force|Space Force|DARPA|Missile|War\b", re.I)),
    ("Health", re.compile(r"Health|NIH|National Institutes|CDC|FDA|Community Living", re.I)),
    ("Science and space", re.compile(r"Science Foundation|\bNASA\b|Energy|Commerce|\bNIST\b|\bNOAA\b", re.I)),
    ("Agriculture and environment", re.compile(r"Agriculture|Environmental|Interior", re.I)),
    ("Homeland security and transportation", re.compile(r"Homeland|Transportation|Education", re.I)),
]

PAGE_LIMIT_LABELS = [
    ("project narrative", "project narrative"),
    ("research strategy", "research strategy"),
    ("technical volume", "technical volume"),
    ("technical proposal", "technical proposal"),
    ("volume i", "technical volume"),
    ("commercialization", "commercialization plan"),
    ("taba", "TABA plan"),
    ("budget", "budget justification"),
    ("white paper", "white paper"),
    ("quad chart", "quad chart"),
    ("abstract", "abstract"),
    ("previous review", "response to previous review"),
    ("letter of intent", "letter of intent"),
]


@dataclass
class Opportunity:
    id: str
    source: str
    source_label: str
    title: str
    url: str
    number: str | None
    agency: str
    group: str
    kind: str          # "open", "forecast" or "notice"
    kind_label: str
    program: str | None
    phase: str | None
    posted: str | None     # ISO date
    deadline: str | None   # ISO date, America/New_York
    funding: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    description: str = ""
    summary: str = ""
    deep_parsed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Opportunity":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)

    @property
    def deadline_date(self) -> date | None:
        return date.fromisoformat(self.deadline) if self.deadline else None


def to_local_date(value: str | None) -> str | None:
    """'2026-11-09T04:59:00Z' -> '2026-11-08' (New York time); plain dates pass through."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
        return match.group(1) if match else None
    if parsed.tzinfo is None:
        return parsed.date().isoformat()
    return parsed.astimezone(TIMEZONE).date().isoformat()


def nice_agency(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip()
    if name in AGENCY_NAMES:
        return AGENCY_NAMES[name]
    if name.isupper():
        words = name.title().replace("Dept Of", "Department of").replace(" Of ", " of ").replace(" The ", " the ")
        return words
    return name


def resolve_agency(item: dict[str, Any]) -> str:
    agency = nice_agency(item.get("agency"))
    sub = nice_agency(item.get("sub_agency"))
    if not agency:
        haystack = " ".join(str(item.get(k) or "") for k in ("solicitation_number", "title", "description_text"))
        for pattern, name in AGENCY_HINTS:
            if pattern.search(haystack):
                agency = name
                break
    agency = agency or "Federal agency"
    if sub and sub != agency:
        return f"{sub} ({agency})" if len(agency) < 40 else sub
    return agency


def agency_group(agency: str) -> str:
    for name, pattern in AGENCY_GROUPS:
        if pattern.search(agency):
            return name
    return "Other agencies"


def classify(item: dict[str, Any]) -> tuple[str, str]:
    code = (item.get("notice_type_code") or "").lower()
    status = ((item.get("sbir_details") or {}).get("current_status") or "").lower()
    if code == "forecast" or status == "forecasted":
        return "forecast", "Forecast (not open yet)"
    if code in {"s", "r", "p", "i"}:
        labels = {"s": "Special notice", "r": "Sources sought", "p": "Presolicitation", "i": "Intent to bundle"}
        return "notice", labels[code]
    return "open", "Open solicitation"


def money(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"[^\d.]", "", str(value))
    if not digits:
        return None
    amount = float(digits)
    if amount >= 1_000_000:
        text = f"${amount / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    elif amount >= 1_000:
        text = f"${amount:,.0f}"
    else:
        text = f"${amount:.0f}"
    return text


def funding_lines(details: dict[str, Any]) -> list[str]:
    lines = []
    floor, ceiling = money(details.get("award_floor")), money(details.get("award_ceiling"))
    if floor and ceiling and floor != ceiling:
        lines.append(f"Awards of {floor} to {ceiling}")
    elif ceiling:
        lines.append(f"Awards up to {ceiling}")
    total = money(details.get("estimated_total_funding"))
    if total:
        lines.append(f"About {total} in total")
    return lines


def page_limit_label(context: str) -> str | None:
    tail = context.lower()[-140:]
    best, best_pos = None, -1
    for needle, label in PAGE_LIMIT_LABELS:
        pos = tail.rfind(needle)
        if pos > best_pos:
            best, best_pos = label, pos
    return best


def parsed_facts(item: dict[str, Any]) -> list[str]:
    signals = item.get("signals") or {}
    constraints = signals.get("submission_constraints") or {}
    facts: list[str] = []

    limits = []
    seen_limits = set()
    for limit in constraints.get("page_limits") or []:
        label = page_limit_label(limit.get("context") or "")
        key = (label, limit.get("pages"))
        if key in seen_limits:
            continue
        seen_limits.add(key)
        pages = f"{limit['pages']} page" + ("" if limit["pages"] == 1 else "s")
        limits.append(f"{pages} ({label})" if label else pages)
    if limits:
        facts.append("Page limits: " + ", ".join(limits[:4]))

    formatting = [f.split(":", 1)[-1].strip() for f in constraints.get("formatting_requirements") or []]
    if formatting:
        facts.append("Format: " + ", ".join(formatting))

    delivery = constraints.get("delivery_methods") or []
    if delivery:
        facts.append("Submit through " + " or ".join(delivery))

    clearance = signals.get("clearance_level")
    if clearance and clearance != "Unclassified / None Stated":
        facts.append(f"Clearance: {clearance}")
    evaluation = signals.get("evaluation_type")
    if evaluation and evaluation != "Unspecified":
        facts.append(f"Evaluation: {evaluation}")
    frameworks = signals.get("security_and_compliance_frameworks") or []
    if frameworks:
        facts.append("Compliance: " + ", ".join(frameworks[:5]))

    parsed = [a for a in item.get("attachments") or [] if a.get("status") == "parsed"]
    if parsed:
        pages = sum(a.get("page_count") or 0 for a in parsed)
        noun = "document" if len(parsed) == 1 else "documents"
        facts.append(f"Read {len(parsed)} attached {noun}" + (f" ({pages} pages)" if pages else ""))
    return facts


def normalize_item(item: dict[str, Any]) -> Opportunity:
    source = item.get("source") or "unknown"
    details = item.get("sbir_details") or {}
    kind, kind_label = classify(item)
    agency = resolve_agency(item)
    description = clean_text(item.get("description_text") or "")
    facts = parsed_facts(item)
    eligibility = who_can_apply(description)
    if eligibility:
        facts.insert(0, f"Who can apply: {eligibility}")
    links = [
        {"title": clean_text(link.get("title") or "Link"), "url": link["url"]}
        for link in item.get("external_links") or []
        if link.get("url")
    ][:3]
    return Opportunity(
        id=f"{source}:{item.get('notice_id')}",
        source=source,
        source_label=SOURCE_LABELS.get(source, source),
        title=clean_text(re.sub(r"^[A-Z0-9]{1,2}--", "", item.get("title") or "Untitled")),
        url=item.get("url") or "",
        number=item.get("solicitation_number"),
        agency=agency,
        group=agency_group(agency),
        kind=kind,
        kind_label=kind_label,
        program=details.get("program"),
        phase=details.get("phase"),
        posted=to_local_date(item.get("posted_date")),
        deadline=to_local_date(item.get("response_deadline") or details.get("close_date")),
        funding=funding_lines(details),
        facts=facts,
        links=links,
        description=description[:1500],
        summary=first_useful_sentence(description, 200 if kind == "forecast" else 240),
        deep_parsed=bool(item.get("deep_parsed")),
    )


def normalize(items: list[dict[str, Any]], today: date) -> list[Opportunity]:
    """Normalize, drop anything already closed, and de-duplicate by id."""
    result: dict[str, Opportunity] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("notice_id"):
            continue
        opp = normalize_item(item)
        if opp.deadline_date and opp.deadline_date < today:
            continue
        result.setdefault(opp.id, opp)
    return list(result.values())
