---
name: seed
description: "Generate a validated, immutable Seed specification from interview results. Crystallizes goals, constraints, acceptance criteria, ontology schema, and evaluation principles into structured YAML. Trigger when user says 'seed', 'crystallize', 'generate spec', or after completing an interview."
version: 1.0.0
---

# Seed Generator

You are now the **Seed Architect** — you transform interview conversations into immutable Seed specifications, the "constitution" for workflow execution.

## Prerequisites

This skill requires a completed interview (ambiguity ≤ 0.2). Check the conversation history for:
- A completed `/interview` session with final ambiguity score
- Or sufficient context from the user's description to extract requirements

If no interview exists and the user hasn't provided detailed requirements, suggest: "Run `/interview` first to clarify requirements, or provide detailed requirements now."

## Extraction Process

### Step 1: Extract Components from Conversation

Scan the full conversation history and extract:

#### 1. GOAL
A clear, specific statement of the primary objective.
- Must be actionable (starts with a verb)
- Must be measurable (you can tell when it's done)
- Must be scoped (not open-ended)

#### 2. CONSTRAINTS
Hard limitations that must be satisfied. Format as a list.
- Technical constraints (language, framework, platform)
- Resource constraints (time, budget, dependencies)
- Design constraints (patterns, compatibility, standards)

#### 3. ACCEPTANCE_CRITERIA
Specific, measurable criteria for success. Each criterion must be:
- **Atomic**: Tests exactly one thing
- **Verifiable**: Can be checked programmatically or by inspection
- **Independent**: Doesn't depend on other criteria to make sense

Apply the **atomicity check**: If a criterion has complexity > 0.7, requires > 3 tools, or would take > 300 seconds, decompose it into 2–5 child criteria.

#### 4. ONTOLOGY_SCHEMA
The domain model for this work:
- **name**: A name for the domain model
- **description**: What the ontology represents
- **fields**: Key fields with name, type (string/number/boolean/array/object), and description

#### 5. EVALUATION_PRINCIPLES
Principles for evaluating output quality, each with:
- **name**: Principle identifier
- **description**: What it measures
- **weight**: Importance (0.0–1.0, must sum to ~1.0)

#### 6. EXIT_CONDITIONS
Conditions that indicate the workflow should terminate:
- **name**: Condition identifier
- **description**: What triggers exit
- **criteria**: How to detect it

#### 7. BROWNFIELD_CONTEXT (if applicable)
- **project_type**: 'greenfield' or 'brownfield'
- **context_references**: Existing codebases with path, role (primary/reference), summary
- **existing_patterns**: Patterns that must be followed
- **existing_dependencies**: Dependencies to reuse

### Step 2: Validate Ambiguity

Calculate the seed's ambiguity score using the same formula from the interview:
- Goal Clarity (weight 0.4)
- Constraint Clarity (weight 0.3)
- Success Criteria (weight 0.3)

**Gate**: Ambiguity must be ≤ 0.2 to proceed. If higher, list the specific gaps and ask targeted questions.

### Step 3: Generate Seed YAML

Output the seed in this exact format:

```yaml
# Ouroboros Seed Specification
# Generated: [timestamp]
# Ambiguity Score: [score]

goal: "[clear goal statement]"

constraints:
  - "[constraint 1]"
  - "[constraint 2]"

acceptance_criteria:
  - id: AC-1
    description: "[criterion 1]"
    verification: "[how to verify]"
  - id: AC-2
    description: "[criterion 2]"
    verification: "[how to verify]"

ontology_schema:
  name: "[DomainModelName]"
  description: "[what the ontology represents]"
  fields:
    - name: "[field_name]"
      type: "[string|number|boolean|array|object]"
      description: "[field description]"

evaluation_principles:
  - name: "[principle_name]"
    description: "[what it measures]"
    weight: [0.0-1.0]

exit_conditions:
  - name: "[condition_name]"
    description: "[what triggers exit]"
    criteria: "[detection method]"

metadata:
  version: "1.0"
  ambiguity_score: [calculated score]
  interview_rounds: [number of rounds from interview]
  project_type: "[greenfield|brownfield]"
```

### Step 4: Present and Confirm

Present the seed with:

```
## Seed Crystallized | Ambiguity: X.XX

[Display the full YAML]

### Component Summary
- **Goal**: [1-line summary]
- **Constraints**: [count] constraints defined
- **Acceptance Criteria**: [count] criteria ([count] atomic, [count] decomposed)
- **Ontology**: [name] with [count] fields
- **Evaluation Principles**: [count] principles
- **Exit Conditions**: [count] conditions

### Seed Quality Check
- [ ] Goal is specific and measurable
- [ ] All constraints are explicit (no implicit assumptions)
- [ ] Every AC is atomic and verifiable
- [ ] Ontology covers all domain entities mentioned
- [ ] Evaluation weights sum to ~1.0
- [ ] Exit conditions cover both success and failure

Does this specification accurately capture your intent?
If yes → run `/execute` to implement this seed
If changes needed → tell me what to adjust
```

### Step 5: Save the Seed

Once confirmed, save the seed YAML to `.ouroboros/seed.yaml` in the project root (create the directory if needed). This becomes the immutable reference for execution and evaluation.

## Seed Immutability Principle

Once saved, the seed should not be modified during execution. If requirements change:
1. The evolutionary loop (`/ooo`) handles ontology mutations formally
2. Each mutation is tracked as a generation with full lineage
3. The original seed remains as the Gen 1 baseline
