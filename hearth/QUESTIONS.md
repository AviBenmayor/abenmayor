# Questions for Hearth

The brief says some things I need aren't in the pack, and that what I choose to ask about is part of
what you're reading. These are ordered by how much they'd change the work — not by how easy they are
to answer. I've built under a stated assumption for each rather than waiting.

### 1. Capacity and cost per touch
**Assumed:** ~14 new leads/day of real capacity, derived from `activities.csv` — 145 reps, median 6
dials per rep-active-day, ~52 reps working daily, ~22 touches per properly worked lead. Against 47
leads/day arriving, that puts the cutoff at the top 30%.

**Asking because** the cutoff is the one number in this that isn't a modelling choice, and my
estimate is inferred from logged activity, which undercounts if calls go unlogged or overcounts if
those 22 touches include post-sale onboarding. What is a rep's actual daily capacity, and what does
a dial cost you? With a real cost per touch I'd set the line where marginal expected value crosses
it, instead of where capacity runs out.

### 2. How do you organise reps, and is there a skill difference worth routing around?
**Assumed:** leads go to whoever is next, and any rep can work any lead. I built the score to rank
the book, not to assign it.

**Asking because** I can see that reps differ enormously — the 53 with 25+ leads span 0% to 62.5%
win rate, far beyond chance (χ²=711, df=52, p≈0) — but I can't tell skill from allocation. Over half
that spread tracks the quality of leads they were handed (corr = +0.56), and I see no territories
(46% of a median rep's leads in one time zone against a 42% baseline) and no segment specialisation
(67% against a 67% baseline). `owner_id` is also assigned as part of working a lead rather than at
intake, so I can't use it as a feature or read it as a verdict on anyone.

If there are real tiers — seniority, pods, closers vs openers — then the top of the ranking should go
to specific people and I'd build that. If it's round-robin, the ranking alone is the whole answer.
These are different products and I've shipped the second one.

### 3. What are `rep_128`, `rep_222` and `rep_210`?
504 leads, 9% of the book, **100% touched with a median of 25–30 touches each, and zero wins**, all
still sitting in `New Lead` status on leads of normal quality. **Assumed:** a status write-back
failure rather than 504 genuinely dead leads. It matters both ways — if the statuses are wrong, some
of my training labels are wrong; if they're right, something has been absorbing paid leads and rep
hours for five months.

### 4. Which field is the system of record for "won"?
980 leads carry status `Closed Won`, 954 have a `converted_opp_id`, and 907 of those have
`is_won = True`. **I used `is_won`** — it's the narrowest and ties to an actual opportunity — but the
three disagree by 8%, which is larger than the margin between my model and the legacy score. If
`status` is what the business reports on, my labels are wrong by 73 leads and every number moves.

### 5. What is `status = "Bad Data"`, operationally?
14.7% of paid inbound, a 0% win rate, and 61% of it still got touched by a rep. It's partly
predictable at intake (TikTok 31.3% vs Google 10.3%). **Assumed:** unreachable or invalid contact
details. If that's right, a bad-data filter is worth shipping independently of any lead score, and
possibly worth taking to whoever buys the TikTok inventory. If it means something else — duplicates,
test records, out-of-territory — the fix is different and probably upstream of both of us.

### 6. Why did the channel mix move so hard between the two windows, and is the new mix the steady state?
TikTok fell 6.3% → 0.4%, `prospecting` 28.2% → 11.5%, `brand` rose 32.2% → 42.7%, and
`icp_category = Unknown` went 0.3% → 4.7%. I dropped `channel` and `utm_medium` from the model partly
for this reason — they were also the weakest features on out-of-time validation, which made the call
easy. But if the mix keeps moving, retraining cadence matters more than model choice, and I'd want to
know whether Mar–May is the new normal or itself a transition.

### 7. What actually happens to a lead after it's scored?
**Assumed:** a score field plus tier drives queue order in Salesforce, and tier C/D route to a
HubSpot sequence rather than a dial. I've built the tool to be agnostic — it takes a CSV and returns
a ranked queue. But a score only earns its keep through the routing action attached to it, and if
assignment is round-robin by territory today, the ranking has to fit inside that constraint rather
than replace it.

### 8. Is the legacy score the baseline you're benchmarking against?
You said you won't tell me, which is fair. Flagging it because I found the legacy score does carry
real signal — mean 47.7 on won leads vs 37.6 on lost, AUC 0.645 — so "nobody trusts it" looks like a
trust and adoption problem at least as much as an accuracy one. That's worth knowing before anyone
ships a second score into the same CRM and expects a different reception.

### 9. Extraction schema — two things I'd add
Not a blocker, just what the transcripts showed against `call_extractions.csv`:
- **No field captures growth intent.** Multiple transcripts have a contractor volunteering a second
  crew or an expansion into the next county — a buying signal with a date on it, and the schema has
  nowhere to put it.
- **`reached` and `call_type` disagree.** `transcript_18` is typed `call_type = gatekeeper` but
  `reached = influencer`, where the speaker says "I kinda run the office side, the owner's out."
  The gatekeeper/influencer boundary is doing real work and looks inconsistently applied.
- `heard_about_us` is blank on 87% of rows. If it isn't being extracted reliably, it may be worth
  dropping rather than half-populating.
