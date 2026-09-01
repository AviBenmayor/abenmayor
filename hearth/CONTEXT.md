# CONTEXT — Hearth GTM Engineer Exercise

Orientation doc for a take-home + live session for **Hearth** (https://gethearth.com).
The assignment itself is in [`brief.md`](brief.md) — this file is the working context around it:
what the company does, what's actually in the data, and what's already been checked.

---

## 1. The company

Hearth sells software to **residential home improvement contractors** — roofing, HVAC, plumbing,
electrical, remodeling, painting, landscaping, fencing/decks. The wedge is that big-ticket jobs
stall at the estimate stage because homeowners can't pay several thousand dollars up front.

| Module | What it does |
|---|---|
| **Customer financing** | Homeowner pre-qualifies from a contractor-sent link; contractor carries no credit risk |
| **HELOC** | Home-equity option for larger projects |
| **Quoting & contracts** | Estimates from phone/tablet, digital approval |
| **Invoicing & Hearth Pay** | Invoice from the approved quote, card/ACH collection |
| **Harper AI** | AI receptionist — answers calls 24/7, chases financing applications |
| **Concierge** | Humans who work tricky financing deals for the contractor |
| **Priority support** | Dedicated line instead of a queue |

Public claims: 30,000+ pros, $1B+ funded jobs, +17% estimate close rate. They run **Salesforce and
HubSpot**. Median won deal here is ~$1,540 — this is high-volume, low-ACV SaaS, not enterprise.

## 2. The ask

> *"Who should reps work, how hard, and how would we know you were right?"*

Paid inbound arrives, reps can't work it all, so attention is allocated near-randomly today. There
is a legacy rules-based score in the CRM that nobody trusts or uses. Three required deliverables:

1. **A score** — every lead in `leads_to_score.csv`, as `lead_id, score, tier`. Any monotone number.
   Target is my choice (P(win) / expected dollars / P(win this month)) **and must be defended** —
   they rank and route differently. They hold the outcomes and will benchmark against an undisclosed
   naive baseline, but explicitly say *most of what they're reading is the defense, not the AUC*.
2. **Something a rep opens** — a working tool that takes a lead and says what to do with it. Must run
   on unseen records. **Demoed live to someone role-playing a rep who does not want it.** They expect
   it to break; they're grading diagnosis and repair under pressure.
3. **A one-page memo** — target + why; findings incl. what looks wrong and what the data *cannot*
   answer; **the speed-to-lead question** (does responding faster predict higher win rate — show work,
   say whether you'd act on it); who gets worked first, where the cutoff sits, what happens below it;
   what ships Monday and how you'd know in 30 days. Appendices don't count against the page.

**No deck.** They read the memo beforehand. Session is ~75 min: demo, then work the problem live
while they change the spec.

Deliberate gaps: **no cost or capacity data** (state and defend an assumption, or ask) and **no data
dictionary**. "Some things you need are not in this pack. Email and ask… what you choose to ask about
is part of what we are reading." → **Asking good questions is scored.** Contact: alexi.bennink@gethearth.com.

**Data handling:** confidential, don't share or post, delete when the process concludes. Approach is
portfolio-safe; the data is not.

## 3. Repo layout

```
hearth/
├── CONTEXT.md          # this file
├── brief.md            # the assignment as sent
├── data/               # 7 CSVs (~13 MB)
└── transcripts/        # 25 synthetic call transcripts
```

## 4. The data

Two windows of the same funnel, anonymized, dollar amounts transformed (segment-level aggregates and
rankings preserved). Outcomes are as of **early Aug 2026**.

### Train — Oct 6 2025 → Feb 28 2026

| File | Rows | Grain | Key columns |
|---|---|---|---|
| `leads_history.csv` | 5,507 | lead | **cols 1–12 = intake** (known at arrival); 13–19 (`status`, `owner_id`, `mql_at`, `sal_at`, `converted_at`, `converted_contact_id`, `converted_opp_id`) exist **only because a human worked it** |
| `activities.csv` | 144,966 | activity | `who_id`, `owner_id`, `created_at`, `type`, `subtype`, `call_disposition`, `call_duration_seconds`, `status` |
| `opps.csv` | 954 | opportunity | `opp_id`, `created_at`, `close_date`, `stage`, `is_won`, `amount`, `won_arr`, `owner_id`, `deal_type` |
| `call_extractions.csv` | 8,171 | call | LLM-typed: `call_type`, `reached`, `outcome`, 7 product-mention flags, `n_pain_points`, `n_competitor_mentions`, `n_rep_commitments`, `seat_discussion`, `heard_about_us` |
| `call_objections.csv` | 8,275 | objection | `type`, `product`, `rebuttal_attempted`, `rebuttal_type`, `resolved` |
| `transcripts/*.txt` | 25 | call | synthetic, carries `call_ref` + `lead_id` |

### Score — Mar 1 → May 31 2026

`leads_to_score.csv` — 4,255 leads, **intake columns only** (the 12 that exist the second the lead
hits the CRM). No status, owner, activity, or outcome. **Zero lead_id overlap with the train window.**

`submission_template.csv` — `lead_id, score, tier`.

### The 12 intake columns — the entire feature surface

`lead_id`, `created_at`, `channel`, `campaign_ref`, `utm_medium`, `contractor_annual_revenue`,
`icp_category`, `state`, `zip3`, `time_zone`, `enrichment_status`, `legacy_score`

That's it. Everything else in the pack is for *learning* what predicts, not for *scoring*.

## 5. Verified joins

All confirmed clean — zero unmatched keys on every edge below.

```
leads_history.lead_id ──┬── activities.who_id            (L-prefixed: 4,495 leads)
                        ├── call_extractions.lead_id     (2,682 leads)
                        └── call_objections.lead_id
        │
        ├── converted_contact_id ── activities.who_id    (C-prefixed: 980 contacts)
        └── converted_opp_id ────── opps.opp_id          (954/954)

call_extractions.call_ref ── call_objections.call_ref    (4,491 distinct refs)
                          └── transcripts header         (25/25)
```

**The one real trap: `activities.who_id` is bimodal.** Pre-conversion activity is attached to the
**lead** (`L…`, 4,495 distinct); post-conversion activity is attached to the **contact**
(`C…`, 980 distinct). A converted lead's timeline is split across two IDs and must be unioned via
`converted_contact_id`. Joining on `lead_id` alone silently truncates every won lead's history —
which is exactly the population you're trying to learn from. `opps.csv` has **no** `lead_id`; the
only path is `leads_history.converted_opp_id`.

## 6. What the profiling found

### Outcomes
- **954 leads (17.3%) converted to an opp; 907 won → 16.5% lead-level win rate.** Very high for paid
  inbound, consistent with low-ACV self-serve.
- Of leads that reach an opp, **95.1% win**. The opp stage is nearly a formality — meaning **the real
  decision is upstream, at qualification, not in the pipeline.** That shapes what's worth predicting.
- Won amount: min 0, median $1,537, mean $1,655, max $5,429. `deal_type` is `Hearth New Account` for
  all 954 — no segmentation available there.
- Stage: 907 Closed Won / 41 Closed Lost / 6 Qualification.
- Status is dominated by `Unqualified` (21.9%), `Closed Won` (17.8%), `Bad Data` (14.7%),
  `Hold` (14.1%). **~15% of paid inbound is junk on arrival** — a live cost worth quantifying.

### Distribution shift between windows — the biggest scoring risk
The two windows are **not** drawn from the same distribution:

| Field | Train | Score |
|---|---|---|
| `channel = tiktok` | 6.3% | **0.4%** |
| `channel = google` | 35.2% | 44.8% |
| `utm_medium = prospecting` | 28.2% | **11.5%** |
| `utm_medium = brand` | 32.2% | 42.7% |
| `utm_medium = rd` | 23.7% | 35.7% |
| `icp_category = Low Value` | 66.8% | 57.6% |
| `icp_category = Unknown` | 0.3% | **4.7%** |
| `revenue = Personal Loan Inquiry` | 1.0% | 2.7% |

Marketing mix moved hard between the windows. Anything leaning on `channel`/`utm_medium` levels is
extrapolating, and `icp_category = Unknown` is 15× more common in the scoring set — it needs an
explicit handling rule, not an imputation accident.

### Data problems already spotted
- **`status` and `is_won` disagree.** 980 leads have status `Closed Won`, but only 954 have an opp and
  only 907 of those are `is_won = True`. Three different "won" counts. Pick one, say why.
- **`converted_contact_id` (980) > `converted_opp_id` (954)** — 26 leads became contacts without opps.
- **387 exact-duplicate objection rows** (353 groups sharing `call_ref` + `type` + `product`), ~4.7% of
  the table. Naive `COUNT(*)` per call overstates. *Not* every repeat is a dup — the same `type` can
  legitimately appear twice against different `product` values.
- **`activities.type` is blank on 36,449 rows** (25%) that still carry `subtype = Email`/`Task`.
  `call_disposition` is blank on 81,513 (56%). Type off `subtype`, not `type`.
- **4 activity rows predate the window**, earliest 2021-03-29.
- **`enrichment_status` is ~100% `Not Enriched`** in both windows — a dead column.
- **`heard_about_us` is blank on 7,122 of 8,171 extractions** (87%) — the weakest extraction field.
- **Objections resolve only 27% of the time** (2,234 / 8,275) despite a rebuttal being attempted on 76%.
- `legacy_score` is present on all 5,507 and does carry weak signal (mean 47.7 on won vs 37.6 on
  not-won) — so "nobody trusts it" is a trust problem, not strictly a signal problem. Worth a line:
  the naive baseline they benchmark against may well be this column.

### Call data — read the coverage rule carefully
Extractions cover **2,682 of 5,507 train leads (48.7%)**, and the brief is explicit that coverage
reflects *when an internal extraction job ran*, not anything about the leads. **Presence/absence of
call data is not signal** — don't let a model learn "has calls → converts."

Confirmed: **0 of the 4,255 scoring leads have any call data.** Call extractions and objections join
only to the train window. So call fields can inform *what* to tell a rep and *how* to design the tool,
but they cannot be features in the submitted score. Extraction `call_at` runs to Jul 31 2026 — long
post-conversion support/onboarding tails on train-window leads.

Call shape: `discovery` 2,094 · `brief_live` 1,772 · `closing` 1,131 · `voicemail_drop` 873 ·
`demo` 826 · `gatekeeper` 562 · `support` 494 · `onboarding` 314. Reached: `decision_maker` 5,576 ·
`influencer` 1,056 · `nobody` 967 · `gatekeeper_only` 572. Outcome: `held` 3,505 · `advanced` 2,722 ·
`no_contact` 1,409 · `rejected` 482 · `regressed` 53.

Top objections: `timing` 2,578 · `price` 1,706 · `partner_dm` 1,057 · `no_need` 1,006 ·
`competitor` 730 · `product_gap` 503 · `trust` 351 · `financing_terms` 334. (A long tail of near-empty
types — `seat_limits` 5, `language` 1, `seasonality` 1 — suggests schema drift or a rarely-hit branch.)

## 7. The transcripts

25 files, `transcript_01..25.txt`. Header block carries `call_ref` and `lead_id`; then a two-speaker
dialogue where **`Phone Caller #2` is always the Hearth rep** and **`Phone Caller #1` the prospect**
(owner or office-manager gatekeeper). Six rep personas: Caspian (6), Barnaby (6), Peregrine (4),
Odalys (4), Torvald (3), Delphine (2).

**All 25 match a row in `call_extractions.csv` and a lead in `leads_history.csv`** — verified, zero
unmatched. Their purpose per the brief is narrow and explicit: **audit the extraction schema against
source material — what it captured, what it missed, what you'd add.** They are synthesized to be
consistent with real extraction records. **Do not compute population statistics from them.**

Two things to keep in mind while auditing:

- **They are template-generated.** "Accounting program my cousin set up" appears in 17 of 25 files,
  "adding a second crew" in 16, "next county over" in 12, "can you hear me okay" in 21. Repeated
  phrases are generator structure, not contractor behavior.
- **Speaker labels are sometimes wrong.** In at least `transcript_04` and `transcript_15`, a
  prospect's line is attributed to the rep. Realistic diarization error — and itself a finding about
  what an extraction layer is reading.

Seeds already visible for the schema audit: `transcript_18` is typed `call_type = gatekeeper` but
`reached = influencer` while the speaker says "I kinda run the office side, the owner's out" —
the gatekeeper/influencer boundary is doing real work and may be inconsistently applied. And several
transcripts carry strong growth signals ("second crew by spring", "expanding into the next county")
that the schema has **no field for** — an obvious candidate for "what would you extract that we don't."

## 8. Open questions to ask them

The brief invites email, and scores what you ask. Candidates, strongest first:

1. **Capacity and cost** — how many reps, what's a working day's capacity, what does a touch cost?
   The cutoff is meaningless without it, and they said asking is as valid as assuming.
2. **What is `status = Bad Data`?** ~15% of paid inbound. Is it detectable at intake? If so, that's a
   shippable win independent of the score.
3. **Is `legacy_score` the naive baseline?** They won't say — but asking shows you clocked it.
4. **Why did the marketing mix shift so hard** between the windows, and is the Mar–May mix the
   steady state going forward? Determines whether to model channel at all.
5. **What action does a tier actually trigger** in Salesforce/HubSpot today — queue, cadence, round-robin?
   The score is only worth what the routing does with it.
6. **`status` vs `is_won` vs `converted_opp_id`** — which is the system of record for "won"?

## 9. Working notes

- Everything in §6 was verified directly against the files; nothing there is assumed.
- Not yet done: the speed-to-lead analysis (memo Q3 — needs first-touch from `activities` joined
  through both `who_id` forms), target selection, the model, and the rep-facing tool.
- Timing: `created_at` → first activity gives response time; `mql_at`/`sal_at` give funnel stamps.
  **`sal_at` is identical to `mql_at` on 3,797 of the 4,957 rows that have both (76.6%)** — for three
  quarters of leads these are not distinct stages, so any MQL→SAL duration is zero by construction.
  278 leads have neither stamp.
- **`data/` and `transcripts/` are gitignored.** This repo has a GitHub remote
  (`AviBenmayor/abenmayor`) and the brief forbids posting the files anywhere. Commit code and the
  memo, never the pack. Delete the pack when the process concludes.
