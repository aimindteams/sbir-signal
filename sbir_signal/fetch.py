"""Get this week's solicitations: run the Apify Actor, or read a saved dataset file."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def load_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):  # allow {"items": [...]}
        data = data.get("items", [])
    return list(data)


def run_actor() -> list[dict]:
    from apify_client import ApifyClient  # imported here so tests do not need the package

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise SystemExit("APIFY_TOKEN is not set. Add it as a repository secret (see README).")
    client = ApifyClient(token)
    log.info("Running %s", config.ACTOR_ID)
    run = client.actor(config.ACTOR_ID).call(
        run_input=config.ACTOR_INPUT,
        timeout_secs=config.ACTOR_TIMEOUT_SECS,
        max_total_charge_usd=config.ACTOR_MAX_CHARGE_USD,
        logger=None,
    )
    if not run or run.get("status") != "SUCCEEDED":
        raise SystemExit(f"Actor run did not succeed: {run and run.get('status')}")
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items(clean=True))
    log.info("Actor returned %d items", len(items))
    return items
