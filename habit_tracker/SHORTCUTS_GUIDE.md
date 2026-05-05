# iOS Shortcuts Guide — Habit Tracker

## Prerequisites

1. **Notion Integration Token**: Create an internal integration at https://www.notion.so/my-integrations
   - Name it "Habit Tracker"
   - Copy the **Internal Integration Secret** (starts with `ntn_`)
   - Go to the Habit Tracker parent page in Notion → ••• menu → Connections → Add "Habit Tracker"
   - This grants the integration access to both databases

2. **IDs Reference** (from `notion_config.json`):
   - Habit Log DB: `3ef7854435ba4ab8805b8ebbd6a27935`
   - Habits Config DB: `d71756dd54354596a8b680ca43318264`

---

## Shortcut 1: Log Habit

The core shortcut. Select a habit, enter a value, and it writes to Notion.

### Steps to Build

1. **Open Shortcuts app** → tap **+** → name it **"Log Habit"**

2. **Add action: "List"**
   Create a list with all 10 habit names:
   ```
   Steps
   Water
   Sleep
   Stress Management
   Exercise
   Journaling
   Budgeting
   Reading
   Hobbies
   Screen Time
   ```

3. **Add action: "Choose from List"**
   - Prompt: "Which habit?"

4. **Add action: "If"** — branch based on habit type

   **For numeric habits** (Steps, Water, Sleep, Exercise, Reading):

   Add action: **"If"**
   - Input: Chosen Item
   - Condition: "is" → "Steps"
   - Then: **"Ask for Input"** → Type: Number → Prompt: "How many steps?"

   Repeat similar If blocks for Water ("How many glasses?"), Sleep ("How many hours?"), Exercise ("How many minutes?"), Reading ("How many minutes?")

   **For yes/no habits** (Stress Management, Journaling, Budgeting, Hobbies, Screen Time):
   - No input needed — these auto-log as completed

   **Tip:** Use a **Dictionary** to simplify. See the "Optimized Version" section below.

5. **Add action: "Get Contents of URL"** (this is the Notion API call)
   - URL: `https://api.notion.com/v1/pages`
   - Method: **POST**
   - Headers:
     - `Authorization`: `Bearer ntn_YOUR_TOKEN_HERE`
     - `Content-Type`: `application/json`
     - `Notion-Version`: `2022-06-28`
   - Request Body (JSON): See below

6. **Add action: "Show Notification"**
   - Title: "Habit Logged"
   - Body: "[Chosen Item] logged!"

### Notion API Request Body

**For a numeric habit (e.g., Steps):**
```json
{
  "parent": {
    "database_id": "3ef7854435ba4ab8805b8ebbd6a27935"
  },
  "properties": {
    "Entry": {
      "title": [
        {
          "text": {
            "content": "Steps — 2026-03-22"
          }
        }
      ]
    },
    "Date": {
      "date": {
        "start": "2026-03-22"
      }
    },
    "Habit": {
      "relation": [
        {
          "id": "32b48af1-331b-8153-ab00-de7d0265adcf"
        }
      ]
    },
    "Value": {
      "number": 8500
    },
    "Completed": {
      "checkbox": true
    }
  }
}
```

**For a yes/no habit (e.g., Journaling):**
```json
{
  "parent": {
    "database_id": "3ef7854435ba4ab8805b8ebbd6a27935"
  },
  "properties": {
    "Entry": {
      "title": [
        {
          "text": {
            "content": "Journaling — 2026-03-22"
          }
        }
      ]
    },
    "Date": {
      "date": {
        "start": "2026-03-22"
      }
    },
    "Habit": {
      "relation": [
        {
          "id": "32b48af1-331b-81bb-a860-d05ed27316c3"
        }
      ]
    },
    "Value": {
      "number": 1
    },
    "Completed": {
      "checkbox": true
    }
  }
}
```

### Habit → Notion Page ID Mapping

Use this to set the correct relation ID:

| Habit | Page ID |
|-------|---------|
| Steps | `32b48af1-331b-8153-ab00-de7d0265adcf` |
| Water | `32b48af1-331b-81ea-8dce-e9781291823e` |
| Sleep | `32b48af1-331b-81ba-92e8-d8305accdb47` |
| Stress Management | `32b48af1-331b-813c-a450-dd213ad265f6` |
| Exercise | `32b48af1-331b-81ac-9d50-cce8778668be` |
| Journaling | `32b48af1-331b-81bb-a860-d05ed27316c3` |
| Budgeting | `32b48af1-331b-81a0-98ed-e31b60273b67` |
| Reading | `32b48af1-331b-812f-9a97-e66d4c253e8a` |
| Hobbies | `32b48af1-331b-8137-b251-ddb3ae3e88f5` |
| Screen Time | `32b48af1-331b-812c-8a01-de07e32e0650` |

### Optimized Version (using Dictionaries)

Instead of nested If blocks, use two Dictionaries to look up habit info:

**Step 1: Habit ID Dictionary**
Add action: **Dictionary**
```
Steps → 32b48af1-331b-8153-ab00-de7d0265adcf
Water → 32b48af1-331b-81ea-8dce-e9781291823e
Sleep → 32b48af1-331b-81ba-92e8-d8305accdb47
Stress Management → 32b48af1-331b-813c-a450-dd213ad265f6
Exercise → 32b48af1-331b-81ac-9d50-cce8778668be
Journaling → 32b48af1-331b-81bb-a860-d05ed27316c3
Budgeting → 32b48af1-331b-81a0-98ed-e31b60273b67
Reading → 32b48af1-331b-812f-9a97-e66d4c253e8a
Hobbies → 32b48af1-331b-8137-b251-ddb3ae3e88f5
Screen Time → 32b48af1-331b-812c-8a01-de07e32e0650
```

**Step 2: Habit Type Dictionary**
Add action: **Dictionary**
```
Steps → number
Water → number
Sleep → number
Exercise → number
Reading → number
Stress Management → yes_no
Journaling → yes_no
Budgeting → yes_no
Hobbies → yes_no
Screen Time → yes_no
```

**Step 3: Get Values from Dictionaries**
- "Get Dictionary Value" for key [Chosen Item] from Habit ID Dictionary → save as `habitId`
- "Get Dictionary Value" for key [Chosen Item] from Habit Type Dictionary → save as `habitType`

**Step 4: Conditional Input**
- **If** `habitType` = "number":
  - "Ask for Input" (Number) → Prompt based on habit name → save as `inputValue`
- **Otherwise**:
  - Set `inputValue` to `1`

**Step 5: Check Goal Completion**
Add a **Goal Dictionary**:
```
Steps → 10000
Water → 8
Sleep → 7
Exercise → 45
Reading → 15
```
- For numeric habits: **If** `inputValue` ≥ goal value → set `isCompleted` to `true`, else `false`
- For yes/no habits: always `true`

**Step 6: Format Date**
- "Current Date" → "Format Date" → format: `yyyy-MM-dd` → save as `todayDate`

**Step 7: Build JSON Body**
Add action: **Text**
```
{
  "parent": {"database_id": "3ef7854435ba4ab8805b8ebbd6a27935"},
  "properties": {
    "Entry": {"title": [{"text": {"content": "[Chosen Item] — [todayDate]"}}]},
    "Date": {"date": {"start": "[todayDate]"}},
    "Habit": {"relation": [{"id": "[habitId]"}]},
    "Value": {"number": [inputValue]},
    "Completed": {"checkbox": [isCompleted]}
  }
}
```

**Step 8: API Call**
- "Get Contents of URL"
  - URL: `https://api.notion.com/v1/pages`
  - Method: POST
  - Headers: `Authorization: Bearer ntn_YOUR_TOKEN`, `Content-Type: application/json`, `Notion-Version: 2022-06-28`
  - Request Body: [Text from Step 7]

**Step 9: Confirmation**
- "Show Notification": "[Chosen Item] logged!"

---

## Shortcut 2: Auto Sync (Apple Health)

Pulls steps and sleep from Apple Health and writes to Notion.

### Steps to Build

1. **Name:** "Habit Auto Sync"

2. **Get Steps:**
   - Add action: **"Find Health Samples"**
     - Type: Steps
     - Start Date: Start of Today
     - End Date: Now
     - Group By: Day
   - "Get Details of Health Samples" → get "Value" → save as `todaySteps`

3. **Get Sleep:**
   - Add action: **"Find Health Samples"**
     - Type: Sleep Analysis
     - Start Date: Yesterday at 6 PM
     - End Date: Today at 12 PM
     - Group By: Day
   - Calculate total sleep hours → save as `todaySleep`

4. **Format Date:**
   - "Current Date" → format `yyyy-MM-dd` → save as `todayDate`

5. **Log Steps to Notion:**
   - "Get Contents of URL" (same POST as Shortcut 1)
   - Body with: Habit relation = Steps ID, Value = `todaySteps`, Completed = `todaySteps` ≥ 10000

6. **Log Sleep to Notion:**
   - "Get Contents of URL" (same POST)
   - Body with: Habit relation = Sleep ID, Value = `todaySleep`, Completed = `todaySleep` ≥ 7

7. **Notification:** "Synced: [todaySteps] steps, [todaySleep]h sleep"

### Automation Trigger
- Open **Shortcuts** → **Automation** tab → **+**
- **Time of Day** → 9:00 PM → **Run Immediately**
- Select "Habit Auto Sync"

---

## Shortcut 3: Morning Brief

Shows today's scheduled habits as a morning notification.

### Steps to Build

1. **Name:** "Morning Brief"

2. **Get Current Day:**
   - "Current Date" → "Format Date" → format: `EEEE` (gives "Monday", "Tuesday", etc.) → save as `dayOfWeek`

3. **Build Habit List:**
   - Start with the daily habits (always shown):
     ```
     Steps, Water, Sleep, Stress Management, Journaling, Budgeting, Reading, Screen Time
     ```
   - **If** `dayOfWeek` is Mon/Tue/Wed/Thu/Fri → add "Exercise"
   - **If** `dayOfWeek` is Mon/Wed/Fri/Sat/Sun → add "Hobbies"

4. **Show Notification:**
   - Title: "Good morning! Today's habits:"
   - Body: [habit list, one per line]

### Automation Trigger
- **Time of Day** → 7:30 AM → **Run Immediately**

---

## Shortcut 4: Evening Check-In

Queries Notion for today's incomplete habits and reminds you.

### Steps to Build

1. **Name:** "Evening Check-In"

2. **Format Date:**
   - "Current Date" → format `yyyy-MM-dd` → save as `todayDate`

3. **Query Notion for today's entries:**
   - "Get Contents of URL"
   - URL: `https://api.notion.com/v1/databases/3ef7854435ba4ab8805b8ebbd6a27935/query`
   - Method: POST
   - Headers: same as before
   - Body:
   ```json
   {
     "filter": {
       "property": "Date",
       "date": {
         "equals": "2026-03-22"
       }
     }
   }
   ```
   (Use `todayDate` variable instead of hardcoded date)

4. **Parse Response:**
   - "Get Dictionary Value" for key "results" → save as `loggedEntries`
   - Extract the habit names from each entry

5. **Compare Against Full List:**
   - Build the full expected list for today (same logic as Morning Brief)
   - Use "Repeat with Each" + "If" to find habits NOT in `loggedEntries`
   - Save missing habits as `missingList`

6. **Show Notification:**
   - **If** `missingList` is not empty:
     - Title: "Habits check-in"
     - Body: "Still to log: [missingList]"
     - Add "Open Log Habit shortcut" action on tap
   - **Otherwise:**
     - Title: "All done!"
     - Body: "You've logged all habits for today."

### Automation Trigger
- **Time of Day** → 9:00 PM → **Run Immediately**

---

## Shortcut 5: Weekly Review

Generates a weekly summary and creates a review page in Notion.

### Steps to Build

1. **Name:** "Weekly Review"

2. **Calculate Date Range:**
   - "Current Date" → "Adjust Date" → subtract 7 days → format `yyyy-MM-dd` → save as `weekStart`
   - "Current Date" → format `yyyy-MM-dd` → save as `weekEnd`

3. **Query This Week's Entries:**
   - "Get Contents of URL"
   - URL: `https://api.notion.com/v1/databases/3ef7854435ba4ab8805b8ebbd6a27935/query`
   - Method: POST
   - Body:
   ```json
   {
     "filter": {
       "and": [
         {
           "property": "Date",
           "date": { "on_or_after": "[weekStart]" }
         },
         {
           "property": "Date",
           "date": { "on_or_before": "[weekEnd]" }
         }
       ]
     }
   }
   ```

4. **Count Completions:**
   - Use "Repeat with Each" on results
   - Count total entries and completed entries per habit
   - Calculate completion rate: completed / expected days × 100

5. **Create Review Page in Notion:**
   - "Get Contents of URL"
   - URL: `https://api.notion.com/v1/pages`
   - Method: POST
   - Body:
   ```json
   {
     "parent": {
       "page_id": "32b48af1-331b-81d8-9ecf-d7f66a189b6a"
     },
     "properties": {
       "title": [
         {
           "text": {
             "content": "Weekly Review — [weekStart] to [weekEnd]"
           }
         }
       ]
     },
     "children": [
       {
         "object": "block",
         "type": "heading_2",
         "heading_2": {
           "rich_text": [{"type": "text", "text": {"content": "Completion Summary"}}]
         }
       },
       {
         "object": "block",
         "type": "paragraph",
         "paragraph": {
           "rich_text": [{"type": "text", "text": {"content": "[formatted summary of each habit's completion rate]"}}]
         }
       }
     ]
   }
   ```

6. **Notification:**
   - Title: "Weekly Review Ready"
   - Body: "Overall: [X]% completion. Tap to view in Notion."

### Automation Trigger
- **Time of Day** → Sunday 7:00 PM → **Run Immediately**

---

## Shortcut 6 (Optional): Quick Log Widgets

One-tap shortcuts for the most common habits.

### Create One Per Frequent Habit

For example, **"Log Water"**:
1. Increment a counter variable or ask for glasses
2. POST to Notion with Water habit ID
3. Show quick confirmation

Repeat for: "Log Exercise", "Log Reading", "Done Journaling", etc.

### Add to Home Screen
- Long press each shortcut → "Add to Home Screen"
- Group them in a "Habits" folder on your home screen

---

## Setup Checklist

- [ ] Create Notion integration at https://www.notion.so/my-integrations
- [ ] Connect integration to the Habit Tracker page in Notion
- [ ] Replace `ntn_YOUR_TOKEN_HERE` with your real token in all shortcuts
- [ ] Build Shortcut 1: Log Habit
- [ ] Build Shortcut 2: Auto Sync
- [ ] Build Shortcut 3: Morning Brief
- [ ] Build Shortcut 4: Evening Check-In
- [ ] Build Shortcut 5: Weekly Review
- [ ] Set up automation triggers for Shortcuts 2-5
- [ ] (Optional) Build Quick Log widgets
- [ ] Test by logging a few habits and checking they appear in Notion
