# 100 App Integration Research Agent

This repository contains a reproducible research pipeline and a static dashboard that summarizes the integration potential of 100 requested apps. The generated deliverable is a Salesforce-style analytics page in [docs/index.html](docs/index.html).

## What It Produces

- Evidence-backed findings for each app in [data/findings.json](data/findings.json).
- Verification output in [data/verification.json](data/verification.json), including a 30-app review sample.
- A static dashboard built from those artifacts and written to [docs/index.html](docs/index.html).

## Project Structure

- [data/apps.yml](data/apps.yml): source app list and hints.
- [scripts/research.py](scripts/research.py): main research pass that generates findings.
- [scripts/browser_verify.py](scripts/browser_verify.py): optional browser-based evidence sampling.
- [scripts/llm_extract.py](scripts/llm_extract.py): raw first-pass extraction for comparison.
- [scripts/verify.py](scripts/verify.py): schema checks, evidence checks, and review-sample verification.
- [scripts/build_report.py](scripts/build_report.py): renders the static dashboard.
- [tests/test_pipeline.py](tests/test_pipeline.py): end-to-end regression checks.

## Running Locally

Optional development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

If you use a `.env` file, `scripts/research.py` loads it automatically from the repo root.

Common environment variables:

- `ZENMUX_API_KEY`, `ZENMUX_MODEL`, `ZENMUX_BASE_URL`
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`
- `LLM_PROVIDER_ORDER`
- `BROWSER_USE_API_KEY`, `BROWSER_USE_MODEL`
- `COMPOSIO_API_KEY`

End-to-end pipeline:

```bash
python scripts/research.py --input data/apps.yml --output data/findings.json
python scripts/browser_verify.py --findings data/findings.json --verification data/verification.json --output data/browser_audit.json --limit 30 --browser-use-limit 5
python scripts/llm_extract.py --findings data/findings.json --browser-audit data/browser_audit.json --output data/first_pass_findings.json --limit 30
python scripts/verify.py --findings data/findings.json --first-pass data/first_pass_findings.json --browser-audit data/browser_audit.json --output data/verification.json
python scripts/build_report.py --findings data/findings.json --verification data/verification.json --out docs/index.html
python -m unittest discover -s tests
```

Open [docs/index.html](docs/index.html) directly in a browser. No local server is required.

## Deployment

The site is static. [vercel.json](vercel.json) points Vercel at the `docs` folder, and GitHub Pages can also serve the same output from `/docs`.

## Verification Summary

The report is designed to show both the findings and the confidence model behind them:

- 100 app records are normalized into a single schema.
- Evidence links are attached where public documentation exists.
- A 30-app review sample checks risky verdicts and weak evidence.
- First-pass extraction is compared against corrected verification output.

## Notes

- The dashboard styling lives in [scripts/build_report.py](scripts/build_report.py); rebuild the report after visual changes.
- The data and verification artifacts are the source of truth for the page.
- The output is intended to read like an executive dashboard, not a raw table dump.