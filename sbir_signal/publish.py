"""Move an approved draft into the public archive and refresh the site.

    python -m sbir_signal.publish --date 2026-10-19    # publish that draft
    python -m sbir_signal.publish --discard 2026-10-19 # drop a draft that was not approved
    python -m sbir_signal.publish                      # just rebuild index, open list, feed and sitemap
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime

from . import config
from .issue import load_state, save_state, still_relevant
from .normalize import Opportunity
from .render import copy_static, render_feed, render_index, render_open, render_sitemap

log = logging.getLogger("sbir_signal")


def rebuild_site(state: dict) -> None:
    today = datetime.now(config.TIMEZONE).date()
    issues = sorted(state["issues"], key=lambda e: e["date"], reverse=True)
    opps = [Opportunity.from_dict(d) for d in state["open"].values()]
    opps = [o for o in opps if still_relevant(o, today)]
    copy_static()
    (config.SITE_DIR / "index.html").write_text(render_index(issues, None), encoding="utf-8")
    (config.SITE_DIR / "open.html").write_text(render_open(opps, today), encoding="utf-8")
    (config.SITE_DIR / "feed.xml").write_text(render_feed(issues), encoding="utf-8")
    (config.SITE_DIR / "sitemap.xml").write_text(render_sitemap(issues), encoding="utf-8")


def publish(issue_date: str) -> None:
    draft = config.DRAFTS_DIR / issue_date
    if not (draft / "issue.html").exists():
        raise SystemExit(f"No draft found for {issue_date}")
    meta = json.loads((draft / "meta.json").read_text(encoding="utf-8"))
    target = config.SITE_DIR / "issues"
    if (target / f"{issue_date}.html").exists():
        # Never overwrite an issue that is already in the archive (for example a same-day rerun).
        log.warning("An issue for %s is already published; keeping it and discarding this draft.", issue_date)
        shutil.rmtree(draft)
        return
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft / "issue.html", target / f"{issue_date}.html")
    shutil.copyfile(draft / "issue.md", target / f"{issue_date}.md")

    state = load_state()
    state["issues"] = [e for e in state["issues"] if e["date"] != issue_date] + [meta]
    save_state(state)
    shutil.rmtree(draft)
    rebuild_site(state)
    log.info("Published %s", issue_date)


def discard(issue_date: str) -> None:
    draft = config.DRAFTS_DIR / issue_date
    if draft.exists():
        shutil.rmtree(draft)
    log.info("Discarded draft %s", issue_date)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Publish the draft for this date")
    parser.add_argument("--discard", help="Delete the draft for this date")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.date:
        publish(args.date)
    elif args.discard:
        discard(args.discard)
    else:
        rebuild_site(load_state())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
