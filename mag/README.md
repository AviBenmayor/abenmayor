# MAG Analytics Lead — Case Study Submission

**Avi Benmayor**

**Live dashboard: https://mag-desk-pnl-production.up.railway.app** (hosted on
Railway). Three views — Desk P&L, Hold, and Cash at Exchange — all running on
one unified position model.

## How to navigate this folder

| What | Where |
|---|---|
| **Write-up** — Parts 1–4 and 6, all judgment calls and numbers, plus how AI was used | [`WRITEUP.md`](WRITEUP.md) |
| **Unified position model (q)** — Part 1 | [`pos_model.q`](pos_model.q) |
| **Unified position model (pandas port)** — same logic, powers the dashboards | [`dashboard/model.py`](dashboard/model.py) |
| **Deck (Part 5)** — live on Gamma | [MAG Desk Analytics](https://gamma.app/docs/MAG-Desk-Analytics--6r9h3se2qni1wew) |
| **Deck screenshots** | [`deck_assets/`](deck_assets/) |
| **Source data** — loaded by `pos_model.q` | `fills.csv`, `marks.csv`, `quotes.csv`, `venue_cash.csv` |
| **Model output** — the unified `pos` table materialized to CSV, for inspection without running q | [`pos.csv`](pos.csv) |

## The dashboard

[`dashboard/webapp/`](dashboard/webapp/) is the build that is **deployed to
Railway**: a static single-page app (Express serving `public/`) whose data is
baked to JSON by `webapp/scripts/export_data.py`, which imports
[`dashboard/model.py`](dashboard/model.py) — so the deployed numbers are
computed by the same position-model code, just served statically.

## Running things locally

```bash
# Part 1 model in q (loads the CSVs in this directory)
q pos_model.q

# Dashboard
cd dashboard/webapp && npm install && npm start   # http://localhost:3000
```

## Map to the case-study parts

1. **Unified position model** — `pos_model.q` (+ `dashboard/model.py`), Part 1 of `WRITEUP.md`
2. **Desk P&L view** — dashboard home page, Part 2 of `WRITEUP.md`
3. **Hold view** — dashboard Hold page, Part 3 of `WRITEUP.md`
4. **Cash-at-exchange view** — dashboard Cash page, Part 4 of `WRITEUP.md`
5. **Deck** — [MAG Desk Analytics on Gamma](https://gamma.app/docs/MAG-Desk-Analytics--6r9h3se2qni1wew)
6. **Plain-English summary** — Part 6 of `WRITEUP.md`
