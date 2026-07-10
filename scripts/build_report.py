#!/usr/bin/env python3
"""Render the integration research case study as one static HTML page."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{round(value * 100)}%"


def count_many(rows: list[dict], field: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        value = row[field]
        if isinstance(value, list):
            counter.update(value)
        else:
            counter[value] += 1
    return counter


def summarize(rows: list[dict]) -> dict:
    return {
        "auth": count_many(rows, "auth_methods"),
        "credential": count_many(rows, "credential_access"),
        "surface": count_many(rows, "api_surface"),
        "buildability": count_many(rows, "buildability"),
        "mcp": count_many(rows, "mcp_status"),
        "low_confidence": sum(1 for row in rows if row["confidence"] < 0.65),
    }


def top(counter: Counter, n: int = 4) -> str:
    return ", ".join(f"{label} ({count})" for label, count in counter.most_common(n))


def category_matrix(rows: list[dict]) -> tuple[list[str], list[str], dict]:
    categories = []
    for row in rows:
        if row["category"] not in categories:
            categories.append(row["category"])
    statuses = ["easy_win", "buildable", "gated", "blocked", "poor_fit"]
    matrix = {category: Counter() for category in categories}
    for row in rows:
        matrix[row["category"]][row["buildability"]] += 1
    return categories, statuses, matrix


def esc(value) -> str:
    if isinstance(value, list):
        value = ", ".join(value)
    return html.escape(str(value), quote=True)


def evidence_links(urls: list[str]) -> str:
    links = []
    for i, url in enumerate(urls[:3], start=1):
        safe = html.escape(url, quote=True)
        links.append(
            f'<a href="{safe}" target="_blank" rel="noreferrer">source {i}</a>'
        )
    return " ".join(links)


def render_matrix(rows: list[dict]) -> str:
    categories, statuses, matrix = category_matrix(rows)
    head = "".join(f"<th>{esc(status.replace('_', ' '))}</th>" for status in statuses)
    body = []
    for category in categories:
        cells = "".join(f"<td>{matrix[category][status]}</td>" for status in statuses)
        total = sum(matrix[category].values())
        body.append(f"<tr><th>{esc(category)}</th>{cells}<td>{total}</td></tr>")
    return f"""
    <table class="matrix">
      <thead><tr><th>Category</th>{head}<th>Total</th></tr></thead>
      <tbody>{"".join(body)}</tbody>
    </table>
    """


def render_rows(rows: list[dict]) -> str:
    rendered = []
    for row in rows:
        rendered.append(
            f"""
            <tr data-category="{esc(row["category"])}" data-build="{esc(row["buildability"])}" data-credential="{esc(row["credential_access"])}">
              <td><strong>{esc(row["app"])}</strong><span>{esc(row["category"])}</span></td>
              <td>{esc(row["description"])}</td>
              <td>{esc(row["auth_methods"])}</td>
              <td><span class="pill">{esc(row["credential_access"].replace("_", " "))}</span></td>
              <td>{esc(row["api_surface"])}<span>{esc(row["surface_breadth"])} surface</span></td>
              <td><span class="pill {esc(row["buildability"])}">{esc(row["buildability"].replace("_", " "))}</span><span>{esc(row["main_blocker"])}</span></td>
              <td>{esc(row["mcp_status"].replace("_", " "))}</td>
              <td>{evidence_links(row["evidence_urls"])}<span>confidence {esc(row["confidence"])}</span></td>
            </tr>
            """
        )
    return "\n".join(rendered)


def render_verification(verification: dict) -> str:
    summary = verification["summary"]
    first_pass = summary.get("first_pass_comparison")
    browser_audit = summary.get("browser_audit")
    examples = []
    for row in verification["human_review_sample"]:
        if row["status"] in {"corrected", "miss"}:
            examples.append(
                f"""
                <article class="review-card">
                  <strong>{esc(row["app"])}</strong>
                  <span class="pill {esc(row["status"])}">{esc(row["status"])}</span>
                  <p>{esc(row["note"])}</p>
                </article>
                """
            )
    correction_examples = []
    if first_pass:
        for row in first_pass.get("examples", [])[:4]:
            mismatch_text = "; ".join(
                f"{item['field']}: {item['first_pass']} -> {item['corrected']}"
                for item in row.get("mismatches", [])[:3]
            )
            correction_examples.append(
                f"""
                <article class="review-card">
                  <strong>{esc(row["app"])}</strong>
                  <span class="pill corrected">model correction</span>
                  <p>{esc(mismatch_text)}</p>
                </article>
                """
            )
    snippet_examples = []
    if browser_audit:
        for row in browser_audit.get("snippet_examples", [])[:4]:
            snippet_examples.append(
                f"""
                <article class="review-card">
                  <strong>{esc(row["app"])}</strong>
                  <span class="pill">{esc(row["claim"])}: {esc(row["term"])}</span>
                  <p>{esc(row["snippet"])}</p>
                  <a href="{esc(row["url"])}" target="_blank" rel="noreferrer">evidence URL</a>
                </article>
                """
            )
    browser_line = "Browser audit not generated."
    if browser_audit:
        browser_line = (
            f"Browser audit checked {browser_audit.get('sample_count', 0)} apps, "
            f"reached {browser_audit.get('reachable_sources', 0)} cited sources, "
            f"ran {browser_audit.get('browser_use_completed', 0)}/{browser_audit.get('browser_use_count', 0)} Browser Use Cloud tasks, "
            f"and classified evidence as {browser_audit.get('verdict_counts', {})}."
        )
    first_pass_line = "No raw LLM first-pass artifact was present."
    if first_pass:
        first_pass_line = (
            f"Raw first pass covered {first_pass.get('sample_count', 0)} apps, "
            f"with {first_pass.get('exact_matches', 0)} exact matches and "
            f"{first_pass.get('corrections_needed', 0)} corrections needed."
        )
    return f"""
    <section class="band" id="verification">
      <div class="section-head">
        <p class="eyebrow">Verification</p>
        <h2>Accuracy improved because the verifier looked for contradictions, not just links.</h2>
      </div>
      <div class="metrics four">
        <div><strong>{summary["sample_count"]}</strong><span>human-checked apps</span></div>
        <div><strong>{pct(summary["first_pass_accuracy"])}</strong><span>first-pass exact accuracy</span></div>
        <div><strong>{pct(summary["post_correction_accuracy"])}</strong><span>after correction or downgrade</span></div>
        <div><strong>{summary["warning_count"]}</strong><span>low-confidence warnings</span></div>
      </div>
      <p class="wide">{esc(summary["trust_statement"])}</p>
      <p class="wide">{esc(first_pass_line)}</p>
      <p class="wide">{esc(browser_line)}</p>
      <div class="review-grid">{"".join(correction_examples)}</div>
      <div class="review-grid">{"".join(snippet_examples)}</div>
      <div class="review-grid">{"".join(examples)}</div>
    </section>
    """


def render_html(findings: dict, verification: dict) -> str:
    rows = findings["findings"]
    summary = summarize(rows)
    total = len(rows)
    self_serve = summary["credential"]["self_serve"]
    easy = summary["buildability"]["easy_win"]
    gated = (
        summary["buildability"]["gated"]
        + summary["buildability"]["blocked"]
        + summary["buildability"]["poor_fit"]
    )
    official_mcp = summary["mcp"]["official"]
    public_rest = summary["surface"]["REST"]
    verified_count = total - summary["low_confidence"]
    score_rows = [
        ("Self-serve access", self_serve, total),
        ("Easy-win builds", easy, total),
        ("REST surfaces", public_rest, total),
        ("Official MCP", official_mcp, total),
    ]

    headline_patterns = [
        f"Self-serve wins dominate: {self_serve}/{total} apps expose credentials a developer can usually obtain without sales.",
        f"REST is still the default agent substrate: {public_rest}/{total} apps have a documented REST surface.",
        f"The biggest blockers are access gates, not missing APIs: {gated}/{total} need outreach, admin approval, paid plans, or are poor fits.",
        f"Official MCP is emerging but sparse: {official_mcp}/{total} apps had official MCP or agent-toolkit evidence in this pass.",
    ]
    pattern_cards = "".join(f"<li>{esc(pattern)}</li>" for pattern in headline_patterns)
    score_cards = "".join(
        f"""
        <div class=\"score-card\">
          <span>{esc(label)}</span>
          <strong>{count}</strong>
          <div class=\"meter\"><i style=\"width:{max(8, round((count / total) * 100))}%\"></i></div>
          <small>{pct(count / total)} of the research set</small>
        </div>
        """
        for label, count, total in score_rows
    )
    signal_tiles = "".join(
        f"""
        <article class=\"signal-tile\">
          <p>{esc(label)}</p>
          <strong>{count}</strong>
          <span>out of {total} apps</span>
        </article>
        """
        for label, count, total in [
            ("Self-serve access", self_serve, total),
            ("Verified rows", verified_count, total),
            ("Easy-win surface", easy, total),
            ("MCP-ready signals", official_mcp, total),
        ]
    )

    data_json = json.dumps(
        {
            "auth": summary["auth"],
            "credential": summary["credential"],
            "buildability": summary["buildability"],
            "mcp": summary["mcp"],
        },
        ensure_ascii=False,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>100 App Integration Research Case Study</title>
  <style>
    :root {{
      --ink: #16325c;
      --muted: #5c6b85;
      --line: #d7e3f4;
      --paper: #eef4fb;
      --field: #ffffff;
      --panel: rgba(255, 255, 255, .84);
      --soft: #f4f9ff;
      --blue: #d8e9ff;
      --cyan: #d2f0ff;
      --mint: #d8f6e8;
      --rose: #ffe0e0;
      --gold: #fff0bf;
      --violet: #e8e4ff;
      --accent: #0176d3;
      --accent-deep: #0b5cab;
      --teal: #0f766e;
      --red: #ba0517;
      --green: #2e844a;
      --shadow: 0 22px 60px rgba(22, 50, 92, .10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(1, 118, 211, .10), transparent 30%),
        radial-gradient(circle at top right, rgba(46, 132, 74, .08), transparent 26%),
        linear-gradient(180deg, #ffffff 0%, var(--paper) 360px),
        var(--paper);
      line-height: 1.45;
      letter-spacing: 0;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell-topbar {{
      position: sticky;
      top: 0;
      z-index: 40;
      backdrop-filter: blur(18px);
      background: rgba(255, 255, 255, .72);
      border-bottom: 1px solid rgba(215, 227, 244, .9);
    }}
    .topbar-inner {{
      max-width: 1260px;
      margin: 0 auto;
      padding: 14px clamp(18px, 4vw, 34px);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    .brand-mark {{
      width: 36px;
      height: 36px;
      border-radius: 12px;
      background: linear-gradient(135deg, var(--accent), #56b3ff);
      box-shadow: 0 12px 24px rgba(1, 118, 211, .28);
    }}
    .brand strong {{ display: block; font-size: 14px; letter-spacing: .02em; }}
    .brand span, .topbar-meta span {{ display: block; color: var(--muted); font-size: 12px; }}
    .topbar-meta {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .topbar-chip {{
      border: 1px solid var(--line);
      background: white;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 700;
      color: var(--accent-deep);
      box-shadow: 0 8px 18px rgba(22, 50, 92, .05);
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 44px clamp(20px, 5vw, 72px) 36px;
      border-bottom: 1px solid rgba(215, 227, 244, .92);
      background:
        radial-gradient(circle at top left, rgba(1, 118, 211, .16), transparent 33%),
        radial-gradient(circle at right center, rgba(87, 181, 231, .18), transparent 30%),
        linear-gradient(120deg, rgba(255,255,255,.98), rgba(241,247,255,.92) 52%, rgba(229,243,255,.95));
      background-size: cover;
      background-position: center;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -8% -40% auto;
      width: 420px;
      height: 420px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(1,118,211,.18), rgba(1,118,211,0) 68%);
      pointer-events: none;
    }}
    .hero-inner {{
      position: relative;
      z-index: 1;
      max-width: 1260px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(330px, .9fr);
      gap: 28px;
      align-items: center;
    }}
    .eyebrow {{
      margin: 0 0 12px;
      color: var(--accent);
      font-weight: 800;
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: .12em;
    }}
    h1 {{
      margin: 0;
      max-width: 980px;
      font-size: clamp(40px, 6.4vw, 82px);
      line-height: .96;
      letter-spacing: 0;
      text-wrap: balance;
    }}
    .hero p {{
      max-width: 740px;
      margin: 22px 0 22px;
      font-size: clamp(18px, 2vw, 22px);
      color: #43546f;
    }}
    .pattern-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 0;
      margin: 24px 0 0;
      max-width: 1000px;
      list-style: none;
    }}
    .pattern-list li {{
      background: rgba(255,255,255,.88);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 14px;
      padding: 16px 18px;
      font-weight: 650;
      box-shadow: 0 12px 30px rgba(22, 50, 92, .06);
    }}
    .hero-panel {{ display: grid; gap: 14px; }}
    .hero-panel-card {{
      background: rgba(255,255,255,.88);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 20px 48px rgba(22, 50, 92, .10);
    }}
    .hero-panel-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    .signal-tile, .score-card {{
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,249,255,.94));
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 18px;
      padding: 14px 16px;
      box-shadow: 0 12px 28px rgba(22, 50, 92, .06);
    }}
    .signal-tile p, .score-card span {{ margin: 0; color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }}
    .signal-tile strong, .score-card strong {{ display: block; margin-top: 8px; font-size: 30px; line-height: 1; color: var(--accent-deep); }}
    .signal-tile span, .score-card small {{ display: block; margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .meter {{
      margin-top: 12px;
      height: 8px;
      border-radius: 999px;
      background: #e6eef8;
      overflow: hidden;
    }}
    .meter i {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), #56b3ff);
    }}
    main {{ padding: 0 clamp(18px, 4vw, 60px) 64px; }}
    section {{ max-width: 1260px; margin: 0 auto; padding: 54px 0; }}
    .band {{ border-bottom: 1px solid var(--line); }}
    .section-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, .45fr);
      gap: 24px;
      align-items: end;
      margin-bottom: 22px;
    }}
    .section-head h2 {{ margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.05; letter-spacing: -.01em; }}
    .section-head p:last-child {{ margin: 0; color: var(--muted); }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin: 22px 0;
    }}
    .metrics.four {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .metrics div, .review-card, .workflow-step {{
      background: var(--panel);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 18px;
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    .metrics strong {{ display: block; font-size: 34px; line-height: 1; color: var(--accent-deep); }}
    .metrics span, td span, .small {{ display: block; color: var(--muted); font-size: 12px; margin-top: 5px; }}
    .insights {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .insights article {{
      border-left: 5px solid var(--accent);
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,249,255,.95));
      padding: 18px;
      border-radius: 18px;
      border-top: 1px solid rgba(215, 227, 244, .95);
      border-right: 1px solid rgba(215, 227, 244, .95);
      border-bottom: 1px solid rgba(215, 227, 244, .95);
      box-shadow: var(--shadow);
    }}
    .insights h3 {{ margin: 0 0 8px; }}
    .insights p, .wide {{ color: var(--muted); margin: 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: rgba(255,255,255,.98);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: var(--shadow);
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
    }}
    th {{ background: #f2f7ff; font-size: 12px; text-transform: uppercase; color: #4d5f7c; letter-spacing: .04em; }}
    .matrix td {{ text-align: center; }}
    .dataset-panel {{
      background: rgba(255,255,255,.94);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 22px;
      padding: 16px;
      box-shadow: var(--shadow);
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1.5fr repeat(3, minmax(150px, 1fr));
      gap: 10px;
      margin: 0 0 14px;
      padding: 12px;
      background: linear-gradient(180deg, #f8fbff, #eef5ff);
      border: 1px solid rgba(215, 227, 244, .95);
      border-radius: 18px;
    }}
    input, select {{
      width: 100%;
      border: 1px solid rgba(186, 203, 227, .95);
      border-radius: 12px;
      padding: 11px 12px;
      font: inherit;
      background: white;
      box-shadow: 0 8px 18px rgba(22, 50, 92, .04);
    }}
    .table-wrap {{
      max-height: 620px;
      overflow: auto;
      border-radius: 18px;
      border: 1px solid rgba(215, 227, 244, .95);
      background: white;
    }}
    .table-wrap table {{
      border: 0;
      border-radius: 0;
      box-shadow: none;
      min-width: 1180px;
    }}
    .table-wrap thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      box-shadow: 0 1px 0 var(--line);
    }}
    .table-wrap tbody tr:nth-child(even) td {{ background: #fbfdff; }}
    .table-wrap tbody tr:hover td {{ background: #f3f8ff; }}
    .pill {{
      display: inline-block;
      border-radius: 999px;
      padding: 4px 8px;
      background: var(--blue);
      color: var(--accent-deep);
      font-size: 12px;
      font-weight: 700;
    }}
    .easy_win {{ background: var(--mint); color: var(--green); }}
    .buildable {{ background: var(--cyan); color: #0e7490; }}
    .gated, .blocked, .poor_fit, .miss {{ background: var(--rose); color: var(--red); }}
    .corrected {{ background: var(--gold); color: #765c04; }}
    .official {{ background: var(--violet); color: #5b21b6; }}
    .workflow {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .workflow-step b {{ display: block; margin-bottom: 8px; }}
    .review-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    code, pre {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      background: #eef4ff;
      border-radius: 6px;
    }}
    pre {{
      padding: 16px;
      overflow-x: auto;
      border: 1px solid rgba(215, 227, 244, .95);
      box-shadow: var(--shadow);
    }}
    footer {{ max-width: 1260px; margin: 0 auto; padding: 32px 0 48px; color: var(--muted); }}
    .footer-shell {{
      background: rgba(255,255,255,.78);
      border-top: 1px solid rgba(215, 227, 244, .95);
    }}
    @media (max-width: 900px) {{
      .hero-inner, .pattern-list, .section-head, .metrics, .metrics.four, .insights, .workflow, .review-grid, .controls, .hero-panel-grid {{
        grid-template-columns: 1fr;
      }}
      .topbar-inner {{ flex-direction: column; align-items: flex-start; }}
      .hero {{ padding-top: 28px; padding-bottom: 28px; }}
      th, td {{ min-width: 150px; }}
    }}
  </style>
</head>
<body>
  <div class="shell-topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-mark"></div>
        <div>
          <strong>Agent Web Research Console</strong>
          <span>Salesforce-style dashboard for app integration intelligence</span>
        </div>
      </div>
      <div class="topbar-meta">
        <div class="topbar-chip">{total} apps analyzed</div>
        <div class="topbar-chip">{verified_count} verified rows</div>
        <div class="topbar-chip">{official_mcp} MCP signals</div>
      </div>
    </div>
  </div>
  <header class="hero">
    <div class="hero-inner">
      <div>
        <p class="eyebrow">Composio-style integration research</p>
        <h1>100 requested apps, reduced to integration patterns.</h1>
        <p>A reproducible agent pipeline classified auth, access gates, API breadth, MCP readiness, buildability, and evidence for every app in the research set.</p>
        <ul class="pattern-list">{pattern_cards}</ul>
      </div>
      <div class="hero-panel">
        <div class="hero-panel-card">
          <div class="hero-panel-grid">{signal_tiles}</div>
          <div class="metrics four">{score_cards}</div>
        </div>
      </div>
    </div>
  </header>
  <main>
    <section class="band">
      <div class="section-head">
        <div>
          <p class="eyebrow">Headline</p>
          <h2>The easy wins are developer platforms, productivity tools, ecommerce, support, and API-native data vendors.</h2>
        </div>
        <p>Partner-gated work clusters in ads, enterprise commerce, financial data, private-market research, and newer AI/media apps with thin public APIs.</p>
      </div>
      <div class="metrics">
        <div><strong>{self_serve}</strong><span>self-serve or trial-friendly</span></div>
        <div><strong>{easy}</strong><span>easy-win toolkits</span></div>
        <div><strong>{public_rest}</strong><span>documented REST APIs</span></div>
        <div><strong>{official_mcp}</strong><span>official MCP or agent-toolkit paths</span></div>
        <div><strong>{summary["low_confidence"]}</strong><span>low-confidence rows</span></div>
      </div>
      <div class="insights">
        <article><h3>Auth pattern</h3><p>{esc(top(summary["auth"]))}. OAuth2 plus API keys covers most practical integrations; Basic auth appears mainly in older REST APIs.</p></article>
        <article><h3>Access pattern</h3><p>{esc(top(summary["credential"]))}. A toolkit can be built for most apps today, but production rollout often depends on admin scopes or vendor approval.</p></article>
        <article><h3>Buildability pattern</h3><p>{esc(top(summary["buildability"]))}. Missing APIs are rarer than gated credentials, review processes, and unsafe write actions.</p></article>
      </div>
    </section>

    <section class="band">
      <div class="section-head">
        <div>
          <p class="eyebrow">Matrix</p>
          <h2>Where the work lands by category.</h2>
        </div>
        <p>Counts are verdicts after consistency checks and human review downgrades for weak evidence.</p>
      </div>
      {render_matrix(rows)}
    </section>

    <section class="band">
      <div class="section-head">
        <div>
          <p class="eyebrow">Full dataset</p>
          <h2>100 app findings with evidence links.</h2>
        </div>
        <p>Use the filters to find outreach targets, easy wins, MCP candidates, or low-confidence rows.</p>
      </div>
      <div class="dataset-panel">
        <div class="controls">
          <input id="search" placeholder="Search app, auth, blocker, evidence note">
          <select id="category"><option value="">All categories</option></select>
          <select id="build"><option value="">All verdicts</option></select>
          <select id="credential"><option value="">All credential access</option></select>
        </div>
        <div class="table-wrap">
          <table id="findings">
            <thead>
              <tr>
                <th>App</th><th>What it does</th><th>Auth</th><th>Access</th><th>API surface</th><th>Verdict and blocker</th><th>MCP</th><th>Evidence</th>
              </tr>
            </thead>
            <tbody>{render_rows(rows)}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="band">
      <div class="section-head">
        <div>
          <p class="eyebrow">Agent</p>
          <h2>The pipeline is an agentic research loop, with human review only where it matters.</h2>
        </div>
        <p>The default run is deterministic without keys. Add ZenMux for the primary Grok pass, OpenRouter as fallback, and Composio for tool routing if available.</p>
      </div>
      <div class="workflow">
        <div class="workflow-step"><b>1. Scout</b><span>Loads the 100 apps, normalizes hints, and attaches likely official docs, auth pages, API references, and MCP sources.</span></div>
        <div class="workflow-step"><b>2. Extract</b><span>Classifies auth, access gates, API surface, breadth, MCP status, buildability, blocker, evidence, and confidence.</span></div>
        <div class="workflow-step"><b>3. Verify</b><span>Checks schema coverage, evidence presence, low-confidence rows, and contradictions such as OAuth without OAuth evidence.</span></div>
        <div class="workflow-step"><b>4. Human review</b><span>Samples 30 apps across all categories and every risky verdict, then records hits, corrections, and misses.</span></div>
      </div>
    </section>

    {render_verification(verification)}

    <section class="band">
      <div class="section-head">
        <div>
          <p class="eyebrow">Runnable proof</p>
          <h2>Rebuild the research artifacts and this page.</h2>
        </div>
        <p>The repo is static-site ready: deploy <code>docs/index.html</code> with GitHub Pages from the <code>/docs</code> folder.</p>
      </div>
      <pre><code>$env:ZENMUX_API_KEY="sk-ai-v1-..."
$env:ZENMUX_MODEL="x-ai/grok-4.5-free"
$env:ZENMUX_BASE_URL="https://zenmux.ai/api/v1"
$env:OPENROUTER_API_KEY="sk-or-..."
$env:OPENROUTER_MODEL="tencent/hy3:free"
$env:LLM_PROVIDER_ORDER="zenmux,openrouter"
$env:BROWSER_USE_API_KEY="bu_..."
$env:BROWSER_USE_MODEL="gpt-5.4-mini"
python scripts/research.py --input data/apps.yml --output data/findings.json
python scripts/browser_verify.py --findings data/findings.json --verification data/verification.json --output data/browser_audit.json --limit 30 --browser-use-limit 5
python scripts/llm_extract.py --findings data/findings.json --browser-audit data/browser_audit.json --output data/first_pass_findings.json --limit 30
python scripts/verify.py --findings data/findings.json --first-pass data/first_pass_findings.json --browser-audit data/browser_audit.json --output data/verification.json
python scripts/build_report.py --findings data/findings.json --verification data/verification.json --out docs/index.html
python -m unittest discover -s tests</code></pre>
    </section>
  </main>
  <div class="footer-shell">
    <footer>
      Generated from {total} app findings. Data summary: <code id="summary-data">{html.escape(data_json)}</code>
    </footer>
  </div>
  <script>
    const table = document.querySelector("#findings");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const controls = {{
      search: document.querySelector("#search"),
      category: document.querySelector("#category"),
      build: document.querySelector("#build"),
      credential: document.querySelector("#credential")
    }};
    function fill(select, values) {{
      [...new Set(values)].sort().forEach(value => {{
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value.replaceAll("_", " ");
        select.appendChild(option);
      }});
    }}
    fill(controls.category, rows.map(row => row.dataset.category));
    fill(controls.build, rows.map(row => row.dataset.build));
    fill(controls.credential, rows.map(row => row.dataset.credential));
    function applyFilters() {{
      const query = controls.search.value.trim().toLowerCase();
      rows.forEach(row => {{
        const matchesSearch = !query || row.textContent.toLowerCase().includes(query);
        const matchesCategory = !controls.category.value || row.dataset.category === controls.category.value;
        const matchesBuild = !controls.build.value || row.dataset.build === controls.build.value;
        const matchesCredential = !controls.credential.value || row.dataset.credential === controls.credential.value;
        row.style.display = matchesSearch && matchesCategory && matchesBuild && matchesCredential ? "" : "none";
      }});
    }}
    Object.values(controls).forEach(control => control.addEventListener("input", applyFilters));
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", default="data/findings.json")
    parser.add_argument("--verification", default="data/verification.json")
    parser.add_argument("--out", default="docs/index.html")
    args = parser.parse_args()

    html_text = render_html(load_json(args.findings), load_json(args.verification))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
