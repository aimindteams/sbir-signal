"""Weekly build: fetch, decide what is new, summarize, and write a draft for review.

    python -m sbir_signal.build                      # live run (needs APIFY_TOKEN, optional GEMINI_API_KEY)
    python -m sbir_signal.build --input items.json   # use a saved dataset instead of running the Actor
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from . import config
from .fetch import load_file, run_actor
from .issue import default_intro, load_state, plan_issue, save_state
from .normalize import normalize
from .render import render_issue_html, render_markdown
from .summarize import summarize

log = logging.getLogger("sbir_signal")

REVIEW_HEADER = """**How to publish this issue**

1. Read it over. Fix anything in Substack after you paste.
2. Copy everything below the line into a new Substack post and publish it.
3. Close this GitHub issue as **completed** to add it to the web archive, or as **not planned** to skip it.

Web preview of this draft: {preview}

---

"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str, help="Read Actor items from this JSON file instead of running the Actor")
    parser.add_argument("--date", type=str, help="Issue date (YYYY-MM-DD); defaults to today in New York")
    parser.add_argument("--no-ai", action="store_true", help="Skip Gemini even if a key is set")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today = date.fromisoformat(args.date) if args.date else datetime.now(config.TIMEZONE).date()
    items = load_file(Path(args.input)) if args.input else run_actor()

    state = load_state()
    opps = normalize(items, today)
    issue, to_summarize, open_map = plan_issue(opps, state, today)
    if issue.new_count == 0 and not issue.closing_soon and not issue.forecasts:
        log.info("Nothing new and nothing closing soon; no draft this week.")
        _output(drafted="false")
        return 0

    intro = None if args.no_ai else summarize(to_summarize, issue.counts)
    issue.intro = intro or default_intro(issue)

    out_dir = config.DRAFTS_DIR / issue.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(issue)
    (out_dir / "issue.md").write_text(markdown, encoding="utf-8")
    (out_dir / "issue.html").write_text(render_issue_html(issue), encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps({"date": issue.slug, "title": issue.title, "summary": issue.intro}, indent=1) + "\n", encoding="utf-8"
    )
    preview = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'aimindteams/sbir-signal')}/blob/main/drafts/{issue.slug}/issue.md"
    (out_dir / "review.md").write_text(REVIEW_HEADER.format(preview=preview) + markdown, encoding="utf-8")

    for opp in to_summarize:
        open_map[opp.id] = opp  # carries the new summaries
    for opp in open_map.values():
        state["seen"].setdefault(opp.id, issue.slug)
    state["open"] = {opp_id: opp.to_dict() for opp_id, opp in sorted(open_map.items())}
    save_state(state)

    log.info("Draft written to %s (%d new, %d closing soon, %d forecasts)", out_dir, issue.new_count, len(issue.closing_soon), len(issue.forecasts))
    _output(drafted="true", date=issue.slug, title=issue.title)
    return 0


def _output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


if __name__ == "__main__":
    raise SystemExit(main())
