# Habit Tracker — Project Specification

## Overview
A serverless habit tracking system using **iOS Shortcuts** for daily input and **Notion** for data storage, dashboards, and weekly reviews. No backend server required — everything runs on-device or through the Notion API.

## Habits (10 total)

| # | Habit | Measurement | Daily Goal | Data Source | Default Frequency |
|---|-------|------------|------------|-------------|-------------------|
| 1 | Steps | Number | 10,000 | Apple Health (auto) | Daily |
| 2 | Water | Glasses (number) | 8 | Manual (Shortcut) | Daily |
| 3 | Sleep | Hours (number) | 7-8 | Apple Health (auto) | Daily |
| 4 | Stress Management | Yes/No | 1x | Manual (Shortcut) | Daily |
| 5 | Exercise | Minutes (number) | 45 | Manual (Shortcut) | Customizable |
| 6 | Journaling | Yes/No | 1x | Manual (Shortcut) | Daily |
| 7 | Budgeting | Yes/No | 1x | Manual (Shortcut) | Daily |
| 8 | Reading | Minutes (number) | 15 | Manual (Shortcut) | Daily |
| 9 | Hobbies | Yes/No | 1x | Manual (Shortcut) | Customizable |
| 10 | Screen Time | Yes/No (under cap) | Stay under limit | Self-reported (Shortcut) | Daily |

- Each habit has a **fully customizable frequency** (daily, specific weekdays, X times per week)
- The system should be designed so habits can be added or removed over time

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  iOS Shortcuts   │────▶│  Notion API  │────▶│  Notion DBs     │
│  (input + auto)  │     └──────────────┘     │  (storage)      │
└─────────────────┘                           └────────┬────────┘
                                                       │
┌─────────────────┐                           ┌────────▼────────┐
│  Apple Health    │──▶ via Shortcuts ────────▶│  Notion Views   │
│  (steps, sleep)  │                           │  (dashboards)   │
└─────────────────┘                           └─────────────────┘
```

### No server. No app. Just Shortcuts + Notion.

## iOS Shortcuts (5-6 total)

### 1. Log Habit
- Menu-driven: select a habit, enter the value (or toggle yes/no)
- Writes a row to the Notion Habit Log database via API
- Should be fast — optimized for minimal taps

### 2. Auto Sync
- Pulls steps and sleep data from Apple Health via HealthKit Shortcuts actions
- Writes to Notion automatically
- Runs as a time-based automation (e.g., end of day)

### 3. Morning Brief
- Fires as a morning automation (e.g., 7:30 AM)
- Shows a notification or alert listing today's scheduled habits
- Checks which habits are already logged (auto-synced ones)

### 4. Evening Check-In
- Fires as an evening automation (e.g., 9:00 PM)
- Queries Notion for today's incomplete habits
- Shows a notification listing what's still unlogged
- Optionally opens the Log Habit shortcut

### 5. Weekly Review
- Fires on Sunday evening (or chosen day)
- Queries the past week's data from Notion
- Creates/updates a weekly review page in Notion with:
  - Completion rates per habit
  - Current streak counts
  - Highlights and areas for improvement

### 6. Quick Log (Optional)
- One-tap shortcuts for the most common habits (e.g., "Logged Water" widget)
- Skips the menu and directly increments/logs a specific habit

## Notion Database Schema

### Habit Log DB (main data store)
| Property | Type | Description |
|----------|------|-------------|
| Date | Date | The day this entry is for |
| Habit | Select | Which habit (Steps, Water, Sleep, etc.) |
| Value | Number | The numeric value (steps count, minutes, glasses, etc.) |
| Completed | Checkbox | Whether the habit was completed (for yes/no habits, or if goal was met) |
| Notes | Text | Optional notes |

### Habits Config DB (habit definitions)
| Property | Type | Description |
|----------|------|-------------|
| Name | Title | Habit name |
| Type | Select | number, yes_no |
| Goal | Number | Daily target value |
| Unit | Text | glasses, steps, minutes, hours, etc. |
| Frequency | Select | daily, weekdays, custom |
| Custom Days | Multi-select | Mon, Tue, Wed, etc. (if frequency = custom) |
| Active | Checkbox | Whether this habit is currently being tracked |
| Data Source | Select | manual, apple_health, self_report |

### Weekly Review Template
- Auto-generated page per week
- Linked database views filtered to that week
- Formulas for completion percentage per habit
- Streak tracking via rollups or formulas

### Dashboard Page
- **Scorecard view**: Table showing each habit's completion rate this week
- **Calendar view**: Habit Log DB filtered by date, showing daily completion
- **Streak tracker**: Current and best streaks per habit (via Notion formulas/rollups)

## Notifications (iOS Shortcuts Automations)

| Notification | Time | Trigger | Content |
|-------------|------|---------|---------|
| Morning Brief | ~7:30 AM | Time-based automation | "Today's habits: [list]. Steps and sleep already synced." |
| Evening Check-In | ~9:00 PM | Time-based automation | "You haven't logged: [incomplete habits]. Tap to log." |
| Weekly Review | Sunday ~7:00 PM | Time-based automation | "Weekly review ready. [X/10 habits on track]" |

## Accountability
- **Streaks**: Track consecutive completion days per habit (stored in Notion via formulas)
- **Weekly Review**: Structured reflection prompt in Notion every week
- **No gamification**: Just data, streaks, and self-reflection

## Future Considerations (not in MVP)
- Sharing/accountability partner access to Notion dashboard
- Trend charts via external tools if native Notion views feel limiting
- Additional auto-data sources (Oura, Fitbit)
- Habit correlations (does more sleep correlate with more exercise?)

## MVP Scope
Build in this order:
1. **Notion databases** — Create Habit Log DB, Habits Config DB, and Dashboard page
2. **Log Habit shortcut** — Core input flow
3. **Auto Sync shortcut** — Steps and sleep from Apple Health
4. **Morning + Evening automations** — Notification shortcuts
5. **Weekly Review shortcut** — Automated weekly summary page
6. **Streaks** — Add streak formulas to Notion
