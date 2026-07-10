#!/usr/bin/env python3
"""Fetch evidence pages and save claim-level snippets for verification.

This is a no-dependency browser-verification fallback: it behaves like a simple
read-only browser, records HTTP status, extracts visible-ish text, and stores
snippets around terms that support or contradict each app's claims. It can be
replaced by Playwright/browser-use later without changing the output contract.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import html
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path


CLAIM_TERMS = {
    "auth": ["oauth", "api key", "basic auth", "bearer", "token", "jwt", "client credentials"],
    "access": ["developer", "create an app", "approval", "partner", "contact sales", "admin", "paid", "sandbox"],
    "surface": ["rest", "graphql", "webhook", "api reference", "sdk", "endpoint", "mcp", "model context protocol"],
    "gating": ["approval", "review", "restricted", "partner", "contact us", "contact sales", "enterprise"],
}


def load_env_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def has_real_key(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    if not value:
        return False
    return not any(value.startswith(prefix) for prefix in ("replace_with_", "bu_...", "sk-or-...", "sk-ai-v1-..."))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(url: str, timeout: int) -> tuple[int | None, str, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 integration-browser-verifier/1.0",
            "Accept": "text/html,application/json,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(250_000).decode("utf-8", errors="ignore")
            return response.status, extract_text(raw), None
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTPError: {exc.code}"
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {str(exc)[:160]}"


def extract_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def snippets(text: str, url: str) -> list[dict]:
    lowered = text.lower()
    found = []
    seen = set()
    for claim, terms in CLAIM_TERMS.items():
        for term in terms:
            idx = lowered.find(term)
            if idx == -1:
                continue
            start = max(0, idx - 190)
            end = min(len(text), idx + 310)
            key = (claim, term)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "claim": claim,
                    "term": term,
                    "url": url,
                    "snippet": text[start:end].strip(),
                }
            )
            break
    return found


def verdict_for(row: dict, source_results: list[dict]) -> dict:
    reachable = [source for source in source_results if source["status"] and 200 <= int(source["status"]) < 400]
    terms = {snippet["claim"] for source in source_results for snippet in source.get("claim_snippets", [])}
    expected = set()
    if row.get("auth_methods"):
        expected.add("auth")
    if row.get("api_surface"):
        expected.add("surface")
    if row.get("credential_access") in {"paid_or_admin", "partner_gated"} or row.get("buildability") in {"gated", "blocked"}:
        expected.add("gating")
    missing = sorted(expected - terms)
    return {
        "reachable_sources": len(reachable),
        "support_claim_types": sorted(terms),
        "missing_claim_types": missing,
        "verdict": "supported" if reachable and not missing else ("partial" if reachable else "unreachable"),
    }


def cloud_task_for(row: dict) -> str:
    urls = "\n".join(f"- {url}" for url in row.get("evidence_urls", [])[:3])
    return f"""
Open the official documentation pages below for {row['app']} and verify these integration claims:
- auth methods: {', '.join(row.get('auth_methods', []))}
- credential access: {row.get('credential_access')}
- API surface: {', '.join(row.get('api_surface', []))}
- buildability: {row.get('buildability')}
- MCP status: {row.get('mcp_status')}

Evidence URLs:
{urls}

Return compact JSON only:
{{
  "app": "{row['app']}",
  "verdict": "supported|partial|unsupported|unreachable",
  "checked_urls": ["urls actually opened"],
  "supporting_snippets": ["short snippets or close paraphrases, max 3"],
  "contradictions": ["short contradictions, if any"],
  "notes": "one sentence"
}}
"""


async def run_browser_use_cloud(rows: list[dict], limit: int, timeout: int) -> list[dict]:
    if not has_real_key("BROWSER_USE_API_KEY"):
        return []
    try:
        from browser_use_sdk.v3 import AsyncBrowserUse
    except Exception as exc:
        return [
            {
                "app": row["app"],
                "status": "sdk_import_failed",
                "error": f"{type(exc).__name__}: {str(exc)[:180]}",
            }
            for row in rows[:limit]
        ]

    client = AsyncBrowserUse()
    results = []
    for row in rows[:limit]:
        try:
            result = await asyncio.wait_for(
                client.run(cloud_task_for(row), model=os.environ.get("BROWSER_USE_MODEL", "gpt-5.4-mini")),
                timeout=timeout,
            )
            output = result.output
            parsed = None
            if isinstance(output, str):
                match = re.search(r"\{.*\}", output, flags=re.S)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        parsed = None
            results.append(
                {
                    "app": row["app"],
                    "status": "completed",
                    "model": os.environ.get("BROWSER_USE_MODEL", "gpt-5.4-mini"),
                    "session_id": str(getattr(result, "id", "") or getattr(result, "session_id", "")),
                    "output": parsed or output,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "app": row["app"],
                    "status": "failed",
                    "model": os.environ.get("BROWSER_USE_MODEL", "gpt-5.4-mini"),
                    "error": f"{type(exc).__name__}: {str(exc)[:260]}",
                }
            )
    return results


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", default="data/findings.json")
    parser.add_argument("--verification", default="data/verification.json")
    parser.add_argument("--output", default="data/browser_audit.json")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--browser-use-limit", type=int, default=5, help="Number of sample apps to verify with Browser Use Cloud")
    parser.add_argument("--browser-use-timeout", type=int, default=180, help="Per Browser Use Cloud task timeout in seconds")
    parser.add_argument(
        "--browser-use-mode",
        choices=["auto", "off", "required"],
        default="auto",
        help="Use Browser Use Cloud when BROWSER_USE_API_KEY is present; required fails if missing.",
    )
    args = parser.parse_args()
    socket.setdefaulttimeout(args.timeout)

    findings = load_json(Path(args.findings))["findings"]
    sample_apps = []
    verification_path = Path(args.verification)
    if verification_path.exists():
        sample_apps = [row["app"] for row in load_json(verification_path).get("human_review_sample", [])]
    if not sample_apps:
        sample_apps = [row["app"] for row in findings[: args.limit]]
    sample_apps = sample_apps[: args.limit]
    by_app = {row["app"]: row for row in findings}
    sample_rows = [by_app[app] for app in sample_apps]

    if args.browser_use_mode == "required" and not has_real_key("BROWSER_USE_API_KEY"):
        raise SystemExit("BROWSER_USE_API_KEY is required for --browser-use-mode required")
    cloud_results = []
    if args.browser_use_mode != "off":
        cloud_results = asyncio.run(run_browser_use_cloud(sample_rows, args.browser_use_limit, args.browser_use_timeout))

    fetch_jobs = []
    for app in sample_apps:
        row = by_app[app]
        for url in row.get("evidence_urls", [])[:3]:
            fetch_jobs.append((row["app"], url))

    fetched = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(fetch, url, args.timeout): (app, url)
            for app, url in fetch_jobs
        }
        for future in concurrent.futures.as_completed(future_map):
            app, url = future_map[future]
            try:
                status, text, error = future.result(timeout=args.timeout + 1)
            except Exception as exc:
                status, text, error = None, "", f"{type(exc).__name__}: {str(exc)[:160]}"
            fetched[(app, url)] = {
                "url": url,
                "status": status,
                "error": error,
                "text_length": len(text),
                "claim_snippets": snippets(text, url),
            }
            if args.sleep:
                time.sleep(args.sleep)

    audited = []
    for app in sample_apps:
        row = by_app[app]
        sources = [fetched[(row["app"], url)] for url in row.get("evidence_urls", [])[:3] if (row["app"], url) in fetched]
        audited.append(
            {
                "app": row["app"],
                "category": row["category"],
                "claimed": {
                    "auth_methods": row["auth_methods"],
                    "credential_access": row["credential_access"],
                    "api_surface": row["api_surface"],
                    "buildability": row["buildability"],
                    "mcp_status": row["mcp_status"],
                },
                "sources": sources,
                "audit": verdict_for(row, sources),
            }
        )

    summary_counts = {}
    for row in audited:
        verdict = row["audit"]["verdict"]
        summary_counts[verdict] = summary_counts.get(verdict, 0) + 1
    payload = {
        "metadata": {
            "generated_by": "scripts/browser_verify.py",
            "method": (
                "Browser Use Cloud SDK verification for the first sampled apps when BROWSER_USE_API_KEY is present, "
                "plus concurrent HTTP evidence fetching and claim snippets for the full sample."
            ),
            "sample_count": len(audited),
            "browser_use_sdk": "browser-use-sdk",
            "browser_use_enabled": bool(cloud_results),
        },
        "summary": {
            "sample_count": len(audited),
            "verdict_counts": summary_counts,
            "reachable_sources": sum(row["audit"]["reachable_sources"] for row in audited),
            "browser_use_count": len(cloud_results),
            "browser_use_completed": len([row for row in cloud_results if row.get("status") == "completed"]),
        },
        "browser_use_cloud": cloud_results,
        "apps": audited,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote browser audit for {len(audited)} apps to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
