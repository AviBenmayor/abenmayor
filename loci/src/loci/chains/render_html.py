"""`loci chains render --html` -- data/chains/chains_watchlist.html + chains_data.json.

A read-only companion to `docs/CHAINS.md` (`render.py`), for the owner to browse
with `loci chains serve` instead of reading a markdown table. It shares
`render.assemble()` with the markdown renderer (see that module's docstring) so
the two documents can never disagree about which brand is hand-vetted, auto-
admitted or rejected.

The page is STATIC and the data is NOT: `chains_watchlist.html` fetches
`chains_data.json` at load time rather than embedding it, so the page itself
rarely changes while the data behind it is regenerated every `chains refresh`.
Both live under `data/` (gitignored) -- this is a read model, not a source of
truth, and `watchlist.yaml` remains the only hand-edited file.

Sort default, before any client-side interaction: within each section,
`sales_role: incumbent` rows (co-op supermarket banners chief among them) sink
to the bottom. They are on the list for completeness, not because a broker
lead exists to sell -- D113's `sales_role` table says so, and a reader
skimming this page top-down should see prospects first.
"""
from __future__ import annotations

import datetime as dt
import json as json_mod
import math
import pathlib

from loci.chains import render as ren

REPO_ROOT = ren.REPO_ROOT
OUT_DIR = REPO_ROOT / "data" / "chains"
HTML_NAME = "chains_watchlist.html"
JSON_NAME = "chains_data.json"

CAVEAT_TEXT = (
    "Curated counts are what a person checked; detected counts come from open "
    "data and are a FLOOR — franchisee filings, DOHMH lag, and brands no "
    "city dataset can see all push them down. Where the two disagree, both are "
    "shown. See docs/chains-process.md.")


def _clean(value):
    """JSON-safe scalar: NaN and pandas Timestamp become None/str, everything
    else passes through. Never a dash string -- that is a JS presentation
    choice, not a fact about the data."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)[:10] if hasattr(value, "isoformat") else str(value)


def _pipe_value(pipe_row) -> str | None:
    cell = ren._pipe_cell(pipe_row)
    return None if cell == "—" else cell


def _reject_snippet(brand_key: str) -> str:
    return f'loci chains reject {brand_key} --reason ""'


def _is_incumbent(row: dict) -> bool:
    return (row.get("sales_role") or "") == "incumbent"


def _ranked(rows: list[dict], keyfn) -> list[dict]:
    """Sort by `keyfn` descending, then push incumbents/co-op banners to the
    bottom of their own sub-ranking rather than mixing them in by number --
    an incumbent with a huge detected count must not out-rank a real
    prospect (D113's `sales_role` table)."""
    primary = [r for r in rows if not _is_incumbent(r)]
    incumbents = [r for r in rows if _is_incumbent(r)]
    primary.sort(key=keyfn, reverse=True)
    incumbents.sort(key=keyfn, reverse=True)
    return primary + incumbents


def _hand_key(r: dict):
    n = r.get("net_new_12m")
    return (0 if n is None else 1, n or 0)


def _auto_key_factory(snap: dict[str, dict]):
    def key(r: dict):
        bk = r.get("brand_key") or ""
        d = snap.get(bk, {})
        return (d.get("locations_new_12m") or 0, d.get("locations_total") or 0)
    return key


def build_data(con, *, doc: dict | None = None, month: str | None = None,
               today: dt.date | None = None) -> dict:
    """The exact payload `chains_data.json` serializes. Pure function of
    `render.assemble()`'s output -- no query of its own."""
    today = today or dt.date.today()
    asm = ren.assemble(con, doc=doc, month=month)
    snap, pipe = asm["snap"], asm["pipe"]

    watchlist_out = []
    for r in _ranked(asm["hand"], _hand_key):
        bk = r.get("brand_key") or ""
        d = snap.get(bk, {})
        watchlist_out.append({
            "brand_key": bk,
            "brand": _clean(r.get("brand")),
            "category": _clean(r.get("category")),
            "loci_category": _clean(r.get("loci_category")),
            "net_new_12m": _clean(r.get("net_new_12m")),
            "nyc_locations_now": _clean(r.get("nyc_locations_now")),
            "detected_total": _clean(d.get("locations_total")),
            "detected_new_12m": _clean(d.get("locations_new_12m")),
            "pipeline": _pipe_value(pipe.get(bk)),
            "confidence": _clean(r.get("confidence")),
            "last_verified": _clean(r.get("last_verified")),
            "sales_role": _clean(r.get("sales_role")),
        })

    auto_out = []
    for r in _ranked(asm["auto"], _auto_key_factory(snap)):
        bk = r.get("brand_key") or ""
        d = snap.get(bk, {})
        auto_out.append({
            "brand_key": bk,
            "brand": _clean(r.get("brand")),
            "loci_category": _clean(r.get("loci_category")),
            "detected_total": _clean(d.get("locations_total")),
            "detected_new_12m": _clean(d.get("locations_new_12m")),
            "pipeline": _pipe_value(pipe.get(bk)),
            "sales_role": _clean(r.get("sales_role")),
            "admission_reason": _clean(r.get("admission_reason")),
            "decided_on": _clean(r.get("decided_on")),
            "reject_snippet": _reject_snippet(bk),
        })

    n_hand, n_auto, n_rejected = len(asm["hand"]), len(asm["auto"]), len(asm["rejected"])
    return {
        "generated": today.isoformat(),
        "detect_snapshot": asm["month"],
        "counts": {
            "hand_vetted": n_hand,
            "auto_admitted": n_auto,
            "rejected": n_rejected,
            "total": len(asm["rows"]),
        },
        "watchlist": watchlist_out,
        "auto_admitted": auto_out,
        "footer": {"caveat": CAVEAT_TEXT, "rejected_count": n_rejected},
    }


def render_html(con, *, doc: dict | None = None, month: str | None = None,
                 today: dt.date | None = None) -> tuple[str, str]:
    """Returns (html_text, json_text). `html_text` is the constant page
    shell; `json_text` is the one part that changes every snapshot."""
    data = build_data(con, doc=doc, month=month, today=today)
    return PAGE_HTML, json_mod.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write(html_text: str, json_text: str,
          out_dir: pathlib.Path | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    target_dir = out_dir or OUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    html_path = target_dir / HTML_NAME
    json_path = target_dir / JSON_NAME
    html_path.write_text(html_text)
    json_path.write_text(json_text)
    return html_path, json_path


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NYC Chains Watchlist</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {
    --bg: #eef1ef;
    --surface: #ffffff;
    --surface-2: #f5f7f6;
    --surface-3: #eaf1ee;
    --border: #d6dbd8;
    --border-strong: #b7c0bc;
    --text: #1a2220;
    --text-muted: #5c6864;
    --text-faint: #8b9691;
    --accent: #1f6f63;
    --accent-strong: #14544a;
    --accent-soft: #dbeeea;
    --good: #3f7d3a;
    --warn: #93630c;
    --warn-soft: #f7ecd4;
    --bad: #a33d2e;
    --radius-sm: 5px;
    --radius-md: 9px;
    --font-display: 'Source Serif 4', Georgia, 'Times New Roman', serif;
    --font-body: 'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif;
    --font-mono: 'IBM Plex Mono', 'SFMono-Regular', Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #101a17; --surface: #17221f; --surface-2: #1c2926; --surface-3: #22322d;
      --border: #2c3a36; --border-strong: #3d4d47; --text: #eaf1ef; --text-muted: #a8b6b1;
      --text-faint: #728179; --accent: #56b8a7; --accent-strong: #86d0c2;
      --accent-soft: #1d3a35; --good: #82c67c; --warn: #e0b458; --warn-soft: #362c16;
      --bad: #e08d7b;
    }
  }
  :root[data-theme="dark"] {
    --bg: #101a17; --surface: #17221f; --surface-2: #1c2926; --surface-3: #22322d;
    --border: #2c3a36; --border-strong: #3d4d47; --text: #eaf1ef; --text-muted: #a8b6b1;
    --text-faint: #728179; --accent: #56b8a7; --accent-strong: #86d0c2;
    --accent-soft: #1d3a35; --good: #82c67c; --warn: #e0b458; --warn-soft: #362c16;
    --bad: #e08d7b;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text); font-family: var(--font-body);
    font-size: 14px; line-height: 1.5; padding-inline: 20px; padding-block: 28px 56px;
    max-width: 1220px; margin-inline: auto;
  }
  a { color: var(--accent-strong); }
  h1, h2 { font-family: var(--font-display); font-weight: 700; margin: 0; }
  .tnum { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
  header.page-header {
    display: flex; flex-direction: column; gap: 10px; padding-block-end: 20px;
    border-bottom: 1px solid var(--border); margin-block-end: 22px;
  }
  .kicker {
    font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.09em;
    text-transform: uppercase; color: var(--accent-strong); font-weight: 500;
  }
  h1 { font-size: 28px; letter-spacing: -0.01em; }
  .purpose { max-width: 68ch; color: var(--text-muted); font-size: 14.5px; margin: 0; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 22px; margin-block-start: 6px; }
  .meta-stat { display: flex; flex-direction: column; gap: 1px; }
  .meta-num { font-family: var(--font-mono); font-size: 17px; font-weight: 500; color: var(--text); }
  .meta-label { font-size: 11.5px; color: var(--text-faint); }
  .caveat {
    background: var(--warn-soft); border: 1px solid var(--warn); border-left: 3px solid var(--warn);
    border-radius: var(--radius-sm); padding: 12px 14px; font-size: 13px; color: var(--text);
    margin-block-end: 22px;
  }
  .caveat strong { color: var(--warn); }
  section { margin-block-end: 30px; }
  .section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-block-end: 6px; flex-wrap: wrap; }
  .section-head h2 { font-size: 18px; }
  .section-note { font-size: 12.5px; color: var(--text-faint); max-width: 72ch; margin: 0 0 10px; }
  .controls {
    display: flex; flex-wrap: wrap; gap: 12px 18px; align-items: flex-end; background: var(--surface);
    border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px 16px; margin-block-end: 18px;
  }
  .control-group { display: flex; flex-direction: column; gap: 6px; }
  .control-group label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-faint); }
  #searchInput {
    font-family: var(--font-body); font-size: 13.5px; background: var(--surface-2);
    border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 7px 10px;
    color: var(--text); min-width: 280px;
  }
  #searchInput:focus { border-color: var(--accent); outline: none; }
  .table-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
  table { border-collapse: collapse; width: 100%; min-width: 900px; font-size: 12.6px; }
  thead th {
    position: sticky; top: 0; background: var(--surface-2); text-align: left; font-size: 10.6px;
    text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-faint); font-weight: 500;
    padding: 9px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; cursor: pointer;
    user-select: none;
  }
  thead th:hover { color: var(--accent-strong); }
  thead th .arrow { font-size: 9px; margin-inline-start: 3px; color: var(--accent); }
  th.num, td.num { text-align: right; }
  tbody td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; color: var(--text); }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr.incumbent-row { background: var(--surface-2); }
  td.num, .mono { font-family: var(--font-mono); }
  .brand-name { font-weight: 600; }
  .pill {
    display: inline-block; background: var(--accent-soft); color: var(--accent-strong);
    border-radius: 999px; padding: 2px 8px; font-size: 11px; white-space: nowrap;
  }
  .pill.incumbent { background: var(--surface-3); color: var(--text-faint); }
  .muted { color: var(--text-faint); }
  .snippet {
    display: flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 11.4px;
    background: var(--surface-3); border: 1px solid var(--border); border-radius: var(--radius-sm);
    padding: 4px 7px; white-space: nowrap;
  }
  .snippet button {
    font-family: var(--font-body); font-size: 10.5px; border: 1px solid var(--border-strong);
    background: var(--surface); color: var(--text-muted); border-radius: 999px; padding: 2px 7px;
    cursor: pointer;
  }
  .snippet button:hover { color: var(--accent-strong); border-color: var(--accent); }
  .table-note { font-size: 12px; color: var(--text-faint); margin: 8px 2px 0; }
  footer {
    margin-block-start: 36px; padding-block-start: 16px; border-top: 1px solid var(--border);
    font-size: 12px; color: var(--text-faint); display: flex; flex-direction: column; gap: 6px;
  }
  @media (max-width: 640px) {
    body { padding-inline: 16px; }
    h1 { font-size: 22px; }
    .controls { flex-direction: column; align-items: stretch; }
    #searchInput { min-width: 0; }
  }
</style>
</head>
<body>

<header class="page-header">
  <div class="kicker">Loci &middot; site-selection intelligence</div>
  <h1>NYC Chains Watchlist</h1>
  <p class="purpose">Brands actively growing their NYC footprint: companies to sell a
    site-selection product to, and later a demand signal for where retail traffic is
    headed next. Hand-vetted rows are separated from what the monthly job admitted
    unattended &mdash; nobody has looked at the second group yet.</p>
  <div class="meta-row">
    <div class="meta-stat"><span class="meta-num tnum" id="statGenerated">&nbsp;</span><span class="meta-label">generated</span></div>
    <div class="meta-stat"><span class="meta-num tnum" id="statSnapshot">&nbsp;</span><span class="meta-label">detect snapshot</span></div>
    <div class="meta-stat"><span class="meta-num tnum" id="statHand">&nbsp;</span><span class="meta-label">hand-vetted</span></div>
    <div class="meta-stat"><span class="meta-num tnum" id="statAuto">&nbsp;</span><span class="meta-label">auto-admitted</span></div>
    <div class="meta-stat"><span class="meta-num tnum" id="statRejected">&nbsp;</span><span class="meta-label">rejected</span></div>
  </div>
</header>

<div class="caveat">
  <strong>Read the caveats before quoting a number.</strong>
  <p id="caveatText" style="margin:4px 0 0;color:var(--text-muted);"></p>
</div>

<section class="controls" aria-label="Filter">
  <div class="control-group">
    <label for="searchInput">Filter (brand / category / sales role)</label>
    <input id="searchInput" type="text" placeholder="e.g. grocery, prospect, Dunkin&hellip;" autocomplete="off">
  </div>
</section>

<section aria-label="Watchlist">
  <div class="section-head"><h2>Watchlist</h2></div>
  <p class="section-note">Hand-vetted rows, ranked by net new locations in 12 months
    (curated). Incumbents and co-op banners &mdash; off the broker lead list &mdash;
    sort to the bottom. Click a column heading to sort.</p>
  <div class="table-scroll">
    <table id="watchlistTable">
      <thead>
        <tr>
          <th data-key="brand" data-type="text">Brand</th>
          <th data-key="category" data-type="text">Category</th>
          <th data-key="loci_category" data-type="text">loci_category</th>
          <th class="num" data-key="net_new_12m" data-type="num">Net new 12m (curated)</th>
          <th class="num" data-key="nyc_locations_now" data-type="num">NYC now (curated)</th>
          <th class="num" data-key="detected_total" data-type="num">Detected total</th>
          <th class="num" data-key="detected_new_12m" data-type="num">Detected new 12m</th>
          <th data-key="pipeline" data-type="text">Pipeline (gov filings)</th>
          <th data-key="confidence" data-type="text">Confidence</th>
          <th data-key="last_verified" data-type="text">Last verified</th>
          <th data-key="sales_role" data-type="text">Sales role</th>
        </tr>
      </thead>
      <tbody id="watchlistBody"></tbody>
    </table>
  </div>
  <p class="table-note" id="watchlistCount"></p>
</section>

<section aria-label="Auto-admitted this snapshot">
  <div class="section-head"><h2>Auto-admitted this snapshot (nobody has looked yet)</h2></div>
  <p class="section-note">Admitted by <code>loci chains auto-admit</code> because the brand
    cleared the D109 candidate predicate and no exclusion rule fired. <code>NYC now</code>
    is deliberately absent here &mdash; only a detect count exists, and that count is a
    floor off open data. Reject a row with the snippet in its last column; promote one with
    <code>loci chains admit &lt;brand_key&gt; --reason "..."</code>.</p>
  <div class="table-scroll">
    <table id="autoTable">
      <thead>
        <tr>
          <th data-key="brand" data-type="text">Brand</th>
          <th data-key="loci_category" data-type="text">loci_category</th>
          <th class="num" data-key="detected_total" data-type="num">Detected total</th>
          <th class="num" data-key="detected_new_12m" data-type="num">Detected new 12m</th>
          <th data-key="pipeline" data-type="text">Pipeline (gov filings)</th>
          <th data-key="sales_role" data-type="text">Sales role</th>
          <th data-key="admission_reason" data-type="text">Admitted because</th>
          <th data-key="decided_on" data-type="text">Decided on</th>
          <th data-type="none">Reject</th>
        </tr>
      </thead>
      <tbody id="autoBody"></tbody>
    </table>
  </div>
  <p class="table-note" id="autoCount"></p>
</section>

<footer>
  <span id="footerCaveat"></span>
  <span id="footerRejected"></span>
  <span>Source: <code>src/loci/chains/watchlist.yaml</code> (curated) &amp;
    <code>chains.brand_snapshot</code> (detected, DuckDB). Regenerate with
    <code>loci chains render --html</code> (also part of <code>loci chains refresh</code>).
    Serve with <code>loci chains serve</code>.</span>
</footer>

<script>
(function () {
  "use strict";

  var DASH = "—";

  function fmt(v) {
    if (v === null || v === undefined || v === "") return DASH;
    return String(v);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function matches(row, q) {
    if (!q) return true;
    var hay = [row.brand, row.category, row.loci_category, row.sales_role]
      .map(function (x) { return (x || "").toString().toLowerCase(); })
      .join(" ");
    return hay.indexOf(q) !== -1;
  }

  function sortRows(rows, sortState) {
    if (!sortState || !sortState.key) return rows;
    var key = sortState.key, dir = sortState.dir, type = sortState.type;
    var copy = rows.slice();
    copy.sort(function (a, b) {
      var av = a[key], bv = b[key];
      var cmp;
      if (type === "num") {
        var an = (av === null || av === undefined) ? -Infinity : Number(av);
        var bn = (bv === null || bv === undefined) ? -Infinity : Number(bv);
        cmp = an - bn;
      } else {
        var as = (av === null || av === undefined) ? "" : String(av).toLowerCase();
        var bs = (bv === null || bv === undefined) ? "" : String(bv).toLowerCase();
        cmp = as < bs ? -1 : as > bs ? 1 : 0;
      }
      return dir === "asc" ? cmp : -cmp;
    });
    return copy;
  }

  function wireSort(tableId, getRows, render, sortState) {
    var table = document.getElementById(tableId);
    var heads = table.querySelectorAll("thead th[data-key]");
    heads.forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.getAttribute("data-key");
        var type = th.getAttribute("data-type");
        if (sortState.key === key) {
          sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
        } else {
          sortState.key = key; sortState.type = type; sortState.dir = "desc";
        }
        heads.forEach(function (h) { h.querySelector(".arrow") && h.querySelector(".arrow").remove(); });
        var arrow = document.createElement("span");
        arrow.className = "arrow";
        arrow.textContent = sortState.dir === "asc" ? "▲" : "▼";
        th.appendChild(arrow);
        render(getRows());
      });
    });
  }

  function pillCell(role) {
    if (!role) return '<span class="muted">' + DASH + "</span>";
    var cls = role === "incumbent" ? "pill incumbent" : "pill";
    return '<span class="' + cls + '">' + escapeHtml(role) + "</span>";
  }

  function init(data) {
    document.getElementById("statGenerated").textContent = fmt(data.generated);
    document.getElementById("statSnapshot").textContent = fmt(data.detect_snapshot);
    document.getElementById("statHand").textContent = data.counts.hand_vetted;
    document.getElementById("statAuto").textContent = data.counts.auto_admitted;
    document.getElementById("statRejected").textContent = data.counts.rejected;
    document.getElementById("caveatText").textContent = data.footer.caveat;
    document.getElementById("footerCaveat").textContent = data.footer.caveat;
    document.getElementById("footerRejected").textContent =
      data.footer.rejected_count + " rejected row"
      + (data.footer.rejected_count === 1 ? "" : "s")
      + " omitted from both tables above and kept in watchlist.yaml so the same "
      + "brands are not re-surfaced every month.";

    var watchlistSort = { key: null, dir: "desc", type: "num" };
    var autoSort = { key: null, dir: "desc", type: "num" };
    var query = "";

    function renderWatchlist() {
      var rows = data.watchlist.filter(function (r) { return matches(r, query); });
      rows = sortRows(rows, watchlistSort);
      var body = document.getElementById("watchlistBody");
      body.innerHTML = rows.map(function (r) {
        var cls = r.sales_role === "incumbent" ? ' class="incumbent-row"' : "";
        return "<tr" + cls + ">"
          + '<td class="brand-name">' + escapeHtml(fmt(r.brand)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.category)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.loci_category)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.net_new_12m)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.nyc_locations_now)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.detected_total)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.detected_new_12m)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.pipeline)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.confidence)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.last_verified)) + "</td>"
          + "<td>" + pillCell(r.sales_role) + "</td>"
          + "</tr>";
      }).join("");
      document.getElementById("watchlistCount").textContent =
        rows.length + " of " + data.watchlist.length + " watchlist rows shown.";
    }

    function renderAuto() {
      var rows = data.auto_admitted.filter(function (r) { return matches(r, query); });
      rows = sortRows(rows, autoSort);
      var body = document.getElementById("autoBody");
      body.innerHTML = rows.map(function (r) {
        var cls = r.sales_role === "incumbent" ? ' class="incumbent-row"' : "";
        return "<tr" + cls + ">"
          + '<td class="brand-name">' + escapeHtml(fmt(r.brand)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.loci_category)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.detected_total)) + "</td>"
          + '<td class="num tnum">' + escapeHtml(fmt(r.detected_new_12m)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.pipeline)) + "</td>"
          + "<td>" + pillCell(r.sales_role) + "</td>"
          + "<td>" + escapeHtml(fmt(r.admission_reason)) + "</td>"
          + "<td>" + escapeHtml(fmt(r.decided_on)) + "</td>"
          + '<td><span class="snippet"><code>' + escapeHtml(r.reject_snippet)
          + '</code><button type="button" data-copy="' + escapeHtml(r.reject_snippet)
          + '">copy</button></span></td>'
          + "</tr>";
      }).join("");
      document.getElementById("autoCount").textContent =
        rows.length + " of " + data.auto_admitted.length + " auto-admitted rows shown.";
      body.querySelectorAll("button[data-copy]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var text = btn.getAttribute("data-copy");
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).catch(function () {});
          }
          var old = btn.textContent;
          btn.textContent = "copied";
          setTimeout(function () { btn.textContent = old; }, 1200);
        });
      });
    }

    wireSort("watchlistTable", function () { return data.watchlist; }, renderWatchlist, watchlistSort);
    wireSort("autoTable", function () { return data.auto_admitted; }, renderAuto, autoSort);

    document.getElementById("searchInput").addEventListener("input", function (e) {
      query = e.target.value.trim().toLowerCase();
      renderWatchlist();
      renderAuto();
    });

    renderWatchlist();
    renderAuto();
  }

  fetch("chains_data.json")
    .then(function (r) { return r.json(); })
    .then(init)
    .catch(function (err) {
      document.body.insertAdjacentHTML(
        "afterbegin",
        '<p style="color:#a33d2e;">Could not load chains_data.json: '
        + escapeHtml(err) + ". Serve this directory (loci chains serve) rather than "
        + "opening the file directly.</p>");
    });
})();
</script>
</body>
</html>
"""
