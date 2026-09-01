"""End-to-end: raw pack -> submission.csv, the browser tool, and everything the
dashboard serves -- in dependency order, from one command.

export_model.py comes first and is the only script that writes output/submission.csv.
Everything downstream reads output/model.json and asserts it agrees, so the dashboard
cannot end up routing leads differently from the file we submit.
"""
import subprocess, sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
STEPS = ["build_dataset.py", "export_model.py", "build_tool.py",
         "score_leads.py", "capacity_and_tiers.py", "build_app_data.py"]

for step in STEPS:
    print(f"\n{'#' * 78}\n# {step}\n{'#' * 78}")
    r = subprocess.run([sys.executable, str(SRC / step)], env={**__import__("os").environ,
                                                               "PYTHONPATH": str(SRC)})
    if r.returncode:
        sys.exit(f"FAILED: {step}")
print("\nall steps ok")
