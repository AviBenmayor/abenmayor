"""Budget-guarded Google Places (New) Nearby Search client (GTM-11).

Every call is counted in a persisted ledger; when the ledger reaches
LOCI_GOOGLE_CALL_BUDGET the client refuses, and it refuses outright when the
budget is unset. Field mask is the minimum that still tells us what a result is
and where it sits: id, location, types. Adding displayName/rating/hours reprices
the SKU (see GTM-11), so do not widen it casually.

Result cap: Nearby Search returns at most 20 places per call. For the coverage
check that is enough — we compare presence/undercount per category, not
absolute counts in dense food hexes (QUESTIONS.md H-D3).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

import requests

ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = "places.id,places.location,places.types"
LEDGER_PATH = pathlib.Path("data/interim/google_calls.json")

# Loci category -> Google Places (New) Table A types. Mirrors webmap/server.js.
GOOGLE_TYPES: dict[str, list[str]] = {
    "grocery": ["grocery_store", "supermarket"],
    "convenience": ["convenience_store"],
    "pharmacy": ["pharmacy", "drugstore"],
    "laundry": ["laundry"],
    "hair_barber": ["hair_salon", "barber_shop"],
    "nails_beauty": ["nail_salon", "beauty_salon"],
    "tailor_repair": ["tailor"],
    "restaurant": ["restaurant"],
    "cafe_bakery": ["cafe", "bakery", "coffee_shop"],
    "bar": ["bar", "pub"],
    "childcare": ["child_care_agency", "preschool"],
    "clinic": ["doctor", "medical_lab"],
    "fitness": ["gym", "fitness_center"],
    "bank": ["bank"],
    "hardware": ["hardware_store"],
}


class BudgetExhausted(RuntimeError):
    pass


class GooglePlacesClient:
    def __init__(self, api_key: str | None = None, budget: int | None = None,
                 ledger_path: pathlib.Path = LEDGER_PATH, session: requests.Session | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("GOOGLE_PLACES_KEY", "")
        env_budget = os.environ.get("LOCI_GOOGLE_CALL_BUDGET")
        self.budget = budget if budget is not None else (int(env_budget) if env_budget else 0)
        self.ledger_path = pathlib.Path(ledger_path)
        self.session = session or requests.Session()
        self._ledger = self._load()

    # ---- ledger --------------------------------------------------------------
    def _load(self) -> dict:
        if self.ledger_path.exists():
            return json.loads(self.ledger_path.read_text())
        return {"calls": 0, "first_call": None, "last_call": None}

    def _save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(self._ledger, indent=1))

    @property
    def calls_used(self) -> int:
        return int(self._ledger.get("calls", 0))

    @property
    def calls_left(self) -> int:
        return max(0, self.budget - self.calls_used)

    def _charge(self) -> None:
        if self.budget <= 0:
            raise BudgetExhausted("LOCI_GOOGLE_CALL_BUDGET is unset or 0 — refusing to call Google.")
        if self.calls_used >= self.budget:
            raise BudgetExhausted(f"Google call budget exhausted: {self.calls_used}/{self.budget}.")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self._ledger["calls"] = self.calls_used + 1
        self._ledger["first_call"] = self._ledger.get("first_call") or now
        self._ledger["last_call"] = now
        self._save()

    # ---- API ------------------------------------------------------------------
    def nearby_count(self, lat: float, lon: float, category: str, radius_m: int = 800) -> int:
        """Number of places of `category` within `radius_m` (capped at 20 by the API)."""
        types = GOOGLE_TYPES[category]
        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_KEY is not set.")
        self._charge()   # charge BEFORE the request so a crash can't under-count
        body = {"includedTypes": types, "maxResultCount": 20,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                                   "radius": radius_m}}}
        resp = self.session.post(ENDPOINT, json=body, timeout=30,
                                 headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK})
        resp.raise_for_status()
        return len(resp.json().get("places", []))
