#!/usr/bin/env python3
"""Create a raw LLM first-pass extraction for sampled integration findings.

ZenMux is tried first, then OpenRouter. The script intentionally writes a
separate artifact so the corrected/curated findings can be compared against the
model's first pass instead of overwriting it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULTS = {
    "ZENMUX_MODEL": "x-ai/grok-4.5-free",
    "ZENMUX_BASE_URL": "https://zenmux.ai/api/v1",
    "OPENROUTER_MODEL": "tencent/hy3:free",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "LLM_PROVIDER_ORDER": "zenmux,openrouter",
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
    return not any(value.startswith(prefix) for prefix in ("replace_with_", "sk-or-...", "sk-ai-v1-..."))


def providers() -> list[dict]:
    order = os.environ.get("LLM_PROVIDER_ORDER", DEFAULTS["LLM_PROVIDER_ORDER"]).split(",")
    configs = {
        "zenmux": {
            "name": "zenmux",
            "key_env": "ZENMUX_API_KEY",
            "model": os.environ.get("ZENMUX_MODEL", DEFAULTS["ZENMUX_MODEL"]),
            "base_url": os.environ.get("ZENMUX_BASE_URL", DEFAULTS["ZENMUX_BASE_URL"]),
        },
        "openrouter": {
            "name": "openrouter",
            "key_env": "OPENROUTER_API_KEY",
            "model": os.environ.get("OPENROUTER_MODEL", DEFAULTS["OPENROUTER_MODEL"]),
            "base_url": os.environ.get("OPENROUTER_BASE_URL", DEFAULTS["OPENROUTER_BASE_URL"]),
        },
    }
    return [configs[name.strip()] for name in order if name.strip() in configs and has_real_key(configs[name.strip()]["key_env"])]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def call_chat(provider: dict, prompt: str, timeout: int) -> dict:
    payload = {
        "model": provider["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You classify SaaS/API integration buildability. Return strict JSON only. "
                    "If evidence is thin, choose unclear or low confidence."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 700,
    }
    request = urllib.request.Request(
        provider["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ[provider["key_env"]],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="ignore"))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return parse_json(content)


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def heuristic_first_pass(row: dict, reason: str) -> dict:
    return {
        "app": row["app"],
        "category": row["category"],
        "auth_methods": row["auth_methods"][:1] or ["unclear"],
        "credential_access": "unclear" if row["confidence"] < 0.7 else row["credential_access"],
        "api_surface": row["api_surface"][:1] or ["none"],
        "buildability": "blocked" if row["confidence"] < 0.6 else row["buildability"],
        "mcp_status": row["mcp_status"],
        "main_blocker": row["main_blocker"],
        "confidence": max(0.35, min(0.72, row["confidence"] - 0.18)),
        "evidence_used": row["evidence_urls"][:2],
        "extraction_notes": f"Heuristic fallback because LLM call failed or was unavailable: {reason}",
    }


def prompt_for(row: dict, snippets: list[dict]) -> str:
    snippet_text = "\n".join(
        f"- {item.get('url')}: {item.get('snippet', '')[:900]}" for item in snippets[:4] if item.get("snippet")
    )
    return f"""
Classify this app for building an AI-agent integration toolkit.

App: {row['app']}
Category: {row['category']}
Hint/docs URLs: {', '.join(row['evidence_urls'][:3])}
Existing evidence notes: {row['evidence_notes']}
Fetched snippets:
{snippet_text or 'No fetched snippets available.'}

Return JSON with exactly these fields:
{{
  "app": "{row['app']}",
  "category": "{row['category']}",
  "auth_methods": ["OAuth2|API key|Basic|token|other|unclear"],
  "credential_access": "self_serve|paid_or_admin|partner_gated|unclear",
  "api_surface": ["REST|GraphQL|SDK|MCP|unofficial|none"],
  "buildability": "easy_win|buildable|gated|poor_fit|blocked",
  "mcp_status": "official|community|none|unclear",
  "main_blocker": "short blocker",
  "confidence": 0.0,
  "evidence_used": ["urls used"],
  "extraction_notes": "short reason"
}}
"""


def prompt_for_batch(rows: list[dict], browser_audit: dict | None) -> str:
    items = []
    for row in rows:
        snippet_text = " ".join(
            item.get("snippet", "")[:420] for item in snippets_for(browser_audit, row["app"])[:3] if item.get("snippet")
        )
        items.append(
            {
                "app": row["app"],
                "category": row["category"],
                "evidence_urls": row["evidence_urls"][:3],
                "evidence_notes": row["evidence_notes"],
                "snippets": snippet_text[:1200],
            }
        )
    return f"""
Classify each app below for building an AI-agent integration toolkit.
Use only the provided URLs/notes/snippets. If evidence is thin, choose unclear or low confidence.

Apps:
{json.dumps(items, ensure_ascii=False)}

Return a JSON array. Each item must have exactly these fields:
app, category, auth_methods, credential_access, api_surface, buildability,
mcp_status, main_blocker, confidence, evidence_used, extraction_notes.

Allowed credential_access: self_serve, paid_or_admin, partner_gated, unclear.
Allowed api_surface values: REST, GraphQL, SDK, MCP, unofficial, none.
Allowed buildability: easy_win, buildable, gated, poor_fit, blocked.
Allowed mcp_status: official, community, none, unclear.
"""


def snippets_for(browser_audit: dict | None, app: str) -> list[dict]:
    if not browser_audit:
        return []
    for row in browser_audit.get("apps", []):
        if row.get("app") == app:
            snippets = []
            for source in row.get("sources", []):
                snippets.extend(source.get("claim_snippets", []))
            return snippets
    return []


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", default="data/findings.json")
    parser.add_argument("--browser-audit", default="data/browser_audit.json")
    parser.add_argument("--output", default="data/first_pass_findings.json")
    parser.add_argument("--limit", type=int, default=30, help="Number of apps to run through the LLM first pass")
    parser.add_argument("--batch-size", type=int, default=10, help="Apps per LLM request")
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args()

    findings = load_json(Path(args.findings))["findings"]
    audit_path = Path(args.browser_audit)
    browser_audit = load_json(audit_path) if audit_path.exists() else None
    available_providers = providers()

    rows = []
    failures = []
    selected = findings[: args.limit]
    for start in range(0, len(selected), max(1, args.batch_size)):
        batch = selected[start : start + max(1, args.batch_size)]
        result = None
        used_provider = None
        errors = []
        for provider in available_providers:
            try:
                if len(batch) == 1:
                    result = [call_chat(provider, prompt_for(batch[0], snippets_for(browser_audit, batch[0]["app"])), args.timeout)]
                else:
                    parsed = call_chat(provider, prompt_for_batch(batch, browser_audit), args.timeout)
                    result = parsed if isinstance(parsed, list) else [parsed]
                used_provider = provider["name"]
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, OSError) as exc:
                errors.append(f"{provider['name']}: {type(exc).__name__}: {str(exc)[:180]}")
                continue
        if result is None:
            result = [heuristic_first_pass(row, "; ".join(errors) or "no configured provider") for row in batch]
            used_provider = "heuristic_fallback"
            failures.extend({"app": row["app"], "errors": errors or ["no configured provider"]} for row in batch)
        by_app = {row["app"]: row for row in batch}
        for item in result:
            if not isinstance(item, dict):
                continue
            source = by_app.get(item.get("app"))
            if not source:
                continue
            item["provider"] = used_provider
            item["corrected_reference"] = {
                "credential_access": source["credential_access"],
                "api_surface": source["api_surface"],
                "buildability": source["buildability"],
                "mcp_status": source["mcp_status"],
                "confidence": source["confidence"],
            }
            rows.append(item)
        time.sleep(args.sleep)

    payload = {
        "metadata": {
            "generated_by": "scripts/llm_extract.py",
            "sample_count": len(rows),
            "provider_order": [provider["name"] for provider in available_providers] or ["heuristic_fallback"],
            "note": "Raw first-pass model classifications before verifier/human corrections.",
        },
        "findings": rows,
        "failures": failures,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} first-pass findings to {out_path}")
    if failures:
        print(f"Fallbacks used for {len(failures)} apps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
