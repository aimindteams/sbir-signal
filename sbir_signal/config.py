"""Settings for the weekly SBIR Signal build. Edit these values, not the code."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

# Where things live in the repo.
DATA_DIR = ROOT / "data"          # pipeline memory: which opportunities were already shown
DRAFTS_DIR = ROOT / "drafts"      # weekly drafts waiting for review
SITE_DIR = ROOT / "docs"          # the public archive served by GitHub Pages
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Branding and links.
NEWSLETTER_NAME = "SBIR Signal"
TAGLINE = "New SBIR and STTR opportunities every week, with the fine print already read."
# "or" (not a get() default) because GitHub passes an unset repository variable as an empty string.
SITE_URL = (os.environ.get("SITE_URL") or "https://aimindteams.github.io/sbir-signal").rstrip("/")
SUBSTACK_URL = (os.environ.get("SUBSTACK_URL") or "https://sbirsignal.substack.com").rstrip("/")
PUBLISHER = "AIMindTeams"

# The Apify Actor that finds and reads the solicitations.
ACTOR_ID = "aimindteams/govcon-rfp-deep-parser"
ACTOR_STORE_URL = "https://apify.com/aimindteams/govcon-rfp-deep-parser"
ACTOR_INPUT = {
    "keywords": ["SBIR", "STTR"],
    "noticeTypes": ["o", "p", "k", "r", "s"],
    "postedWithinDays": 14,
    "maxItems": 80,
    "includeSbir": True,
    "parseAttachments": True,
    "maxAttachmentsPerNotice": 3,
    "includeAttachmentText": False,
    # The pipeline keeps its own memory in data/state.json, so every run sees everything still open.
    "deduplicateAcrossRuns": False,
}
ACTOR_TIMEOUT_SECS = 900
ACTOR_MAX_CHARGE_USD = 2.0

# Gemini (free tier) writes the one-line summaries. Without a key the build still works.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"  # free tier; others are tried if it is retired

# Issue layout.
TIMEZONE = ZoneInfo("America/New_York")
CLOSING_SOON_DAYS = 21
MAX_NEW_ITEMS = 30
