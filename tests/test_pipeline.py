import json
from datetime import date
from pathlib import Path

import pytest

from sbir_signal import build, config, publish, summarize
from sbir_signal.issue import empty_state, plan_issue
from sbir_signal.normalize import normalize, to_local_date

FIXTURE = Path(__file__).parent / "fixtures" / "sample_run.json"
TODAY = date(2026, 10, 19)
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)


@pytest.fixture()
def items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "DRAFTS_DIR", "SITE_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    return tmp_path


def test_deadline_uses_new_york_date():
    assert to_local_date("2026-11-09T04:59:00Z") == "2026-11-08"
    assert to_local_date("2026-11-17") == "2026-11-17"
    assert to_local_date(None) is None


def test_normalize_fills_agency_and_facts(items):
    opps = {o.id: o for o in normalize(items, TODAY)}
    epa = opps["sam.gov:82c25ab2750f410cb73817384e8d9fb3"]
    assert epa.agency == "Environmental Protection Agency"
    assert epa.title == "SBIR FY26 Phase I Broad Agency Announcement"
    assert epa.kind == "open"

    usda = opps["grants.gov:364020"]
    assert "Awards of $600,000 to $650,000" in usda.funding
    assert "About $24.75M in total" in usda.funding
    limits = next(f for f in usda.facts if f.startswith("Page limits"))
    assert "20 pages (project narrative)" in limits
    assert "10 pages (commercialization plan)" in limits
    assert "1 page (response to previous review)" in limits
    assert "Format: 12 pt, Times New Roman, 1 inch" in usda.facts
    assert "Read 1 attached document (61 pages)" in usda.facts
    assert usda.facts[0].startswith("Who can apply: Eligibility for the SBIR/STTR Phase II program is limited to only SBIR/STTR Phase I")
    assert "novated" not in usda.summary
    assert usda.group == "Agriculture and environment"

    army = opps["sam.gov:6785c01dbc8f49e6acf889415bf6e062"]
    assert army.agency == "Army (Department of Defense)"
    assert army.group == "Defense"
    assert army.kind == "notice"
    assert "http" not in army.summary and army.summary.startswith("The U.S. Army")

    nih_parent = opps["grants.gov:359671"]
    assert not any(f.startswith("Who can apply") for f in nih_parent.facts)  # standard small-business rule only


def test_summaries_skip_boilerplate(items):
    opps = {o.id: o for o in normalize(items, TODAY)}
    acl = opps["grants.gov:363966"]
    assert not acl.summary.lower().startswith("the purpose of the federal sbir program")
    assert "disabilities" in acl.summary


def test_first_issue_plan(items):
    opps = normalize(items, TODAY)
    issue, to_summarize, open_map = plan_issue(opps, empty_state(), TODAY)
    assert issue.first_issue
    closing_ids = [o.id for o in issue.closing_soon]
    assert closing_ids == ["grants.gov:362551", "sam.gov:82c25ab2750f410cb73817384e8d9fb3"]  # Nov 4, Nov 8
    forecast_ids = {o.id for o in issue.forecasts}
    assert "grants.gov:359726" not in forecast_ids  # posted June 2025: stale forecast dropped
    assert "grants.gov:363966" in forecast_ids
    groups = [name for name, _ in issue.new_groups]
    assert groups[0] == "Defense"


def test_forecast_that_opens_is_announced_again(items):
    opps = normalize(items, TODAY)
    issue, _, open_map = plan_issue(opps, empty_state(), TODAY)
    state = {"seen": {o: TODAY.isoformat() for o in open_map}, "open": {k: v.to_dict() for k, v in open_map.items()}, "issues": []}

    later = [dict(i) for i in items]
    acl = next(i for i in later if i["notice_id"] == "363966")
    acl.update(notice_type_code="synopsis", response_deadline="2026-12-15",
               sbir_details={**acl["sbir_details"], "current_status": "posted", "close_date": "2026-12-15"})
    issue2, to_summarize, _ = plan_issue(normalize(later, date(2026, 10, 26)), state, date(2026, 10, 26))
    assert [o.id for o in to_summarize] == ["grants.gov:363966"]
    assert issue2.new_count == 1


def test_grounding_rejects_invented_numbers(items):
    opp = {o.id: o for o in normalize(items, TODAY)}["grants.gov:364020"]
    assert summarize._grounded("Phase II awards for USDA research, up to $650,000.", opp)
    assert not summarize._grounded("Phase II awards due December 3 for 40 companies.", opp)


def test_gemini_result_is_checked(items, monkeypatch):
    opps = normalize(items, TODAY)
    target = next(o for o in opps if o.id == "grants.gov:364020")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        summarize,
        "_call_gemini",
        lambda prompt: (
            {
                "intro": "This week brings 9 new opportunities " + EM_DASH + " two close soon.",
                "summaries": {target.id: "USDA funds Phase II research for past Phase I winners in food and agriculture."},
            },
            "test-model",
        ),
    )
    intro, status = summarize.summarize(opps, "9 new opportunities, 2 closing within 21 days, 4 new forecasts")
    assert target.summary.startswith("USDA funds Phase II")
    assert intro and EM_DASH not in intro
    assert status.startswith("AI summaries: on (test-model)")


def test_gemini_falls_back_when_a_model_is_retired(monkeypatch):
    import httpx

    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        request = httpx.Request("POST", url)
        if "gemini-3.8-flash" in url:
            return httpx.Response(404, json={"error": {"message": "not found"}}, request=request)
        payload = {"candidates": [{"content": {"parts": [{"text": '```json\n{"intro": "x", "summaries": {}}\n```'}]}}]}
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3.8-flash")  # pretend the configured model is retired
    monkeypatch.setattr(summarize.httpx, "post", fake_post)
    result, model = summarize._call_gemini("prompt")
    assert model == "gemini-3.6-flash" and result["intro"] == "x"
    assert len(calls) == 2


def test_gemini_bad_key_stops_quickly(monkeypatch):
    import httpx

    def fake_post(url, **kwargs):
        return httpx.Response(400, json={"error": {"message": "API key not valid."}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(config, "GEMINI_API_KEY", "bad")
    monkeypatch.setattr(summarize.httpx, "post", fake_post)
    with pytest.raises(RuntimeError, match="API key not valid"):
        summarize._call_gemini("prompt")


def test_build_and_publish_end_to_end(items, sandbox):
    assert build.main(["--input", str(FIXTURE), "--date", TODAY.isoformat(), "--no-ai"]) == 0
    draft = config.DRAFTS_DIR / TODAY.isoformat()
    markdown = (draft / "issue.md").read_text(encoding="utf-8")
    html = (draft / "issue.html").read_text(encoding="utf-8")
    assert markdown.startswith("# SBIR Signal: October 19, 2026")
    assert "## Closing soon" in markdown and "## Open now" in markdown
    for text in (markdown, html):
        assert EM_DASH not in text and EN_DASH not in text
    review = (draft / "review.md").read_text(encoding="utf-8")
    assert "```text\nSBIR Signal: October 19, 2026\n```" in review
    assert "```text\n9 open SBIR/STTR opportunities, 2 closing within 3 weeks, 4 forecasts\n```" in review
    assert "```text\nSBIR, STTR, Weekly issue, NSF, EPA, Defense, NIH, USDA, HHS\n```" in review
    body = review.split("\n---\n", 1)[1]
    assert not body.lstrip().startswith("#") and "**This week:**" not in body
    assert f"drafts/{TODAY.isoformat()}" in review  # publish.yml finds the date here
    state = json.loads((config.DATA_DIR / "state.json").read_text())
    assert len(state["seen"]) == 13  # 16 items minus three stale 2025 forecasts

    publish.main(["--date", TODAY.isoformat()])
    assert (config.SITE_DIR / "issues" / f"{TODAY.isoformat()}.html").exists()
    assert "SBIR Signal: October 19, 2026" in (config.SITE_DIR / "index.html").read_text()
    assert (config.SITE_DIR / "open.html").exists() and (config.SITE_DIR / "feed.xml").exists()
    assert not draft.exists()

    # Same-day rerun: skipped, so today's archive page can never be replaced.
    build.main(["--input", str(FIXTURE), "--date", TODAY.isoformat(), "--no-ai"])
    assert not draft.exists()
    # Three days later with nothing new: skipped too.
    build.main(["--input", str(FIXTURE), "--date", "2026-10-22", "--no-ai"])
    assert not (config.DRAFTS_DIR / "2026-10-22").exists()

    # A week later with nothing new it still drafts, because deadlines are close.
    assert build.main(["--input", str(FIXTURE), "--date", "2026-10-26", "--no-ai"]) == 0
    second_dir = config.DRAFTS_DIR / "2026-10-26"
    second = (second_dir / "issue.md").read_text(encoding="utf-8")
    assert "## New this week" not in second and "## Closing soon" in second
    review = (second_dir / "review.md").read_text(encoding="utf-8")
    assert "```text\nNo new SBIR/STTR opportunities this week, 2 closing within 3 weeks\n```" in review
    assert "No new SBIR or STTR opportunities appeared this week." in second


def test_publish_never_overwrites_an_archived_issue(items, sandbox):
    build.main(["--input", str(FIXTURE), "--date", TODAY.isoformat(), "--no-ai"])
    publish.main(["--date", TODAY.isoformat()])
    page = config.SITE_DIR / "issues" / f"{TODAY.isoformat()}.html"
    original = page.read_text(encoding="utf-8")
    build.main(["--input", str(FIXTURE), "--date", TODAY.isoformat(), "--no-ai", "--force"])
    publish.main(["--date", TODAY.isoformat()])
    assert page.read_text(encoding="utf-8") == original
    assert not (config.DRAFTS_DIR / TODAY.isoformat()).exists()


DSIP_FIXTURE = Path(__file__).parent / "fixtures" / "dsip_items.json"


def test_dod_topics_normalize_cleanly():
    opps = {o.number: o for o in normalize(json.loads(DSIP_FIXTURE.read_text()), TODAY)}
    af = opps["DAF26BX06-DP027"]
    assert af.title == "DAF26BX06-DP027: Proliferated Low-Altitude Detection for C-sUAS"
    assert af.kind == "open" and af.group == "Defense" and af.agency == "Air Force (Department of Defense)"
    assert "On DSIP, search for DAF26BX06-DP027" in af.facts
    assert not any(f.startswith("Submit through DSIP") for f in af.facts)
    assert opps["DPA26BZ06-DV023"].agency == "DARPA (Department of Defense)"
    navy = opps["DON27BX01-NP001"]
    assert navy.kind == "forecast" and navy.kind_label == "Pre-release topic"
    assert navy.opens == "2026-10-28" and navy.deadline == "2026-11-25"
    assert navy.facts[0] == "Questions before it opens: peter.n.squire.civ@us.navy.mil"
    assert navy.summary.startswith("ONR requests proposals")
    army = opps["ARM27BX01-DP001"]
    assert army.summary.startswith("The U.S. Army is seeking") and "Awards up to $2M" in army.funding


def test_big_weeks_are_capped_with_overflow_counts(monkeypatch, sandbox):
    monkeypatch.setattr(config, "MAX_NEW_ITEMS", 3)
    monkeypatch.setattr(config, "MAX_LIST_ITEMS", 1)
    items = json.loads(FIXTURE.read_text()) + json.loads(DSIP_FIXTURE.read_text())
    combined = sandbox / "combined.json"
    combined.write_text(json.dumps(items))
    build.main(["--input", str(combined), "--date", TODAY.isoformat(), "--no-ai"])
    md = (config.DRAFTS_DIR / TODAY.isoformat() / "issue.md").read_text(encoding="utf-8")
    assert "Plus 8 more new opportunities with later deadlines" in md  # 11 open or notice, 3 shown
    assert "Plus 3 more closing within 3 weeks" in md  # 4 closing (2 DoD on Oct 21, NSF, EPA), 1 shown
    assert "## Coming soon: forecasts and pre-release topics" in md
    assert "Opens Oct 28, closes Nov 25" in md
    assert "Plus 5 more on the full list" in md  # 6 forecasts, 1 shown
    assert "**This week:** 11 open" in md
