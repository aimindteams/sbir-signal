"""Render an issue as Markdown (review and Substack) and as HTML pages (public archive)."""

from __future__ import annotations

import shutil
from datetime import date, datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .issue import Issue
from .normalize import Opportunity

MIDDOT = chr(0xB7)


def short_date(value: str | None, ref_year: int) -> str:
    if not value:
        return ""
    d = date.fromisoformat(value)
    label = f"{d.strftime('%b')} {d.day}"
    return label if d.year == ref_year else f"{label}, {d.year}"


def deadline_text(opp: Opportunity, ref_year: int) -> str:
    if opp.deadline:
        return f"Due {short_date(opp.deadline, ref_year)}"
    if opp.kind == "forecast":
        return "Not open yet"
    return "No deadline listed"


def meta_line(opp: Opportunity, ref_year: int) -> str:
    bits = [opp.agency]
    program = " ".join(x for x in (opp.program, opp.phase) if x)
    if program:
        bits.append(program)
    bits.append(opp.kind_label)
    bits.append(deadline_text(opp, ref_year))
    return f" {MIDDOT} ".join(bits)


def _env(autoescape: bool) -> Environment:
    env = Environment(
        loader=FileSystemLoader(config.TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]) if autoescape else False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["short_date"] = short_date
    env.globals.update(
        cfg=config,
        deadline_text=deadline_text,
        meta_line=meta_line,
    )
    return env


def render_markdown(issue: Issue, substack: bool = False) -> str:
    """The issue as Markdown. substack=True leaves out the title and stats line, which go in Substack's own fields."""
    return _env(False).get_template("issue.md.j2").render(issue=issue, year=issue.issue_date.year, substack=substack)


def render_issue_html(issue: Issue) -> str:
    return _env(True).get_template("issue.html.j2").render(issue=issue, year=issue.issue_date.year)


def render_index(issues: list[dict], latest_html_path: str | None) -> str:
    return _env(True).get_template("index.html.j2").render(issues=issues, latest=latest_html_path)


def render_open(opps: list[Opportunity], today: date) -> str:
    rows = sorted(opps, key=lambda o: (o.kind == "forecast", o.deadline is None, o.deadline or "", o.title))
    return _env(True).get_template("open.html.j2").render(opps=rows, today=today, year=today.year)


def render_feed(issues: list[dict]) -> str:
    items = []
    for entry in issues[:20]:
        published = datetime.fromisoformat(entry["date"]).replace(hour=12, tzinfo=timezone.utc)
        link = f"{config.SITE_URL}/issues/{entry['date']}.html"
        items.append(
            "<item>"
            f"<title>{escape(entry['title'])}</title><link>{link}</link><guid>{link}</guid>"
            f"<pubDate>{format_datetime(published)}</pubDate>"
            f"<description>{escape(entry.get('summary', ''))}</description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{config.NEWSLETTER_NAME}</title><link>{config.SITE_URL}/</link>"
        f"<description>{escape(config.TAGLINE)}</description>" + "".join(items) + "</channel></rss>\n"
    )


def render_sitemap(issues: list[dict]) -> str:
    urls = [f"{config.SITE_URL}/", f"{config.SITE_URL}/open.html"]
    urls += [f"{config.SITE_URL}/issues/{entry['date']}.html" for entry in issues]
    body = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>\n'
    )


def copy_static() -> None:
    config.SITE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(config.TEMPLATES_DIR / "style.css", config.SITE_DIR / "style.css")
    (config.SITE_DIR / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {config.SITE_URL}/sitemap.xml\n")
    (config.SITE_DIR / ".nojekyll").write_text("")
