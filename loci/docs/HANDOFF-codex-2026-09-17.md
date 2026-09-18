# Handoff to Codex — retail-space-search thread close-out (2026-09-17)

Written by the Claude session that ran the 2026-09-17 market-research thread. Everything
below is either already on disk or is a task with a precise spec. Read `docs/CHECKPOINT.md`
first (project rule), then `docs/retail-space-search-market-2026-09-17.md` §1 and §8–§10.

## Where things stand

**Owner's question:** "I am noticing there might be a market gap for available retail spaces
in New York. I want to do deep market research on what exists for hopeful business owners
to find available retail spaces and then how much the asking price is as well as the lease
terms. If nothing exists, we might need to carve out a large portion of Loci capacity to
develop this."

**Research done (on disk, do not redo):**
- `docs/retail-space-search-market-2026-09-17.md` — the full memo, 12,179 words. Three
  Opus research threads (tenant-facing channel map, 60 channels; rent/lease-terms
  visibility incl. public records; demand side + prior attempts), then an investor pass
  and a contrarian pass. Every URL kept (215, §11). Six ready-to-paste QUESTIONS.md
  entries in §10.
- Raw research files are in the Claude session scratchpad only
  (`/private/tmp/claude-501/-Users-abenmayor-Documents-Projects-abenmayor/ca99d5df-81ca-451d-92bc-6e0157b12733/scratchpad/research_*.md`,
  `synthesis_*.md`); they may be gone. The memo is the durable copy.

**Findings that matter for the decision (all sourced in the memo):**
- The gap is NOT "no listings". ~2,500–4,800 NYC retail-for-lease listings exist
  (Yardi network, Crexi). The gap is opaque rent/terms + unlisted inventory + stale
  listings. Price shown on 54% of a 68-card sample; lease terms on 0/68 (contrarian
  grades both numbers D as tenant-side claims — see memo §7).
- The City already collects the missing data and withholds it: LL157 (2019) makes
  owners report average monthly rent per sf, lease start/expiry, scheduled increases and
  concessions at premises grain (~70k storefronts). Open Data 92iy-9c3n publishes 31
  columns with no rent field. Withholding mechanism inferred to be RPIE confidentiality
  (UNVERIFIED).
- Demand side: operators' pain is decoding true cost and landlord acceptance, not
  discovery; zero evidence of tenant willingness to pay; broker floor ~$3–5k/mo rent
  (grade D, no broker asked).
- Every prior tenant-side startup (42Floors, Truss, TenantBase, SquareFoot, Spacious,
  Storefront.com) died or pivoted by becoming a broker; Int 1472 (2019) promised a
  rent/size/use database and shipped LL157 without rent; Int 0568-2024 disclosure bill died.
- Investor verdict: build-narrow (card line + FOIL + dossier shape into AC-2; no listings
  site). Contrarian verdict: not a gap a product can close; run a 100-storefront
  two-persona corridor test before any build; guardrail — "vacant storefronts as leads"
  is D88 costume risk again.

**Owner ruling (2026-09-17, by buttons): "FOIL only, park the rest."**
File the FOIL for the LL157 rent fields (1–2 sessions). Log the investor/contrarian
split as QUESTIONS.md entries. Return capacity to the survival gate (grocery PPV 0.07
failing, P3′/P5/P6 due 2027-01-31) and AC-1. Revisit only if the FOIL returns
premises-grain rent. The one number that flips the ruling: a FOIL response returning the
LL157 rent-per-sf column at premises grain.

## Status update (2026-09-17, later same day — read this first)

Codex already ran most of this handoff. Done, verified on disk:
- `docs/asks/foil-ll157-rent-fields-2026-09-17.md` written (task 1).
- `docs/CHECKPOINT.md` D126 entry added, session-log line added.
- `src/loci/tickets.py` got a D126 ticket — but Codex placed the tuple inside the
  `EPICS` list literal instead of `T` (wrong list, wrong schema), so `loci
  check-tickets` failed and blocked every Bash command in this repo via the
  pre-commit hook. **Already fixed by the Claude session** (moved the tuple into
  `T`, changed the description's Linear-id language to the same provisional
  `GTM-206` placeholder convention the file already uses for D107/GTM-185, ran
  `loci gen-tickets` + `loci check-tickets` — now passes clean, 97 decisions
  covered). Nothing further needed on this point; just don't reintroduce the bug.

Still open — task 2c below (QUESTIONS.md entries) was NOT done. Do that, then the
commit (task 2e). Skip task 1 and the CHECKPOINT/tickets.py parts of task 2a/2b —
already landed.

## Tasks for Codex, in order

### 1. Draft the FOIL request (the deliverable of the chosen path) — DONE, see above

An Opus agent was drafting this and was stopped before writing. Check
`docs/asks/foil-ll157-rent-fields-2026-09-17.md` — if it exists, review it against the
spec below and skip to task 2; if not, write it. This is a DRAFT for the owner to send
himself. Do NOT submit anything anywhere.

Evidence to read first: memo §3 (LL157 filing fields vs published columns, the 2019
DOF PDF with council-district rent averages, RPIE inference), and the house format of
the one existing ask in `docs/asks/dot-camera-and-vivacity-2026-09-17.md`.

Verify with web research (cite URLs + access dates, flag anything unverified):
1. Statutory basis: the NYC Admin Code sections LL157/2019 enacted (storefront registry,
   Title 11), the exact data elements owners must report, and what the statute says about
   confidentiality/publication (does it cross-reference RPIE confidentiality, Admin Code
   §11-208.1, or is it silent?). Quote the operative text.
2. **Lead found by the stopped agent, verify first:** Int 0090-2026, "Lease agreements
   concerning storefront premises", reportedly heard by the Council on 2026-09-16. Read the
   bill text and hearing record. If it mandates lease-term or rent disclosure, it changes
   both the FOIL letter (cite it) and the QUESTIONS entry on regulation (memo §3 says no
   jurisdiction forces asking-rent posting — that claim may need a caveat).
3. DOF FOIL mechanics: NYC OpenRecords portal (a856-openrecords.nyc.gov), DOF Records
   Access Officer, statutory timeline (5 business days ack, ~20 business days), appeal route.
4. Precedents: prior OpenRecords/MuckRock requests for storefront-registry data; any Council
   or Comptroller report that obtained the rent fields; the 2019 DOF PDF as proof DOF has
   published derived rent figures before.
5. Strongest denial ground (POL §87(2)(d) trade secret / a specific Admin Code
   confidentiality clause) and counters: LL157's own publication mandate; asking rent is
   not a trade secret when the landlord posts it on a listing; severability (release
   non-exempt columns); tiered fallbacks (rent per sf banded at BBL grain; council-district
   × year × storefront-type medians; counts of scheduled-increase and concession flags by NTA).

File contents: (a) purpose paragraph in house format (why Loci wants this; both reviewers
agreed to file; it is the flip number); (b) filing checklist (portal, agency, RAO, what to
paste where, timeline, appeal); (c) the letter, ready to paste, <700 words: precise records
description (fields, filing years 2020–2026), machine-readable format per POL §89(3)(a),
fee language, pre-emptive severability paragraph, tiered fallback ask; (d) anticipated-denial
table (ground | likelihood | reply | appeal-worthy?); (e) what Loci does on each outcome
(full premises-grain / banded / aggregate only / denial), three lines each; (f) sources.
Whole file <2,500 words.

### 2. Session-end bookkeeping (project rules in `CLAUDE.md` and `docs/CHECKPOINT.md`)

Concurrent sessions may be on this tree. `git status` first; stage by explicit path only;
never touch `src/loci/cli.py` hunks that are not yours.

a. **CHECKPOINT.md decision entry.** Last entry on disk is D124. Commit `bbaa988` says
   "CHECKPOINT D125 to follow" — that id is claimed by that commit's author (a peer
   session). Use **D126** unless CHECKPOINT already shows it taken; if a peer is live,
   claim the id by chat before editing. Entry shape: bold header line
   `**D126 — <what was decided>.** *(2026-09-17, owner)*` then the why. Content: owner
   asked the tenant-side market question; three research threads + investor + contrarian
   (memo path); the gap type found; the LL157 collected-but-unpublished finding; both
   verdicts; owner ruling "FOIL only, park the rest" with the reason (no tenant WTP
   evidence, predecessors died by becoming brokers, the pivot would displace the survival
   gate and AC-1); the flip condition (premises-grain rent from FOIL); explicitly NOT
   building a listings site, NOT adding the card vacancy-rent line now, NOT the dossier.
   Note the D67 (2026-09-10) finding stands and this memo supersedes nothing.
   Also add a session-log line under a `### 2026-09-17 — Session N` header and a
   next-actions item "send the FOIL (owner)".

b. **tickets.py definition in the SAME edit** — `loci check-tickets` fails any CHECKPOINT
   decision without one and blocks every session on the tree. File:
   `src/loci/tickets.py`; look at the D124/GTM-198 tuple for the shape
   `(epic, title, priority, estimate, labels, description, [status])`. One ticket:
   epic "E4 · Validation and Artifact" (or the epic the file uses for owner asks — check),
   title "File FOIL for LL157 storefront-registry rent and lease fields (D126)", priority
   H, small estimate, labels "validation,nyc", description carrying the reasoning (the
   memo's flip number; why the tenant-side product was parked), "Opened 2026-09-17
   (CHECKPOINT D126)". Then run `make` targets: `uv run loci gen-tickets` (regenerates
   docs/TICKETS.md, linear-import.csv, linear-tickets.json — never hand-edit those) and
   `uv run loci check-tickets` must pass. Pushing to Linear (GTM project, milestone =
   epic) is a separate step — do it only if the Linear MCP is available and the owner's
   standing rule for this thread allows; otherwise leave "push to Linear" in next actions.

c. **QUESTIONS.md.** Append the six entries from memo §10 in the file's `### <id> — <question>`
   / `- **Status:**` / `- **Why it matters:**` / `- **How to answer:**` format (mirror
   the nearest open entry's fields exactly; ids continue the file's scheme). Add one
   more: "Does Int 0090-2026 change the no-jurisdiction-forces-disclosure claim?" if task 1
   step 2 finds it does.

d. **Memory / sanity.** Confirm the CHECKPOINT phase line and next-actions list match the
   body (stale-header check is the thing Fable verifies at session end).

e. **Commit** (owner has asked for commits on this thread before; if in doubt, stage and
   stop). Stage by explicit path:
   `docs/retail-space-search-market-2026-09-17.md`,
   `docs/asks/foil-ll157-rent-fields-2026-09-17.md`, `docs/CHECKPOINT.md`,
   `docs/QUESTIONS.md`, `docs/TICKETS.md`, `docs/linear-import.csv`,
   `docs/linear-tickets.json`, `src/loci/tickets.py`, and this handoff file. Do not stage
   the unrelated modified files already in `git status` (aerial/sidewalk/agent_memory work
   belongs to another session). Commit message in the repo's style (see `git log -3`):
   one long subject line stating what landed and the decision id; end with the
   attribution trailer the repo uses.

## Do not

- Do not build anything tenant-facing. The ruling is FOIL only.
- Do not re-run the research; the memo is the record. If a number is challenged, the
  contrarian grades in memo §7 say what would fix it.
- Do not write to the DuckDB warehouse or move the supply hash (ed55301203a4). Nothing in
  this thread touches data.
- Do not send the FOIL. The owner sends it.
