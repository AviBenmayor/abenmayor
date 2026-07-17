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
| **Deck (Part 5, in progress)** — Gamma source | [`part5_deck_gamma.md`](part5_deck_gamma.md) |
| **Deck screenshots** | [`deck_assets/`](deck_assets/) |
| **Source data** — loaded by `pos_model.q` | `fills.csv`, `marks.csv`, `quotes.csv`, `venue_cash.csv` |
| **Model output** — the unified `pos` table materialized to CSV, for inspection without running q | [`pos.csv`](pos.csv) |

## The dashboard, in two layers

- [`dashboard/webapp/`](dashboard/webapp/) — the build that is **deployed to
  Railway**: a static single-page app (Express serving `public/`) whose data is
  baked to JSON by `webapp/scripts/export_data.py`, which imports
  `dashboard/model.py` — so the deployed numbers are computed by the same model
  code, just served statically.
- [`dashboard/`](dashboard/) — the original **Streamlit build** where the model
  and every number were first validated (`Desk_P&L.py` plus `pages/` for the
  Hold and Cash views, optional login gate in `auth.py`). Kept because it's the
  reference implementation the write-up describes.

## Running things locally

```bash
# Part 1 model in q (loads the CSVs in this directory)
q pos_model.q

# Streamlit build
cd dashboard && pip install -r requirements.txt && streamlit run "Desk_P&L.py"

# Deployed webapp build
cd dashboard/webapp && npm install && npm start   # http://localhost:3000
```

## Map to the case-study parts

1. **Unified position model** — `pos_model.q` (+ `dashboard/model.py`), Part 1 of `WRITEUP.md`
2. **Desk P&L view** — dashboard home page, Part 2 of `WRITEUP.md`
3. **Hold view** — dashboard Hold page, Part 3 of `WRITEUP.md`
4. **Cash-at-exchange view** — dashboard Cash page, Part 4 of `WRITEUP.md`
5. **Deck** — `part5_deck_gamma.md` (in progress)
6. **Plain-English summary** — Part 6 of `WRITEUP.md`
