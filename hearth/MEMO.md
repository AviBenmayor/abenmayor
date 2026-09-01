# Lead scoring for Hearth inbound — Avi Benmayor

**1 · Target: expected dollars, P(win) × E[size | win].** The brief says the three targets rank
differently. **Here they don't, and that's the finding** — ρ(P(win), expected dollars) = **0.997**,
ρ(P(win), P(win ≤30d)) = **0.974**. Deal size spans 1.9× p10–p90 while P(win) spans ~46×, and the two
move together, so the product barely reorders. I picked expected dollars anyway, on principle: this
is a revenue business, and a rep's next call should go to the lead most likely to bring in the most
money — not merely the one most likely to say yes. Expected revenue is the only target that says
that directly, and the only one denominated in something you can hold against cost-to-serve, which
is what sets the cutoff.

**2 · What I found.** Logistic regression on three intake fields: revenue band, ICP category, legacy
CRM score. Fifteen parameters, hand-computable. Validated out-of-time (Oct–Dec → Jan–Feb), never a
random split, because the base rate climbs 12.3% → 20.1% across cohorts. **AUC 0.724 against 0.645
for the legacy score.** Adding campaign, time zone and zip3 reaches 0.760 — **I dropped all three**,
because each failed a stability test out of period or was untestable, and they drift hardest into
your window. At the 30% cutoff the smaller model catches the same 221 wins. It trains on the **4,574
leads a rep actually worked**, since a rep asks *"if I call this, will it convert?"* — not *"what
share converted including the ones nobody phoned."* That's worth 3 points of probability, nothing in
ranking, and it removed the need for calibration entirely: **19.7% predicted against 19.0% actual,
uncorrected.**

**Your ICP labels invert under control.** Raw, `High Value` beats `Ideal`, 30.2% to 24.1%. But inside
*every* revenue band where both appear, Ideal wins — 44.4% vs 32.3% at $1–5M, 48.4% vs 36.5% at
$5–10M. It's a size proxy, not a quality signal, so **anyone routing by that label is being misled.**
Appendix C has the data problems; the one that touches my labels is **504 leads across three owners
at 100% touched, 25–30 touches each, zero wins, all still in "New Lead."** **What the data cannot
answer:** whether working a lead harder *causes* a win — effort and outcome are jointly determined by
reps who chose what to work. I can rank; I can't price a touch. That needs randomised routing.

**3 · Does responding faster predict a higher win rate?** **Yes — and about a third of it is
confounding.** Raw, ≤1h beats >1h, **21.2% to 15.8%** (p=1.7e-06). But reps call good leads first:
mean legacy score is 47.8 in the sub-5-minute bucket against 33.6 beyond three days. The clean test
is arrival time — **a lead landing at 3am waits for reasons unrelated to its quality.** Those leads
match on every intake field, wait **16.7× longer**, and win only **3.1 points less**. And the worst
bucket isn't slow, it's **abandoned**: beyond three days, 13.1 touches against ~27 elsewhere.
**So enforce a same-business-day first touch — but don't buy a speed-to-lead product on the raw
number.**

**4 · Where the line sits.** Weekday-only, from `activities.csv`: **70 reps × 8 touches = 560/day**,
against 22 touches to work a lead properly — **25 new leads a day against 65 arriving.** You can
properly work about a third of what marketing buys, so **the line goes at the top 30%: capacity, not
a probability threshold.** It captures **54% of expected wins**, and against real Jan–Feb outcomes
there, **221 wins against 193 for the legacy score — +15%** (209 for ICP routing, 121 for random).
**This is an assumption and here's where it breaks:** I assume logged activity is all activity, and
that 22 touches is a requirement rather than a habit. Both errors point the same way — **I'm more
likely to have set the line too high than too low.** Nothing below it is discarded, since the bottom
70% still holds 46% of winnable deals: **tier C → email sequence, no dial; tier D → nurture plus a
monthly re-score**, on fixed cutoffs so tier A means the same thing in every file. **What I can't
tell you is which rep should get it** — reps range 0% to 62.5%, far beyond chance, but over half of
that tracks the leads they were handed (corr **+0.56**).

**5 · Monday, and the 30-day read.** Ship the scores as a CRM field plus the queue tool, top 30%, to
**half the floor** — without a control, a rising base rate reads as the model working. Two things
need no model: **stop dialling `Personal Loan Inquiry` leads** (1.8% win rate, homeowners rather than
contractors, and growing from 1.0% to 2.7% of inbound), and put the ICP inversion in front of whoever
owns routing. **In 30 days** I'd read win rate on worked leads, treatment against control, wanting
**≥+10%** — below the +15% seen offline, because holdout lift shrinks. Secondary: dials per win, and
rep override rate, since above ~30% the tool has failed whatever its AUC. Guardrail: total wins must
not fall. **I'd stop** if the arms are within noise, or the top decile fails to beat legacy's live.

---
*Appendix A model and features · B speed-to-lead · C data problems · D capacity and tiers ·
`QUESTIONS.md` what I'd ask you · live dashboard and rep tool in `README.md`*
