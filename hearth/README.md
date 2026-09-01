# Hearth GTM Engineer exercise — Avi Benmayor

This is the whole submission. **Start with [`MEMO.md`](MEMO.md)** — it's one page, and
everything else here backs it up.

| | |
|---|---|
| **The memo** | [`MEMO.md`](MEMO.md) — one page, the five required answers |
| **The dashboard** | **https://dashboard-production-d33d.up.railway.app** — the rep queue and the evidence behind it, live |
| **The score** | [`output/submission.csv`](output/submission.csv) — 4,255 leads, `lead_id, score, tier` |
| **The offline tool** | [`tool/lead_queue.html`](tool/lead_queue.html) — ranked queue → per-lead brief. One file, any browser, no install, no network |
| **Questions for you** | [`QUESTIONS.md`](QUESTIONS.md) |
| **Data notes** | [`CONTEXT.md`](CONTEXT.md) — profile, joins, and every quirk I hit |

## The offline tool

`tool/lead_queue.html` — one 57 KB file, no install, no network, nothing to break on someone
else's machine. Two views:

- **The queue.** Drop a leads CSV; leads come back ranked with a tier and one instruction each.
  Set "calls I can make today" and the cutoff line moves with it.
- **The brief.** Click any lead for a call-prep one-pager: who they are, **what has already been
  done to them**, what to expect on the call, everything we know at intake, and why it ranked where
  it did. Printable.

Drop `activities.csv`, `call_extractions.csv` or `call_objections.csv` alongside the leads file and
every brief gains a real timeline — calls, dispositions, who was reached, objections raised and
whether they resolved. **Files are identified by their columns, not their names**, so order and
filename don't matter. If the leads file carries `converted_contact_id`, post-conversion activity
hanging off the contact id is merged back too.

A lead with no history says so plainly rather than showing an empty box — which is the *normal*
state at the routing moment, and the reason the score has to work from intake fields alone.

**The "why" leads with observed win rates, not model coefficients.** A coefficient is conditional:
`High Value` carries a negative weight once revenue band is known, which is correct arithmetic and
reads as broken to a rep who knows High Value is their best segment. So the brief shows what
actually happened to leads like this one — *"35.3% of these won, 1.8× base"* — and keeps the
conditional weights behind a disclosure that explains why the two disagree.

## The dashboard

Credentials came with this repo's submission email. It is HTTP Basic and **fails closed** — an unset
password is treated as a misconfiguration, not as "open to the world" — and `robots.txt` disallows
everything.

Two audiences, deliberately:

| | |
|---|---|
| `/` | **the rep view.** A ranked queue by day, and a per-lead card that says what to do, why, and what objections to expect. The "why" is observed segment win rates, not model coefficients — a conditional coefficient is correct arithmetic and indefensible on a sales floor, so both views ship and the card explains the difference. |
| `/score` | **paste or upload any CSV** of leads I have never seen and get tiers back, or `POST /api/score` for the same thing as JSON. Partial rows are fine; anything filled in or unseen is reported rather than silently absorbed. |
| `/speed` | memo Q3 — the raw speed-to-lead effect, and how much of it survives controls. |
| `/cutoff` | memo Q4 — the capacity derivation, with the tier shares and the floor's throughput as **editable inputs**, so you can move the line and watch the economics move with it. |
| `/model` | the model card: target choice, the feature ablation, out-of-time and CV metrics, calibration, the distribution shift, and every data quirk I would want to know before trusting the ranking. |

`GET /submission.csv` from the dashboard returns **the same bytes** as `output/submission.csv`.

## One model, four places

The thing most likely to go wrong in a submission like this is two artifacts quietly disagreeing —
and for a while these did, with the dashboard serving a wider feature set the memo argues against.
It now can't:

- [`src/features.py`](src/features.py) holds the feature set and the pipeline. Nothing redefines them.
- [`src/export_model.py`](src/export_model.py) fits it once and collapses it into `output/model.json`,
  a per-value coefficient lookup. For a linear model on one-hot features that is exact, not an
  approximation. It is the **only** script that writes `output/submission.csv`.
- [`src/scorer.py`](src/scorer.py) scores from that JSON in pure numpy. The batch, the dashboard's
  queue and the live `/api/score` endpoint all go through it. Nothing on the serving path is a
  pickle, so nothing is version-coupled to the scikit-learn that fitted the model.
- [`src/test_parity.js`](src/test_parity.js) runs the JavaScript from the built HTML tool against
  Python's scores. Current agreement: **exact — 0.0** across 500 rows. It became exact when the
  calibration layer came out: with no log/exp round-trip left, both scorers evaluate the same sum. It also throws 14 malformed CSVs
  at the parser and scores 50,000 rows to check it doesn't hang.

Two assertions enforce it on every build: `score_leads.py` fails if its own fit drifts from
`model.json`, and `capacity_and_tiers.py` fails if a single one of the 4,255 tiers differs from the
file being submitted. That check earned its keep — 14 leads sit on exactly the tier-A threshold, and
a 1e-13 disagreement between two scorers was the difference between routing them to "call now" and
routing them to "work".

## Reproducing

```bash
python3 -m venv .venv && .venv/bin/pip install pandas scikit-learn scipy pyarrow joblib
PYTHONPATH=src .venv/bin/python src/run_all.py   # raw pack -> submission.csv, tool, dashboard data
node src/test_parity.js                          # verifies the browser matches Python
```

`requirements.txt` is the **serving** dependency set — deliberately smaller, no scikit-learn.

The analysis behind each memo section runs standalone:

```bash
PYTHONPATH=src .venv/bin/python src/speed_to_lead.py     # Q3, part 1: raw effect and controls
PYTHONPATH=src .venv/bin/python src/speed_to_lead_2.py   # Q3, part 2: natural experiment, regression
PYTHONPATH=src .venv/bin/python src/target_choice.py     # Q1: P(win) vs expected $ vs P(win this month)
PYTHONPATH=src .venv/bin/python src/model_final.py       # Q2: the ablation that chose the feature set
PYTHONPATH=src .venv/bin/python src/capacity.py          # Q4: capacity, cutoff, honest lift
PYTHONPATH=src .venv/bin/python src/data_quirks.py       # close-date artifact, cohort trend, Bad Data
PYTHONPATH=src .venv/bin/python src/objections.py        # rebuttal effectiveness -> coaching layer
```

## Headline numbers

| | |
|---|---|
| Target | expected dollars, P(win) × E[amount \| win] |
| Model | logistic regression, 3 intake fields, no calibration layer — 15 parameters |
| Trained on | the 4,574 leads a rep actually worked, not all 5,507 |
| Validation | out-of-time: train Oct–Dec 2025, score Jan–Feb 2026 |
| AUC | **0.724** vs 0.645 for the legacy CRM score (0.760 available, deliberately not taken — see memo) |
| Lift, top 20% | **2.06×** vs 1.60× for legacy |
| At the capacity cutoff (top 30%) | **221 wins vs 193** for legacy on real outcomes (**+15%**) |
| Derived capacity | ~25 workable leads/business day against 65 arriving |

## A note on the data

The raw pack — the CSVs and transcripts you sent — is not in this repo, and neither is the
historical bundle the dashboard serves, since that's the same data re-serialised. Everything I
built from it is here, including the scored file.

The deployed image is built from the local working copy and carries **three** files — the scoring
window's intake columns, `model.json`, and precomputed aggregates. `leads_history`, `activities`, the
call tables and the transcripts never enter the build context; see `.railwayignore` and `.dockerignore`.
