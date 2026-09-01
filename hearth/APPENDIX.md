# Appendices

Supporting evidence for `MEMO.md`. Every number here is reproducible from `src/` — see
`README.md` for the run order.

---

## A · Model and features

### A1. Why three fields and not six

Each feature was tested for **stability**: does its effect survive into a period it was not
fitted on? A real effect persists; a spurious one wanders. Levels with n≥40 in both halves.

| Feature | period-to-period correlation | verdict |
|---|---|---|
| `icp_category` | spearman **1.000** (3 levels) | kept |
| `contractor_annual_revenue` | pearson **+0.933**, p=0.007 (6 levels) | kept — strongest feature |
| `legacy_score` | mean 47.7 on won vs 37.6 on lost | kept |
| `campaign_ref` | +0.846, p=0.002 (10 levels) | **dropped** — 19.4% of the scoring window is campaigns never seen in training |
| `time_zone` | +0.859 but **p=0.141**, 4 levels, range only 14.2–20.0% | **dropped** — underpowered, and no business mechanism |
| `zip3` | **untestable** — only one zip has ≥40 leads in both periods | **dropped** despite the largest single AUC gain |
| `channel`, `utm_medium`, `state` | dropping them *improved* out-of-time AUC | dropped |
| `enrichment_status` | ~100% one level in both windows | dead column |

### A2. What that choice cost, out-of-time (Oct–Dec 2025 → Jan–Feb 2026)

| Feature set | AUC | lift@10 | lift@20 | lift@30 |
|---|---|---|---|---|
| revenue + ICP + legacy **(shipped)** | 0.724 | 2.31 | 2.05 | **1.81** |
| + zip3 | 0.746 | 2.36 | 2.14 | 1.90 |
| + campaign + time zone | 0.737 | 2.36 | 2.14 | 1.81 |
| all five + zip3 | 0.760 | 2.41 | 2.13 | 1.93 |
| legacy_score (baseline) | 0.645 | 1.77 | 1.60 | 1.58 |

**lift@30 is the operational number** — it's where the cutoff sits. The shipped model matches the
four-feature model there (1.81 vs 1.81) and catches the same 221 wins. The AUC given up was ranking
inside the bottom of the book, where nobody is making calls.

Rows other than the shipped one are fitted on all 5,507 leads, which is how the feature comparison
was run before the training population was narrowed (A4); the ordering between feature sets is
unaffected.

### A3. Model form

Logistic regression beat the alternatives on identical features: GBM 0.7226, random forest 0.7281,
logistic 0.7368. A **deeper** GBM got materially *worse* (0.6836), which says there is no interaction
structure for a tree to find — the response is close to additive, so the linear model is the right
form, not merely the convenient one. Bootstrap over 2,000 resamples: logistic beats GBM in 98%.

### A4. Training population

| | answers | base rate | mean p on scored window |
|---|---|---|---|
| all 5,507 leads | *P(win \| lead arrives)* | 16.5% | 19.0% |
| **4,574 worked leads (shipped)** | *P(win \| a rep works it)* | 19.8% | **21.8%** |

Excluded: never-touched leads, queue-parked leads, and the three owners in C2 — none could have won.
Ranking is unaffected (spearman **0.998**, 97% overlap in the top 30%); only the level moves.
**Cost:** this conditions on a rep having chosen to work the lead, so bias in that choice is
inherited. That is why the +15% lift in the memo is measured on the *full* Jan–Feb book.

### A5. No calibration layer

Platt scaling was fitted and removed: it moved no prediction by more than **0.015** and, being
monotone, reordered nothing. Isotonic was worse — it collapsed 351 distinct scores into 33 and cost
AUC. Choosing the training population (A4) fixed the level instead: **19.7% predicted vs 19.0%
actual**, uncorrected. Removing it also made the browser scorer *bit-identical* to Python (0.0
difference), because no log/exp round-trip remains.

---

## B · Speed-to-lead

Analysis set: 5,069 touched leads. Untouched leads are excluded — they win 0% by construction, so
including them measures whether a lead was worked at all, not how fast.

| Test | Result | Reading |
|---|---|---|
| **Raw** — first touch ≤1h vs >1h | 21.2% vs 15.8%, p=1.7e-06 | large and significant |
| **Triage control** — within legacy-score decile | <5m bucket falls 21.7% → **16.9%** | much of the raw effect is reps calling good leads first |
| **Natural experiment** — off- vs in-hours arrivals | 17.0% vs 20.0%, **+3.1pp**, p=0.012 | a **16.7×** swing in response time buys 3 points |
| **Regression** — logistic, intake controlled | OR **0.935** per e-fold; 30min → 24h = ×0.77 odds | real, small, survives controls |

Reps triage: mean legacy score is **47.8** in the <5-minute bucket against **33.6** beyond three
days; %Ideal falls 23.8% → 6.2%. The >3-day bucket received **13.1 touches against ~27** everywhere
else — that bucket is *abandoned*, not slow, and response time there is proxying for "nobody worked
this."

**Verdict:** enforce a same-business-day first touch, which is cheap. Do not buy a speed-to-lead
product on the strength of 21.2% vs 15.8%.

---

## C · Data problems

### C1. Three definitions of "won" disagree
980 leads with `status = Closed Won`, 954 with a `converted_opp_id`, **907** with `is_won = True`.
I used `is_won` — narrowest, and tied to an actual opportunity. The three differ by 8%, which is
larger than the margin between this model and the legacy score. **Which is the system of record?**

### C2. 504 leads worked hard, never leaving "New Lead"
`rep_128` (393 leads), `rep_222` (83), `rep_210` (28): **100% touched, median 25–30 touches, zero
wins**, on leads of normal quality (mean legacy 41.2 vs 40.7 overall). Reps do not dial something 25
times and update nothing. Either statuses aren't written back — so some training labels are wrong —
or these are routing sinks that have absorbed five months of paid leads.

### C3. `Bad Data` is 14.7% of paid inbound
Wins 0%, yet **61% of it still got touched**. Partly predictable at intake: TikTok **31.3%** bad vs
Google **10.3%**; `prospecting_lead_generation` 30.8% vs `rd` 11.1%. A spend problem sitting inside
a routing exercise, and shippable independently of any score.

### C4. Smaller things
- **387 duplicate objection rows** (353 groups sharing `call_ref` + `type` + `product`), ~4.7%.
- **`activities.type` is blank on 25%** of rows that still carry a `subtype`. Type off `subtype`.
- **`sal_at` = `mql_at` on 76.6%** of rows with both — MQL→SAL is not a real stage for most leads.
- **`close_date` is date-only**, so 144 wins appear to close "before" the lead arrived. Artifact, not
  a broken record — use calendar-day differences.
- **`enrichment_status`** is ~100% `Not Enriched` in both windows.
- **Distribution shift** between windows: TikTok 6.3% → 0.4%, `prospecting` 28.2% → 11.5%,
  `icp_category = Unknown` 0.3% → 4.7%. A reason to distrust channel-level features.

### C5. What the data cannot answer
- **Whether effort causes wins.** Effort and outcome are jointly determined. Needs randomised routing.
- **Lead value past first sale.** `deal_type` is `Hearth New Account` for all 954 opps — no
  expansion, renewal or churn signal, so "expected dollars" is first-order value only.
- **Which rep should get a lead.** See D3.

---

## D · Capacity, the cutoff, and tiers

### D1. Capacity, derived rather than assumed
163 reps logged activity; **98% of it falls Mon–Fri**, so medians are weekday-only. **70 reps on a
typical weekday × 8 touches each = 560 touches/day.** A properly worked lead absorbs **22 touches**
→ **25 new leads/day of real capacity against 65 arriving.**

Both sides are counted in the same unit, which is the easy thing to get wrong: price a lead in
touches while measuring supply in dials and you understate capacity by a third; compare working-day
supply against calendar-day arrivals and you overstate coverage by a third the other way.

### D2. Why the line lands at 30%, not 39%
Working *more* leads and working them *properly* compete for the same touches. At **30 touches for
tier A and 22 for tier B**, the intensity ladder spends 36,720 touches against a measured supply of
36,400 — **100% utilisation.** Working 39% of the book flat and 30% with a real ladder cost the floor
the same day; the second is worth more.

| Work the top… | leads | expected wins | % of all wins | win rate |
|---|---|---|---|---|
| 10% | 425 | 210 | 23% | 49.4% |
| 20% | 851 | 367 | 39% | 43.1% |
| **30%** | **1,276** | **498** | **54%** | **39.0%** |
| 50% | 2,127 | 693 | 75% | 32.6% |
| 100% | 4,255 | 929 | 100% | 21.8% |

**If the capacity estimate is wrong the line moves and the model doesn't.**

### D3. Which rep — the question left open
53 reps with 25+ leads range from **0% to 62.5%** win rate, far beyond chance (χ²=711, df=52, p≈0).
But **over half of that tracks the leads they were handed** — corr(rep's mean lead quality, rep's win
rate) = **+0.56**. No visible territories (median rep has 46% of leads in one time zone against a 42%
baseline) and no visible specialisation (67% in one ICP band against a 67% baseline). `owner_id` is
also assigned as part of *working* a lead rather than at intake, which is why queue-held leads show a
0% win rate — definitional, not a finding. So rep assignment is a question I have left open rather
than answered badly.

### D4. Tiers
Fixed score cutoffs, frozen into `model.json` — **not** within-batch percentiles. A rep who loads 50
leads must not get five "tier A" that are merely the best of a bad batch; tier has to mean the same
thing in every file.

| Tier | leads | mean P(win) | action |
|---|---|---|---|
| A | 438 | 49% | call now, up to 30 touches |
| B | 851 | 34% | call today, up to 22 touches |
| C | 1,264 | 21% | email sequence, no dial |
| D | 1,702 | 10% | nurture, monthly re-score |
