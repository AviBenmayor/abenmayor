# Planner review — putting a finding in front of someone who knows the block

*Process doc. The three live packets are in [planner-packets-2026-09.md](planner-packets-2026-09.md).
Verdicts land in `QUESTIONS.md`; when a verdict changes a rule, it also lands in the
`CHECKPOINT.md` decision log, the same way the contrarian's and the statistician's do.*

**Precedent.** D82 is the one time a planner verdict changed the model. The first character pass
passed a CBD sanity list and was still wrong: twelve prewar retail corridors read ~0
`retail_mixed`, because ground-floor retail in a 1920s taxpayer is not PLUTO `RetailArea` and a
six-person shop is not a LODES payroll cluster; hospitals read *corporate*; parks and cemeteries
got labels. Nothing in the data said the label was wrong — a person read it against a street they
had walked.

---

## 1. What a planner is uniquely able to judge

- **Ground truth of a corridor** — whether a named strip is a retail street, and where it starts
  and stops. No dataset carries this; every proxy (floor area, payroll, overlay geometry) fails on
  a different third of the city.
- **Zoning intent, not text** — why an overlay is mapped where it is, what an active-use mandate
  actually produces, which lots are legally reachable. A "gap" on a lot with no commercial
  frontage is an artifact.
- **Feasibility** — footprint, frontage, loading, venting. Whether the space a category needs
  exists on that block at all.
- **Displacement and turnover** — whether a thick corridor is healthy or churning, and whether a
  fill means a neighborhood served or replaced.
- **Whether a number is plausible.** "0.00× pharmacy" is either an opening or a verdict the market
  already rendered; a planner says which in ten seconds.
- **What "well" means for a filled gap** — hours, EBT, delivery, a pharmacist on duty at 8pm. The
  recommendations ledger cannot generate this for itself.

## 2. What a planner must NOT be asked to judge

Statistics, identification, code. Not "is AUC 0.866 vs 0.854 a real lift," not "is the placebo
constructed right" — those belong to the statistician and the contrarian, and a planner asked for
them defers politely and the packet is wasted. Nor "is the model good." A packet asks about **the
city**; the modeling consequence is ours to draw.

## 3. Packet format — one page per finding

Seven blocks, on one page. A packet needing two pages is two packets.

1. **The claim** — one sentence carrying the number.
2. **The map view** — URL, which toggle, which neighborhood to type into *Jump to neighborhood*,
   what to look at.
3. **The numbers, with grades** — five rows at most, each with its D74 letter grade and what that
   grade means. Ungraded numbers do not go in a packet.
4. **Three yes/no questions**, each answerable from knowledge without opening a dataset.
5. **One open question**, where their vocabulary exceeds ours.
6. **What would change if you say no** — the specific rule, table or claim that moves. If nothing
   moves, do not send the packet.
7. **Not asking** — one line of scope, so they don't feel underqualified.

## 4. How a verdict enters the record

- **One `QUESTIONS.md` entry per packet**, in the finding's tier (A → Tier T beside T11; B → X8;
  C → Tier D beside D12). Status `open` → `in-progress` (sent) → `answered` (≥2 reviewers agree),
  or stays `open` on a split. The reviewer's words go verbatim into *Current answer*, attributed
  by role and date, never paraphrased into agreement: "DCP alumnus, 2026-09-20: …".
- **A decision-log line only when a verdict changes a rule** — a threshold, a grade, a `GTM.md`
  claim, a column. Same form as D82: what was decided, why, what it replaced, what caveat
  survives. A verdict that changes nothing stays a `QUESTIONS.md` answer.
- **A split verdict is a result** — two planners disagreeing means the label is genuinely
  ambiguous there. Record both and suppress, rather than picking.
- **The ledger takes planner-defined "well" criteria per category** (D89): the planner supplies
  what a good fill looks like on that block, and it enters the rubric as the fit component, with
  the owner setting the weight (GTM-162 owns the weights). "Filled" and "filled well" stay
  separate columns; an unobservable criterion is `unavailable`, never zero.

## 5. Who to ask

| Type | Best on | Pair with packet |
|---|---|---|
| **NYC DCP alumni** (BK/MN borough office, Zoning) | overlay intent, mandated ground-floor use, what a rezoning delivers | B, then C |
| **SBS / Avenue NYC / Neighborhood 360°** | district health, what a good fill looks like, vacancy | C, then A |
| **BID directors** (Park Slope 5th Ave, Myrtle Ave, Bed-Stuy Gateway) | rents signed, who tours a space, churn | A |
| **Academic planners** (Hunter, Pratt, Furman, CUNY) | agglomeration vs unmet demand, displacement | A |
| **Tenant-rep brokers** — *contrast group* | why a category does not come, what space costs | C |

Brokers are a contrast group on purpose: most accurate on price, most interested in the answer.
Where a broker and a planner disagree, record both.

**The two-line ask** (works cold, answerable in ten minutes):

> I've built a map ranking NYC blocks by how thin daily-needs retail is per resident, and a
> backtest just told me it ranks *retail streets* rather than unmet demand. Could I send one page —
> three yes/no questions and one open one — for your reaction? No data work on your end; I'm trying
> to find where the map is lying to me.

## 6. Notion-ready packet template

Paste this into a Notion page, one page per finding.

```markdown
## [Finding id] — [one-line claim]
**Asked of:** [name, role] · **Sent:** [date] · **Record:** QUESTIONS.md [id]

**The claim.** [One sentence with the number.]

**Open the map.** [URL] → toggle **[toggle name]** → *Jump to neighborhood*: **[NTA]**.
Look at: [what].

| What | Value | Grade | What the grade means |
|---|---|---|---|
|  |  |  |  |

**Three yes/no questions**
1. [ ] Yes / No — …
2. [ ] Yes / No — …
3. [ ] Yes / No — …

**One open question.** …

**What would change if you say no.** …

**Not asking.** Nothing statistical — no model, no code, no significance.
```

---

## Appendix — the first three packets

Full send-ready text in [planner-packets-2026-09.md](planner-packets-2026-09.md).

- **A · D88 — "openings go where supply is already thick."** Demand herding, or the geometry of
  where retail is legal and re-lettable? → QUESTIONS T12.
- **B · D82 — the 20-lot overlay threshold, ten held-out corridors**, none used to tune it
  (GTM-154, next-action 34). → QUESTIONS X8.
- **C · D73/D74 — Gowanus: pharmacy 0.00×, convenience 0.40×, hardware 0.72×.** Do these fill, by
  whom, and what is "well"? → QUESTIONS D21.
