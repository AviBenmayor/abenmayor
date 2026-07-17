"""Bakes the Part 1 position model + venue_cash into static JSON for the
webapp. Run once (or whenever the source CSVs change) from this directory:

    python3 export_data.py

Reuses dashboard/model.py so the numbers come straight from the Part 1
position model — this only changes how the data is served, not how it's
computed.
"""

import json
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[2]  # dashboard/
sys.path.insert(0, str(DASHBOARD_DIR))
from model import load_position_model, load_venue_cash  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
DATA_DIR = str(DASHBOARD_DIR / "data")


def df_to_records(df):
    df = df.copy()
    for col in df.columns:
        if str(df[col].dtype).startswith("datetime"):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return json.loads(df.to_json(orient="records"))


def main() -> None:
    import pandas as pd

    pos = load_position_model(DATA_DIR)
    vc = load_venue_cash(DATA_DIR)
    quotes = pd.read_csv(f"{DATA_DIR}/quotes.csv")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "pos.json").write_text(json.dumps(df_to_records(pos), indent=None))
    (OUT_DIR / "venue_cash.json").write_text(json.dumps(df_to_records(vc), indent=None))
    (OUT_DIR / "quotes.json").write_text(json.dumps(df_to_records(quotes), indent=None))

    print(f"wrote {len(pos)} pos, {len(vc)} venue_cash, {len(quotes)} quotes rows to {OUT_DIR}")


if __name__ == "__main__":
    main()
