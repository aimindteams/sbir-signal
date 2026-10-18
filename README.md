# SBIR Signal

**A weekly digest of new SBIR and STTR funding opportunities, with the fine print already read.**

Every Monday this repo finds new SBIR/STTR solicitations, forecasts and related federal notices on SAM.gov and Grants.gov, reads the attached documents for page limits, formatting rules and submission portals, and drafts a newsletter issue. A person checks the draft, publishes it on Substack, and the issue is added to the public archive.

- **Subscribe:** https://sbirsignal.substack.com
- **Archive and open opportunities:** https://aimindteams.github.io/sbir-signal

## How it works

```
Monday 11:17 UTC
  1. GitHub Actions runs the SAM.gov & SBIR RFP Deep-Parser on Apify
     (SAM.gov + SBIR.gov, falling back to Grants.gov; attachments parsed in memory)
  2. sbir_signal.build compares the results with data/state.json to find what is new,
     what closes within 21 days, and which forecasts appeared
  3. Gemini (free tier, optional) writes one plain-English sentence per opportunity;
     any sentence with a number that is not in the source is thrown away
  4. The draft is saved under drafts/ and a GitHub issue labeled sbir-draft is opened
You: paste the draft into Substack and publish, then close the issue as "completed"
  5. publish.yml moves the issue into docs/ and refreshes the archive, open list, RSS and sitemap
```

Closing the issue as **not planned** discards the draft instead.

The data comes from the [SAM.gov & SBIR Federal RFP + Attachment Deep-Parser](https://apify.com/aimindteams/govcon-rfp-deep-parser) on the Apify Store. It is the same tool you can run yourself for your own keywords, NAICS codes and set-asides.

## One-time setup

1. **Secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `APIFY_TOKEN`: an Apify API token (Apify Console → Settings → API & Integrations).
   - `GEMINI_API_KEY` (optional): a free key from [Google AI Studio](https://aistudio.google.com/apikey). Without it the build uses the built-in summaries.
2. **Variable** (same page, Variables tab): `SUBSTACK_URL`, for example `https://sbirsignal.substack.com`.
3. **GitHub Pages** (Settings → Pages): Source "Deploy from a branch", branch `main`, folder `/docs`.
4. Run the **Weekly draft** workflow once by hand (Actions tab → Weekly draft → Run workflow) to get the first issue.

## Run it locally

```bash
pip install -r requirements.txt pytest
python -m pytest -q
python -m sbir_signal.build --input tests/fixtures/sample_run.json --date 2026-10-19 --no-ai
python -m sbir_signal.publish --date 2026-10-19
```

## Settings

Everything you might want to change (newsletter name, Actor input, how many days count as "closing soon", the Gemini model) is in [`sbir_signal/config.py`](sbir_signal/config.py).

## Disclaimer

SBIR Signal is compiled automatically from public federal sources and may contain mistakes. Always confirm deadlines and requirements on the official notice before you apply. Not affiliated with the SBA, SBIR.gov, SAM.gov or any agency.

## License

MIT. See [LICENSE](LICENSE).
