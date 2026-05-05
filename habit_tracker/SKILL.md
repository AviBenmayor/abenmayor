# Habit Tracker Skills

## Skill 1: `socratic-interview` — Specification Interview

**Based on:** [Ouroboros](https://github.com/Q00/ouroboros) Double Diamond methodology

A live, interactive Socratic interview that fully defines the habit tracker project before any code is written. The goal is to surface hidden assumptions, clarify requirements, and produce an unambiguous specification document.

---

### How It Works

The interview follows the **Double Diamond** process with four phases:

#### Phase 1: Wonder (Diverge)
Ask focused, one-at-a-time questions to explore the full problem space. Never assume — always ask. Adapt follow-up questions based on previous answers.

**Areas to explore:**

- **Habits & Measurement**
  - What habits beyond the initial list (steps, water, sleep, stress, exercise, journaling, budgeting, reading, hobbies) should be tracked?
  - How should each habit be measured? (binary yes/no, numeric value, duration, rating scale)
  - What are the daily/weekly goals and thresholds for each habit?
  - Should habits have different frequencies? (daily, weekdays only, 3x/week, etc.)
  - How should missed days be handled? (zero, skip, grace period)

- **Notion Integration**
  - Does the user have an existing Notion workspace and structure?
  - What database schema makes sense? (one DB per habit vs unified DB)
  - How should the Notion pages be organized? (daily logs, weekly summaries, dashboards)
  - Should Notion be the primary UI or just the data backend?
  - Are there existing Notion templates or systems to integrate with?

- **Push Notifications**
  - What platform? (iOS, Android, both, desktop)
  - What triggers notifications? (time-based reminders, missed habits, streak milestones, celebrations)
  - What times of day should reminders fire? (morning planning, evening review, habit-specific)
  - How aggressive should reminders be? (single reminder, escalating, snooze-able)
  - Should notifications be customizable per habit?

- **Data Input & Sources**
  - Manual entry only, or integrate with external sources? (Apple Health, Google Fit, Fitbit, Oura, etc.)
  - What's the preferred input method? (quick tap, form, voice, shortcut/widget)
  - How much friction is acceptable for daily logging?
  - Should there be batch entry for catching up on missed days?

- **UX & Access**
  - Primary interface: mobile app, web app, Notion-native, or CLI?
  - Is offline support important?
  - Multi-device sync requirements?
  - Who uses this? (just the user, or shared with accountability partner/coach)

- **Analytics & Accountability**
  - What visualizations matter? (streaks, heatmaps, trends, correlations)
  - Weekly/monthly review format?
  - Streak tracking and what breaks a streak?
  - Gamification elements? (points, levels, badges)
  - Social or accountability features?

- **Technical Preferences**
  - Any preferred tech stack or languages?
  - Hosting preferences? (local, cloud, serverless)
  - Budget constraints for APIs or services?
  - Privacy/data ownership concerns?

#### Phase 2: Ontology (Converge)
Once all areas have been explored:
- Summarize all findings in a structured format
- Identify any contradictions or tensions between answers
- Highlight areas where the user's goals may conflict (e.g., low friction vs comprehensive tracking)
- Confirm understanding with the user before proceeding

#### Phase 3: Design (Diverge)
Based on the converged understanding:
- Propose 2-3 distinct architecture approaches with trade-offs
- For each approach, outline: tech stack, data flow, notification strategy, and Notion schema
- Highlight what each approach optimizes for (simplicity, flexibility, integration depth)

#### Phase 4: Evaluation (Converge)
- Let the user select and refine their preferred approach
- Validate the final specification against original intent
- Write a complete `SPECIFICATION.md` to the `habit_tracker/` directory

---

### Skill Behavior

- **Ask one question at a time** using `AskUserQuestion` — never overwhelm with multiple topics
- **Track progress** — maintain awareness of which areas have been explored and which remain
- **Adapt dynamically** — use previous answers to inform follow-up questions (don't ask about Apple Health integration if the user said manual-only)
- **Challenge assumptions** — if an answer seems contradictory or underspecified, probe deeper
- **Summarize periodically** — every 5-7 questions, briefly recap what's been established
- **Know when to stop** — when all areas have been sufficiently explored (low ambiguity), move to the Ontology phase

### Output

The interview concludes by writing `habit_tracker/SPECIFICATION.md` containing:
- Project overview and goals
- Complete habit list with measurement types and targets
- Notion database schema and page structure
- Notification strategy and rules
- Data input methods and integrations
- Tech stack and architecture decisions
- MVP scope vs future enhancements
