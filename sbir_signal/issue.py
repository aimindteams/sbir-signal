"""Decide what goes into this week's issue, using the pipeline's memory in data/state.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import config
from .normalize import Opportunity

GROUP_ORDER = [
    "Defense",
    "Science and space",
    "Health",
    "Agriculture and environment",
    "Homeland security and transportation",
    "Other agencies",
]
AGENCY_TAGS = [
    (re.compile(r"National Institutes of Health|\bNIH\b|\bCDC\b|\bFDA\b", re.I), "NIH"),
    (re.compile(r"Science Foundation", re.I), "NSF"),
    (re.compile(r"Agriculture", re.I), "USDA"),
    (re.compile(r"Environmental Protection", re.I), "EPA"),
    (re.compile(r"NASA|Aeronautics", re.I), "NASA"),
    (re.compile(r"Energy", re.I), "DOE"),
    (re.compile(r"Homeland", re.I), "DHS"),
    (re.compile(r"Defense|Army|Navy|Air Force|Space Force|DARPA|Missile|War\b", re.I), "Defense"),
    (re.compile(r"Health and Human Services|Community Living", re.I), "HHS"),
    (re.compile(r"Commerce|\bNIST\b|\bNOAA\b", re.I), "Commerce"),
    (re.compile(r"Transportation", re.I), "DOT"),
    (re.compile(r"Education", re.I), "Education"),
]
FORECAST_MAX_AGE_DAYS = 180
NOTICE_MAX_AGE_DAYS = 45


def empty_state() -> dict:
    return {"seen": {}, "open": {}, "issues": []}


def load_state(path: Path | None = None) -> dict:
    path = path or config.DATA_DIR / "state.json"
    if not path.exists():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    for key, value in empty_state().items():
        state.setdefault(key, value)
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or config.DATA_DIR / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def still_relevant(opp: Opportunity, today: date) -> bool:
    if opp.deadline_date:
        return opp.deadline_date >= today
    posted = date.fromisoformat(opp.posted) if opp.posted else None
    if opp.kind == "forecast":
        return posted is None or (today - posted).days <= FORECAST_MAX_AGE_DAYS
    if opp.kind == "notice":
        return posted is None or (today - posted).days <= NOTICE_MAX_AGE_DAYS
    return True


def _deadline_key(opp: Opportunity) -> tuple:
    return (opp.deadline is None, opp.deadline or "", opp.title)


@dataclass
class Issue:
    issue_date: date
    first_issue: bool
    intro: str
    counts: str
    closing_soon: list[Opportunity] = field(default_factory=list)
    new_groups: list[tuple[str, list[Opportunity]]] = field(default_factory=list)
    forecasts: list[Opportunity] = field(default_factory=list)
    still_open: int = 0

    @property
    def new_count(self) -> int:
        return sum(len(items) for _, items in self.new_groups)

    @property
    def title(self) -> str:
        return f"{config.NEWSLETTER_NAME}: {self.issue_date.strftime('%B')} {self.issue_date.day}, {self.issue_date.year}"

    @property
    def slug(self) -> str:
        return self.issue_date.isoformat()

    @property
    def subtitle(self) -> str:
        """One line for Substack's subtitle field."""
        label = "open" if self.first_issue else "new"
        noun = "opportunity" if self.new_count == 1 else "opportunities"
        if self.new_count:
            parts = [f"{self.new_count} {label} SBIR/STTR {noun}"]
        else:
            parts = ["No new SBIR/STTR opportunities this week"]
        if self.closing_soon:
            parts.append(f"{len(self.closing_soon)} closing within 3 weeks")
        if self.forecasts:
            parts.append(f"{len(self.forecasts)} forecast" + ("" if len(self.forecasts) == 1 else "s"))
        return ", ".join(parts)

    @property
    def tags(self) -> list[str]:
        """Substack tags: the fixed three plus one per agency in this issue."""
        tags = ["SBIR", "STTR", "Weekly issue"]
        items = self.closing_soon + [o for _, group in self.new_groups for o in group] + self.forecasts
        for opp in items:
            tag = next((t for pattern, t in AGENCY_TAGS if pattern.search(opp.agency)), None)
            if tag and tag not in tags:
                tags.append(tag)
        return tags


def plan_issue(opps: list[Opportunity], state: dict, today: date) -> tuple[Issue, list[Opportunity], dict[str, Opportunity]]:
    """Returns the issue (without intro text yet), the items that need summaries, and the new open map."""
    opps = [o for o in opps if still_relevant(o, today)]
    first_issue = not state["issues"] and not state["seen"]
    previous_map = {opp_id: Opportunity.from_dict(data) for opp_id, data in state["open"].items()}

    def is_new(opp: Opportunity) -> bool:
        if opp.id not in state["seen"]:
            return True
        before = previous_map.get(opp.id)
        return bool(before and before.kind == "forecast" and opp.kind == "open")  # a forecast that just opened

    new = [o for o in opps if is_new(o)]
    new_ids = {o.id for o in new}

    open_map = {opp_id: opp for opp_id, opp in previous_map.items() if still_relevant(opp, today)}
    for opp in opps:
        previous = open_map.get(opp.id)
        if previous and previous.summary and opp.id not in new_ids:
            opp.summary = previous.summary  # keep last week's AI summary
        open_map[opp.id] = opp

    horizon = today + timedelta(days=config.CLOSING_SOON_DAYS)
    closing = sorted(
        (o for o in open_map.values() if o.kind == "open" and o.deadline_date and today <= o.deadline_date <= horizon),
        key=_deadline_key,
    )
    new_main = [o for o in new if o.kind in ("open", "notice")][: config.MAX_NEW_ITEMS]
    forecasts = sorted((o for o in new if o.kind == "forecast"), key=lambda o: o.posted or "", reverse=True)

    groups = []
    for name in GROUP_ORDER:
        items = sorted((o for o in new_main if o.group == name), key=_deadline_key)
        if items:
            groups.append((name, items))

    shown = {o.id for o in closing} | {o.id for o in new_main} | {o.id for o in forecasts}
    still_open = sum(1 for o in open_map.values() if o.id not in shown and o.kind != "forecast")

    counts = (
        f"{len(new_main)} new opportunities, {len(closing)} closing within {config.CLOSING_SOON_DAYS} days, "
        f"{len(forecasts)} new forecasts"
    )
    issue = Issue(
        issue_date=today,
        first_issue=first_issue,
        intro="",
        counts=counts,
        closing_soon=closing,
        new_groups=groups,
        forecasts=forecasts,
        still_open=still_open,
    )
    return issue, new_main + forecasts, open_map


def default_intro(issue: Issue) -> str:
    if issue.new_count == 0:
        lead = "No new SBIR or STTR opportunities appeared this week."
        if issue.closing_soon:
            lead += f" {len(issue.closing_soon)} you may be working on close within three weeks."
        if issue.forecasts:
            lead += f" {len(issue.forecasts)} new forecasts point to solicitations still to come."
        return lead + " Each entry links to the official notice; check it before you apply."
    new_label = "open opportunities" if issue.first_issue else "new opportunities"
    parts = [f"This week there are {issue.new_count} {new_label}"]
    if issue.closing_soon:
        parts.append(f"{len(issue.closing_soon)} closing within three weeks")
    if issue.forecasts:
        parts.append(f"{len(issue.forecasts)} forecasts of solicitations still to come")
    sentence = parts[0] + (", " + ", ".join(parts[1:-1]) if len(parts) > 2 else "")
    if len(parts) > 1:
        sentence += f" and {parts[-1]}"
    return sentence + ". Each entry links to the official notice; check it before you apply."
