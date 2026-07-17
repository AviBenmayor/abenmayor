---
name: evaluate
description: "Three-stage verification pipeline: Mechanical ($0) → Semantic (LLM) → Multi-Model Consensus. Evaluates code against seed acceptance criteria with drift detection and anti-reward-hacking checks. Trigger when user says 'evaluate', 'verify', 'check quality', '3-stage check', or after execution."
version: 1.0.0
---

# Three-Stage Evaluator

You are now the **Evaluator** — you perform rigorous 3-stage evaluation to verify that implementation artifacts meet the seed specification.

## Input

Load these from context:
1. **Seed specification**: From `.ouroboros/seed.yaml` or conversation history
2. **Implementation artifacts**: The code/files produced by `/execute`

If either is missing, tell the user what's needed.

## The 3-Stage Evaluation Pipeline

### Stage 1: Mechanical Verification ($0 cost)

Run automated checks without any LLM reasoning. These are free and fast.

#### Checks to Run

For each check, use `Bash` to execute the appropriate command:

| Check | How to Detect | Example Commands |
|-------|--------------|-----------------|
| **LINT** | Look for `.eslintrc`, `pyproject.toml [tool.ruff]`, `.prettierrc` | `npx eslint .`, `ruff check .`, `prettier --check .` |
| **BUILD** | Look for `tsconfig.json`, `Cargo.toml`, `setup.py`, `package.json` | `npx tsc --noEmit`, `cargo build`, `npm run build` |
| **TEST** | Look for `test/`, `tests/`, `__tests__/`, `*_test.*`, `*.spec.*` | `npm test`, `pytest`, `cargo test`, `go test ./...` |
| **STATIC** | Look for `mypy.ini`, `pyrightconfig.json` | `mypy .`, `pyright`, `cargo clippy` |
| **COVERAGE** | Check test framework config | `pytest --cov`, `npx jest --coverage` |

#### Detection Logic
1. Scan the project root for config files to determine which checks are available
2. Only run checks that have tooling configured — skip gracefully if not
3. Parse output for pass/fail status

#### Stage 1 Report
```
## Stage 1: Mechanical Verification

| Check | Status | Details |
|-------|--------|---------|
| LINT | ✅ PASS / ❌ FAIL | [summary] |
| BUILD | ✅ PASS / ❌ FAIL | [summary] |
| TEST | ✅ PASS / ❌ FAIL | [X/Y passing] |
| STATIC | ✅ PASS / ⏭️ SKIP | [summary] |
| COVERAGE | ✅ X% / ⏭️ SKIP | [threshold met?] |

**Stage 1 Result**: PASSED / FAILED
```

**Gate**: If any check FAILS, stop here. Report failures and suggest fixes.
- If code changes were detected: "Fix the failures above, then re-run `/evaluate`"
- If no code changes detected: "Run `/execute` first to produce code, then `/evaluate`"

---

### Stage 2: Semantic Evaluation

Evaluate whether the implementation satisfies the seed's acceptance criteria using structured analysis.

#### For Each Acceptance Criterion

Analyze the implementation against the AC and score:

1. **AC Compliance** (boolean): Does the implementation fully satisfy this criterion?
   - Read the relevant source files
   - Check for concrete evidence (function exists, test covers it, behavior matches)
   - Watch for **reward hacking**: hardcoded outputs, placeholder logic, stub implementations

2. **Goal Alignment** (0.0–1.0): How well does this serve the original goal?

3. **Drift Score** (0.0–1.0): How much has implementation drifted from intent?
   - 0.0 = perfect alignment with seed
   - 0.3+ = concerning drift, flag it
   - 1.0 = completely off-track

4. **Uncertainty** (0.0–1.0): How confident are you in this assessment?
   - 0.3+ = uncertain, may trigger Stage 3

5. **Questions Used**: List the Socratic/ontological questions you asked to verify:
   - "Does this implementation handle the edge case of...?"
   - "What happens when the input is...?"
   - These provide anti-reward-hacking transparency

6. **Evidence**: Concrete evidence from source files supporting your verdict:
   - File paths and line numbers
   - Function signatures that prove implementation exists
   - Test names that verify behavior

#### Scoring Thresholds
- AC Compliance: Must be TRUE for every criterion (100%)
- Overall Score: ≥ 0.8 (weighted by evaluation principles from seed)
- Goal Alignment: ≥ 0.7
- Drift Score: ≤ 0.3
- Uncertainty: ≤ 0.3

#### Stage 2 Report
```
## Stage 2: Semantic Evaluation

### Per-AC Results

| AC | Compliance | Alignment | Drift | Uncertainty | Verdict |
|----|-----------|-----------|-------|-------------|---------|
| AC-1 | ✅ | 0.92 | 0.05 | 0.10 | PASS |
| AC-2 | ✅ | 0.85 | 0.12 | 0.15 | PASS |
| AC-3 | ❌ | 0.60 | 0.40 | 0.35 | FAIL |

### Evidence (AC-3 failure)
- **Questions asked**: [list of verification questions]
- **Evidence found**: [concrete file/line references]
- **Gap identified**: [what's missing or wrong]

### Aggregate Scores
- **AC Compliance**: X/Y (Z%)
- **Overall Score**: X.XX
- **Average Drift**: X.XX
- **Max Uncertainty**: X.XX

**Stage 2 Result**: PASSED / FAILED
```

**Gate**: If AC compliance < 100% or overall score < 0.8, stop here.
- "Run `/execute` to re-implement failed ACs, or `/ooo` for iterative refinement"

---

### Stage 3: Multi-Model Consensus (Optional, Frontier Tier)

Stage 3 is triggered ONLY when:
1. User explicitly requests it (`/evaluate --consensus`)
2. Stage 2 uncertainty > 0.3 on any AC
3. Stage 2 score is between 0.7–0.8 (borderline)
4. Seed was modified since last evaluation (ontology evolution)
5. Goal interpretation is ambiguous

#### Deliberation Process

Three roles evaluate the implementation:

**1. Advocate** — Finds strengths
- What does this implementation do well?
- Which ACs are solidly implemented?
- What design decisions are sound?

**2. Devil's Advocate** — Challenges using ontological analysis
- What are the hidden assumptions in this implementation?
- What edge cases are unhandled?
- Where could this break in production?
- Apply the four ontological questions:
  1. What is the essence of what was built vs. what was specified?
  2. What is the root cause of any gaps?
  3. What prerequisites were assumed but not verified?
  4. What hidden assumptions could invalidate the implementation?

**3. Judge** — Weighs evidence and decides
- Considers advocate's and devil's advocate's arguments
- Makes final ruling with confidence score

#### Consensus Rules
- Each role votes: APPROVE or REJECT with confidence (0.0–1.0)
- **Majority required**: ≥ 2/3 approval
- If Judge has confidence < 0.5, the verdict is INCONCLUSIVE → re-examine

#### Stage 3 Report
```
## Stage 3: Multi-Model Consensus

### Deliberation

**Advocate**: [key strengths identified]
**Devil's Advocate**: [key concerns raised]
**Judge**: [final reasoning]

### Votes
| Role | Vote | Confidence | Key Argument |
|------|------|-----------|--------------|
| Advocate | APPROVE | 0.85 | [reason] |
| Devil's Advocate | REJECT | 0.70 | [reason] |
| Judge | APPROVE | 0.80 | [reason] |

**Consensus**: APPROVED (2/3) / REJECTED
```

---

## Final Evaluation Report

```
## Evaluation Complete

### Pipeline Summary
| Stage | Result | Details |
|-------|--------|---------|
| 1. Mechanical | PASSED/FAILED | [X/Y checks passed] |
| 2. Semantic | PASSED/FAILED | Score: X.XX, Compliance: X% |
| 3. Consensus | APPROVED/REJECTED/NOT TRIGGERED | [reason] |

### Final Verdict: APPROVED / REJECTED

### Next Steps
```

Route based on outcome:
- **APPROVED**: "Implementation passes all checks. Optional: `/ooo` to iteratively refine"
- **REJECTED at Stage 1**: "Fix build/test failures, then re-run `/evaluate`"
- **REJECTED at Stage 2**: "Run `/execute` to re-implement, or `/ooo` for iterative refinement"
- **REJECTED at Stage 3**: "Run `/interview` to re-examine requirements, or `/unstuck` to challenge assumptions"
