"""
Habit Tracker API Server
Runs on your Mac. iOS Shortcuts call this instead of Notion directly.
"""

import json
import os
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

HABIT_LOG_DB = "3ef7854435ba4ab8805b8ebbd6a27935"
HABITS_CONFIG_DB = "d71756dd54354596a8b680ca43318264"
PARENT_PAGE_ID = "32b48af1-331b-81d8-9ecf-d7f66a189b6a"

HABITS = {
    "Steps": {"id": "32b48af1-331b-8153-ab00-de7d0265adcf", "type": "number", "goal": 10000, "unit": "steps"},
    "Water": {"id": "32b48af1-331b-81ea-8dce-e9781291823e", "type": "number", "goal": 8, "unit": "glasses"},
    "Sleep": {"id": "32b48af1-331b-81ba-92e8-d8305accdb47", "type": "number", "goal": 8, "unit": "hours"},
    "Stress Management": {"id": "32b48af1-331b-813c-a450-dd213ad265f6", "type": "yes_no", "goal": 1, "unit": "session"},
    "Exercise": {"id": "32b48af1-331b-81ac-9d50-cce8778668be", "type": "number", "goal": 45, "unit": "minutes"},
    "Journaling": {"id": "32b48af1-331b-81bb-a860-d05ed27316c3", "type": "yes_no", "goal": 1, "unit": "entry"},
    "Budgeting": {"id": "32b48af1-331b-81a0-98ed-e31b60273b67", "type": "yes_no", "goal": 1, "unit": "review"},
    "Reading": {"id": "32b48af1-331b-812f-9a97-e66d4c253e8a", "type": "number", "goal": 15, "unit": "minutes"},
    "Hobbies": {"id": "32b48af1-331b-8137-b251-ddb3ae3e88f5", "type": "yes_no", "goal": 1, "unit": "session"},
    "Screen Time": {"id": "32b48af1-331b-812c-8a01-de07e32e0650", "type": "yes_no", "goal": 1, "unit": "under limit"},
}


def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def notion_post(endpoint, body):
    resp = requests.post(f"{NOTION_BASE}{endpoint}", headers=notion_headers(), json=body)
    if not resp.ok:
        error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"message": resp.text}
        raise Exception(f"Notion API error {resp.status_code}: {error.get('message', error)}")
    return resp.json()


def notion_query(database_id, filter_body):
    return notion_post(f"/databases/{database_id}/query", filter_body)


def log_habit(habit_name, value=None, date=None):
    """Log a habit entry to Notion."""
    habit = HABITS.get(habit_name)
    if not habit:
        return {"error": f"Unknown habit: {habit_name}"}

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    if value is None:
        value = 1

    completed = value >= habit["goal"] if habit["type"] == "number" else bool(value)

    body = {
        "parent": {"database_id": HABIT_LOG_DB},
        "properties": {
            "Entry": {"title": [{"text": {"content": f"{habit_name} — {date}"}}]},
            "Date": {"date": {"start": date}},
            "Habit": {"relation": [{"id": habit["id"]}]},
            "Value": {"number": float(value)},
            "Completed": {"checkbox": completed},
        },
    }
    result = notion_post("/pages", body)
    return {"status": "logged", "habit": habit_name, "value": value, "completed": completed, "date": date}


def get_today_entries(date=None):
    """Get all habit entries for a given date."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    result = notion_query(HABIT_LOG_DB, {
        "filter": {"property": "Date", "date": {"equals": date}},
    })

    logged = []
    for page in result.get("results", []):
        props = page["properties"]
        title = props.get("Entry", {}).get("title", [])
        entry_name = title[0]["plain_text"] if title else "Unknown"
        habit_name = entry_name.split(" — ")[0] if " — " in entry_name else entry_name
        value = props.get("Value", {}).get("number", 0)
        completed = props.get("Completed", {}).get("checkbox", False)
        logged.append({"habit": habit_name, "value": value, "completed": completed})

    return {"date": date, "logged": logged}


def get_missing_habits(date=None):
    """Get habits not yet logged for today."""
    entries = get_today_entries(date)
    logged_names = {e["habit"] for e in entries["logged"]}
    missing = [name for name in HABITS if name not in logged_names]
    return {"date": entries["date"], "missing": missing, "logged_count": len(entries["logged"]), "total": len(HABITS)}


def get_weekly_summary():
    """Get completion summary for the past 7 days."""
    today = datetime.now()
    week_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")

    result = notion_query(HABIT_LOG_DB, {
        "filter": {
            "and": [
                {"property": "Date", "date": {"on_or_after": week_start}},
                {"property": "Date", "date": {"on_or_before": week_end}},
            ]
        },
    })

    habit_stats = {name: {"logged": 0, "completed": 0} for name in HABITS}
    for page in result.get("results", []):
        props = page["properties"]
        title = props.get("Entry", {}).get("title", [])
        entry_name = title[0]["plain_text"] if title else ""
        habit_name = entry_name.split(" — ")[0] if " — " in entry_name else ""
        if habit_name in habit_stats:
            habit_stats[habit_name]["logged"] += 1
            if props.get("Completed", {}).get("checkbox", False):
                habit_stats[habit_name]["completed"] += 1

    summary = []
    total_completed = 0
    total_possible = 0
    for name, stats in habit_stats.items():
        rate = round(stats["completed"] / 7 * 100) if stats["logged"] > 0 else 0
        summary.append({"habit": name, "completed": stats["completed"], "days": 7, "rate": rate})
        total_completed += stats["completed"]
        total_possible += 7

    overall_rate = round(total_completed / total_possible * 100) if total_possible > 0 else 0

    return {
        "week_start": week_start,
        "week_end": week_end,
        "habits": summary,
        "overall_rate": overall_rate,
    }


def morning_brief():
    """Get today's habit list and what's already synced."""
    day = datetime.now().strftime("%A")
    entries = get_today_entries()
    logged_names = {e["habit"] for e in entries["logged"]}

    # All daily habits + custom frequency check
    custom_schedule = {
        "Exercise": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "Hobbies": ["Monday", "Wednesday", "Friday", "Saturday", "Sunday"],
    }

    today_habits = []
    for name in HABITS:
        if name in custom_schedule:
            if day in custom_schedule[name]:
                today_habits.append(name)
        else:
            today_habits.append(name)

    pending = [h for h in today_habits if h not in logged_names]
    done = [h for h in today_habits if h in logged_names]

    return {
        "day": day,
        "total_habits": len(today_habits),
        "pending": pending,
        "already_logged": done,
    }


class HabitHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/habits":
            self._send_json({"habits": list(HABITS.keys())})

        elif path == "/today":
            self._send_json(get_today_entries())

        elif path == "/missing":
            self._send_json(get_missing_habits())

        elif path == "/morning":
            self._send_json(morning_brief())

        elif path == "/weekly":
            self._send_json(get_weekly_summary())

        elif path == "/health":
            self._send_json({"status": "ok"})

        else:
            self._send_json({"error": "Not found", "endpoints": [
                "GET /habits", "GET /today", "GET /missing",
                "GET /morning", "GET /weekly", "POST /log",
            ]}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/log":
            body = self._read_body()
            habit_name = body.get("habit")
            value = body.get("value")
            date = body.get("date")

            if not habit_name:
                self._send_json({"error": "Missing 'habit' field"}, 400)
                return

            try:
                result = log_habit(habit_name, value, date)
                if "error" in result:
                    self._send_json(result, 400)
                else:
                    self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        else:
            self._send_json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    if not NOTION_TOKEN:
        print("ERROR: Set NOTION_TOKEN environment variable")
        print("  export NOTION_TOKEN='ntn_...'")
        return

    port = int(os.environ.get("PORT", "8765"))
    server = HTTPServer(("0.0.0.0", port), HabitHandler)
    print(f"Habit Tracker API running on http://localhost:{port}")
    print(f"Endpoints:")
    print(f"  GET  /habits   - List all habits")
    print(f"  GET  /today    - Today's logged entries")
    print(f"  GET  /missing  - Habits not yet logged today")
    print(f"  GET  /morning  - Morning brief")
    print(f"  GET  /weekly   - Weekly summary")
    print(f"  POST /log      - Log a habit (body: {{\"habit\": \"Water\", \"value\": 5}})")
    print()
    print("For iOS Shortcuts, use your Mac's local IP (e.g., http://192.168.x.x:8765)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
