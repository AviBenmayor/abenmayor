"""Read, validate and upsert the curated watchlist.

`watchlist.yaml` sits next to this module because config lives with the code
that reads it (cross-project standard). It is HAND-MAINTAINED and it OUTRANKS
detection: a person who looked at a company's site and counted its stores knows
something no open-data heuristic recovers.

--------------------------------------------------------------------------
THE MERGE RULE -- why `import` defaults to never clobbering
--------------------------------------------------------------------------
A research agent will produce 60-120 brands as JSON. Merging that over a file
someone has been hand-correcting is the moment the hand corrections die. So the
default is FILL-ONLY: an incoming value is written only where the existing
value is empty (None, "", [] or a whitespace string). `--overwrite` inverts it
for the fields the incoming record actually carries -- never for fields it
omits, because "absent from the JSON" is not "the curator was wrong".

`first_added` is never overwritten: it dates the row, not the fact.
`evidence` is UNIONed by url rather than replaced, so importing twice does not
lose a citation a person added by hand.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

import yaml

from loci.categories import CATEGORIES
from loci.chains.normalize import brand_key as normalize_brand

PATH = pathlib.Path(__file__).resolve().parent / "watchlist.yaml"

#: Every field a brand row may carry, in the order they are written back out.
#: The DECISION block (tier .. locations_at_decision) was added 2026-09-15 with
#: the auto-admission ruling; every field in it is optional and a row that
#: predates it reads as `tier: admitted, decided_by: owner` (see `tier_of` /
#: `decided_by_of`), which is what the first 161 hand-vetted rows are.
#:
#: The HAND-EVIDENCE block (capital_events .. trajectory_state) was added
#: 2026-09-16 with GTM-189. Every one of those fields is OPTIONAL and is
#: WRITTEN ONLY BY A PERSON: `detect` re-runs a month as a DELETE+INSERT, so a
#: hand fact that lived in chains.brand_snapshot would be destroyed by the next
#: `--month` re-run. They live here because this file is the only artefact in
#: the chain that a machine never rewrites.
FIELDS = (
    "brand", "brand_key", "category", "loci_category", "hq",
    "nyc_locations_now", "nyc_locations_12m_ago", "net_new_12m",
    "pipeline", "ownership", "expansion_role_title", "why_they_grow",
    "evidence", "confidence",
    "tier", "sales_role", "admission_reason", "rejection_reason",
    "decided_on", "decided_by", "locations_at_decision",
    "capital_events", "signed_leases", "store_count_source",
    "expansion_contact_url", "trajectory_state",
    "first_added", "last_verified",
)

#: The confidence scale is about PROVENANCE, not certainty:
#:   verified   — a person on this team checked the count. `last_verified` dates it.
#:   reported   — a cited source says so; nobody here re-counted.
#:   unverified — a guess, or seeded to exercise the pipeline.
#:   auto       — a machine applied the D109 rule and NOBODY HAS LOOKED. It sits
#:                BELOW unverified: an unverified row was at least typed by a
#:                person who meant to type it. Only `loci chains auto-admit`
#:                writes it, and `loci chains render` sorts every auto row into
#:                its own section so the document never mixes the two.
CONFIDENCE_VALUES = ("verified", "reported", "unverified", "auto")

#: Which half of the list a row is in. A `watch` row (D110, tier 3) is INTERNAL
#: ONLY — a one-or-two-location operator with an intent signal — and is neither
#: admitted nor rejected, so it keeps re-surfacing as a candidate until it
#: graduates, which is the intended behaviour.
TIER_VALUES = ("admitted", "watch", "rejected")
DEFAULT_TIER = "admitted"

#: Who the row is for, and where it sorts. See D109's table.
SALES_ROLE_VALUES = ("prospect", "incumbent", "contraction", "excluded")

#: `auto` means the monthly job wrote it unprompted; `owner` means a person
#: typed `loci chains admit` / `reject`. A row with no `decided_by` predates
#: the field and is a hand-curated row, so it reads as `owner`.
DECIDED_BY_VALUES = ("auto", "owner")
DEFAULT_DECIDED_BY = "owner"

#: Confidence values that do not require a citation. `reported` and `verified`
#: are CLAIMS ABOUT A SOURCE and a claim with no evidence is a guess; `auto`
#: and `unverified` already say in the field that nobody checked.
CONFIDENCE_WITHOUT_EVIDENCE = ("auto", "unverified")

#: Research payloads label confidence on a CERTAINTY scale (high/med/low). The
#: two scales do not line up, so the mapping is deliberately lossy in one
#: direction: an IMPORT CAN NEVER PRODUCE `verified`, because "the model was
#: confident" is not "someone here counted the stores". A curator promotes a row
#: to `verified` by hand, and sets `last_verified` at the same time.
CONFIDENCE_ALIASES = {
    "high": "reported", "medium": "reported", "med": "reported",
    "moderate": "reported", "low": "unverified", "none": "unverified",
}

#: ------------------------------------------------------ the hand-evidence block
#:
#: `capital_events` — the events that change what a company IS, which no count
#: can show: the round that funds twenty stores, the acquisition that freezes
#: expansion, the bankruptcy that starts a closure programme. A rejected row
#: re-surfaces on one (candidates._resurface_reason), which is the only reason
#: the shape is constrained at all: the escape hatch compares `date` against
#: `decided_on`, so an entry whose date does not parse silently disables it.
CAPITAL_EVENT_KINDS = ("fundraise", "acquisition", "pe_minority",
                       "franchise_rights", "bankruptcy", "closure_program")
CAPITAL_EVENT_FIELDS = ("kind", "date", "counterparty", "amount", "url")

#: `signed_leases` — the three-stores-with-leases case detect STRUCTURALLY
#: cannot see: a lease is not a filing, not a POI and not a press hit, and the
#: brand is at its old count until the doors open. `address` is what makes the
#: row checkable; without it the entry is a rumour.
SIGNED_LEASE_FIELDS = ("address", "signed_on", "expected_open", "url")

#: Where `nyc_locations_now` came from. It is the PROVENANCE of the number, and
#: `confidence` is the provenance of the row; the two have to agree or the
#: scale means nothing.
STORE_COUNT_SOURCE_VALUES = ("locator", "press", "filing", "hand_count")

#: Only these may support `confidence: verified` (docs/chains-process.md,
#: "Quarterly re-verification"). A press number is a journalist's count and a
#: filing count is a floor off open data — neither is "somebody here counted
#: the stores", which is the entire meaning of `verified`.
VERIFIED_STORE_COUNT_SOURCES = ("hand_count", "locator")

#: A HAND OVERRIDE of the derived trajectory, for the case the deltas cannot
#: see (an acquired chain frozen at its count reads `static`, which is true of
#: the number and false about the company). `unmeasured` is the honest default
#: and the classifier's own answer until four snapshots exist (GTM-190); it is
#: in the vocabulary here so a curator can assert it against a derived label.
TRAJECTORY_STATE_VALUES = ("accelerating", "steady", "decelerating",
                           "declining", "static", "unmeasured")

#: Never overwritten by an import, even with --overwrite.
IMMUTABLE_ON_IMPORT = frozenset({"first_added"})

#: Incoming key -> watchlist field. A research agent writes the field name it
#: found natural, and silently dropping `net_new_nyc_12mo` because this file
#: spells it `net_new_12m` would lose the RANKING COLUMN of the whole document
#: while reporting a clean import. Every alias here was observed in a real
#: payload; `import` reports any key it could not place rather than swallowing
#: it, so a new spelling shows up as a message and not as missing data.
KEY_ALIASES: dict[str, str] = {
    "hq_city": "hq",
    "headquarters": "hq",
    "net_new_nyc_12mo": "net_new_12m",
    "net_new_nyc_12m": "net_new_12m",
    "nyc_locations_12mo_ago": "nyc_locations_12m_ago",
    "evidence_urls": "evidence",
    "real_estate_role": "expansion_role_title",
    "expansion_role": "expansion_role_title",
    "pipeline_notes": "pipeline",
    "notes": "why_they_grow",
}

#: Incoming keys that are deliberately NOT carried into the watchlist: they are
#: the producer's own working notes, and a field nobody maintains rots.
IGNORED_KEYS = frozenset({
    "nyc_locations_now_method", "source_slice", "pipeline_count",
})

#: `loci_category` is the JOIN KEY to the fifteen daily-needs categories, and a
#: research payload writes the retail vocabulary instead ("coffee", "bakery").
#: Only UNAMBIGUOUS synonyms are mapped. Anything else -- "other", "pet",
#: "bookstore", an apparel chain -- becomes NULL, which is correct: those brands
#: are real and worth selling to, they simply have no daily-needs category to
#: join to. The import REPORTS every value it nulled rather than hiding it.
LOCI_CATEGORY_ALIASES = {
    "coffee": "cafe_bakery", "cafe": "cafe_bakery", "bakery": "cafe_bakery",
    "medical": "clinic", "urgent_care": "clinic", "health": "clinic",
    "supermarket": "grocery", "bodega": "convenience", "gym": "fitness",
    "daycare": "childcare", "salon": "hair_barber", "barber": "hair_barber",
    "nails": "nails_beauty",
}


def _is_date(value: Any) -> bool:
    """YYYY-MM-DD, as a string or as a real date. PyYAML parses an unquoted
    2026-09-15 into a `datetime.date`, so both shapes reach this file."""
    if isinstance(value, dt.date):
        return True
    try:
        dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return True


def tier_of(row: dict) -> str:
    """A row with no `tier` is ADMITTED. The 161 rows that predate the field
    were all hand-vetted onto the list; reading a missing tier as anything else
    would silently drop the whole existing watchlist out of the document."""
    return row.get("tier") or DEFAULT_TIER


def decided_by_of(row: dict) -> str:
    """A row with no `decided_by` was written by a person, before the machine
    could write one at all."""
    return row.get("decided_by") or DEFAULT_DECIDED_BY


def is_auto(row: dict) -> bool:
    """True for a row the monthly job admitted and nobody has looked at."""
    return decided_by_of(row) == "auto"


def admitted_keys(doc: dict) -> set[str]:
    """Keys the candidate predicate must not re-surface as new.

    `watch` rows are deliberately NOT here: tier 3 is internal-only and a watch
    row SHOULD re-appear the month it clears the predicate -- that is exactly
    what graduation is (D110)."""
    return {r["brand_key"] for r in doc.get("brands") or []
            if r.get("brand_key") and tier_of(r) == "admitted"}


def rejected_rows(doc: dict) -> dict[str, dict]:
    """{brand_key: row} for rejected rows, so the escape hatch can read
    `locations_at_decision` off the row that recorded the decision."""
    return {r["brand_key"]: r for r in doc.get("brands") or []
            if r.get("brand_key") and tier_of(r) == "rejected"}


def by_key(doc: dict) -> dict[str, dict]:
    return {r["brand_key"]: r for r in doc.get("brands") or [] if r.get("brand_key")}


def near_matches(doc: dict, key: str, n: int = 5) -> list[str]:
    """Close brand_keys, for the message an unknown key gets. A typo in a key
    is the overwhelmingly likely cause, and a bare "not found" makes the user
    grep a 5,000-line YAML to find out they wrote `dunkin donuts`."""
    import difflib

    keys = sorted(by_key(doc))
    hits = difflib.get_close_matches(key, keys, n=n, cutoff=0.6)
    if hits:
        return hits
    # difflib is unhelpful for a short prefix ("blank" vs "blank street
    # coffee"), which is the other way people get a key wrong.
    return [k for k in keys if key and (k.startswith(key) or key in k)][:n]


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def load(path: pathlib.Path | None = None) -> dict:
    doc = yaml.safe_load((path or PATH).read_text()) or {}
    doc.setdefault("version", 1)
    doc.setdefault("brands", [])
    return doc


def brands(path: pathlib.Path | None = None) -> list[dict]:
    return list(load(path).get("brands") or [])


def validate(doc: dict) -> list[str]:
    """Structural errors, as messages. Empty list = valid.

    The load-bearing check is brand_key == normalize(brand): the key is the
    join to chains.brand_snapshot, and a hand-typed key that the normalizer
    would never produce joins to nothing and reports a real chain as invisible."""
    errors: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(doc.get("brands") or []):
        where = f"brands[{i}]"
        name = row.get("brand")
        if not name:
            errors.append(f"{where}: missing `brand`")
            continue
        where = f"{where} ({name})"
        key = row.get("brand_key")
        expected = normalize_brand(name)
        if not key:
            errors.append(f"{where}: missing `brand_key` (expected {expected!r})")
        elif key != expected:
            errors.append(f"{where}: brand_key {key!r} != normalize(brand) {expected!r} "
                          "— it would join to nothing in chains.brand_snapshot")
        elif key in seen:
            errors.append(f"{where}: duplicate brand_key {key!r}")
        if key:
            seen.add(key)
        lc = row.get("loci_category")
        if lc and lc not in CATEGORIES:
            errors.append(f"{where}: loci_category {lc!r} is not one of {sorted(CATEGORIES)}")
        conf = row.get("confidence")
        if conf and conf not in CONFIDENCE_VALUES:
            errors.append(f"{where}: confidence {conf!r} not in {CONFIDENCE_VALUES}")
        for ev in row.get("evidence") or []:
            if not isinstance(ev, dict) or "url" not in ev:
                errors.append(f"{where}: evidence entries need a `url`, got {ev!r}")
        # An EMPTY evidence list is allowed only where the confidence field
        # already says nobody checked. `confidence: auto` is the case this was
        # written for: the monthly job admits rows off a count and has no
        # citation to give, and forcing it to invent one would be worse.
        if not (row.get("evidence") or []) and conf \
                and conf not in CONFIDENCE_WITHOUT_EVIDENCE:
            errors.append(f"{where}: no `evidence` but confidence is {conf!r} — "
                          f"only {list(CONFIDENCE_WITHOUT_EVIDENCE)} may cite nothing")
        tier = row.get("tier")
        if tier and tier not in TIER_VALUES:
            errors.append(f"{where}: tier {tier!r} not in {TIER_VALUES}")
        role = row.get("sales_role")
        if role and role not in SALES_ROLE_VALUES:
            errors.append(f"{where}: sales_role {role!r} not in {SALES_ROLE_VALUES}")
        by = row.get("decided_by")
        if by and by not in DECIDED_BY_VALUES:
            errors.append(f"{where}: decided_by {by!r} not in {DECIDED_BY_VALUES}")
        for datefield in ("decided_on", "first_added", "last_verified"):
            value = row.get(datefield)
            if value and not _is_date(value):
                errors.append(f"{where}: {datefield} {value!r} is not YYYY-MM-DD")
        errors += _validate_hand_evidence(row, where)
        n_at = row.get("locations_at_decision")
        if n_at is not None and not isinstance(n_at, int):
            # The doubling escape hatch reads this number. A string here would
            # compare wrong and silently disable the re-surface for that row.
            errors.append(f"{where}: locations_at_decision {n_at!r} is not an integer")
        unknown = set(row) - set(FIELDS)
        if unknown:
            errors.append(f"{where}: unknown field(s) {sorted(unknown)}")
    return errors


def _validate_hand_evidence(row: dict, where: str) -> list[str]:
    """The GTM-189 hand-entered block, field by field.

    Every check here exists because the field is READ by something, not because
    a schema felt tidy:

      * `capital_events[].date` is compared against `decided_on` by the
        candidates escape hatch. An unparseable date there does not raise —
        it silently means "no capital event", which is a rejected brand
        staying invisible after the news that should have re-opened it.
      * `kind` is an enum so the same event is not filed as `pe_minority` on
        one row and "PE deal" on the next; nothing can group free text.
      * `store_count_source` gates `confidence: verified`. A `verified` row
        with no counted source is the exact claim the confidence scale exists
        to prevent, so this is an ERROR and not a warning.
    """
    errors: list[str] = []

    events = row.get("capital_events")
    if events is not None:
        if not isinstance(events, list):
            errors.append(f"{where}: capital_events must be a list, got "
                          f"{type(events).__name__}")
        else:
            for j, ev in enumerate(events):
                at = f"{where}: capital_events[{j}]"
                if not isinstance(ev, dict):
                    errors.append(f"{at}: must be a mapping, got {ev!r}")
                    continue
                kind = ev.get("kind")
                if kind not in CAPITAL_EVENT_KINDS:
                    errors.append(f"{at}: kind {kind!r} not in {CAPITAL_EVENT_KINDS}")
                if not _is_date(ev.get("date")):
                    # Required, not optional: an undated capital event cannot
                    # be compared to a rejection date, so it can never re-open
                    # a row, which is the one job the field has.
                    errors.append(f"{at}: date {ev.get('date')!r} is not YYYY-MM-DD "
                                  "— an undated capital event can never re-surface "
                                  "a rejected brand")
                for field in ("counterparty", "amount", "url"):
                    value = ev.get(field)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"{at}: {field} must be a string, got {value!r}")
                unknown = set(ev) - set(CAPITAL_EVENT_FIELDS)
                if unknown:
                    errors.append(f"{at}: unknown key(s) {sorted(unknown)}")

    leases = row.get("signed_leases")
    if leases is not None:
        if not isinstance(leases, list):
            errors.append(f"{where}: signed_leases must be a list, got "
                          f"{type(leases).__name__}")
        else:
            for j, lease in enumerate(leases):
                at = f"{where}: signed_leases[{j}]"
                if not isinstance(lease, dict):
                    errors.append(f"{at}: must be a mapping, got {lease!r}")
                    continue
                if _empty(lease.get("address")):
                    errors.append(f"{at}: missing `address` — a lease with no "
                                  "address is a rumour, not a signed lease")
                for field in ("signed_on", "expected_open"):
                    value = lease.get(field)
                    if value is not None and not _is_date(value):
                        errors.append(f"{at}: {field} {value!r} is not YYYY-MM-DD")
                url = lease.get("url")
                if url is not None and not isinstance(url, str):
                    errors.append(f"{at}: url must be a string, got {url!r}")
                unknown = set(lease) - set(SIGNED_LEASE_FIELDS)
                if unknown:
                    errors.append(f"{at}: unknown key(s) {sorted(unknown)}")

    src = row.get("store_count_source")
    if src is not None and src not in STORE_COUNT_SOURCE_VALUES:
        errors.append(f"{where}: store_count_source {src!r} not in "
                      f"{STORE_COUNT_SOURCE_VALUES}")

    if row.get("confidence") == "verified" and src not in VERIFIED_STORE_COUNT_SOURCES:
        errors.append(
            f"{where}: confidence 'verified' needs store_count_source in "
            f"{list(VERIFIED_STORE_COUNT_SOURCES)}, got {src!r} — `verified` "
            "means somebody here counted the stores, and a press or filing "
            "number is not a count")

    url = row.get("expansion_contact_url")
    if url is not None and not isinstance(url, str):
        errors.append(f"{where}: expansion_contact_url must be a string, got {url!r}")

    state = row.get("trajectory_state")
    if state is not None and state not in TRAJECTORY_STATE_VALUES:
        errors.append(f"{where}: trajectory_state {state!r} not in "
                      f"{TRAJECTORY_STATE_VALUES}")
    return errors


def _merge_evidence(existing: list, incoming: list) -> list:
    """Union by url, existing first. Importing twice never drops a hand-added
    citation and never duplicates one."""
    out = list(existing or [])
    have = {e.get("url") for e in out if isinstance(e, dict)}
    for e in incoming or []:
        if isinstance(e, dict) and e.get("url") and e["url"] not in have:
            out.append(e)
            have.add(e["url"])
    return out


def normalize_record(raw: dict) -> tuple[dict, set[str], set[str]]:
    """One incoming record mapped onto FIELDS.

    Returns (record, unplaced keys, dropped loci_category values).

    `evidence` accepts either the full [{url, date}] shape or a bare list of
    url strings, because both are natural things for a producer to write."""
    record: dict = {}
    unplaced: set[str] = set()
    dropped_cats: set[str] = set()
    for key, value in raw.items():
        field = key if key in FIELDS else KEY_ALIASES.get(key)
        if field is None:
            if key not in IGNORED_KEYS:
                unplaced.add(key)
            continue
        if field == "evidence" and isinstance(value, list):
            value = [e if isinstance(e, dict) else {"url": str(e)} for e in value]
        if field == "confidence" and isinstance(value, str):
            value = CONFIDENCE_ALIASES.get(value.strip().lower(), value)
        if field == "loci_category" and isinstance(value, str):
            slug = value.strip().lower()
            slug = LOCI_CATEGORY_ALIASES.get(slug, slug)
            if slug not in CATEGORIES:
                dropped_cats.add(value)
                slug = None
            value = slug
        if field in record and not _empty(record[field]):
            continue                  # an explicit field wins over its alias
        record[field] = value
    return record, unplaced, dropped_cats


def upsert(doc: dict, incoming: list[dict], *, overwrite: bool = False,
           today: dt.date | None = None) -> tuple[dict, dict]:
    """Merge `incoming` records into `doc`. Returns (doc, counts).

    Each incoming record is matched on `brand_key`, deriving it from `brand`
    when absent so a research JSON need not know the normalizer."""
    today = today or dt.date.today()
    by_key = {}
    for row in doc.get("brands") or []:
        if row.get("brand_key"):
            by_key[row["brand_key"]] = row

    added = updated = skipped = 0
    unplaced: set[str] = set()
    dropped_cats: set[str] = set()
    for raw in incoming:
        record, missed, cats = normalize_record(raw)
        unplaced |= missed
        dropped_cats |= cats
        name = record.get("brand")
        key = record.get("brand_key") or (normalize_brand(name) if name else None)
        if not key:
            skipped += 1
            continue
        record["brand_key"] = key

        target = by_key.get(key)
        if target is None:
            target = {f: None for f in FIELDS}
            target.update({"brand_key": key, "evidence": [],
                           "first_added": today.isoformat()})
            doc.setdefault("brands", []).append(target)
            by_key[key] = target
            added += 1
            fill_all = True
        else:
            updated += 1
            fill_all = False

        for field, value in record.items():
            if field in IMMUTABLE_ON_IMPORT and not fill_all:
                continue
            if field == "evidence":
                target["evidence"] = _merge_evidence(target.get("evidence"), value)
                continue
            if _empty(value):
                continue
            if fill_all or overwrite or _empty(target.get(field)):
                target[field] = value

    doc["updated_on"] = today.isoformat()
    return doc, {"added": added, "updated": updated, "skipped": skipped,
                 "unplaced_keys": sorted(unplaced),
                 "dropped_categories": sorted(dropped_cats)}


# ---------------------------------------------------------------------------
# THE DECISION WRITERS -- `loci chains admit` / `reject` / `auto-admit`
#
# Same discipline as `upsert`: these write the DECISION block and nothing else.
# A decision is not a correction, so admitting a brand must never overwrite the
# hand-checked count, category or evidence a curator put on the row -- the two
# kinds of fact have different owners and different lifetimes.
# ---------------------------------------------------------------------------

def decide(doc: dict, key: str, *, tier: str, reason: str,
           today: dt.date | None = None, sales_role: str | None = None,
           confidence: str | None = None,
           locations_at_decision: int | None = None,
           decided_by: str = "owner") -> dict:
    """Record a tier decision on an EXISTING row. Returns the row.

    Raises KeyError for an unknown brand_key -- the caller is expected to turn
    that into a message listing `near_matches`. Creating the row instead would
    be the wrong kindness: a brand nobody has seen belongs in the queue through
    `auto-admit`, where it arrives with its detect counts attached, not typed
    from memory at a prompt.

    PROMOTION. `admit` on a row the machine wrote flips `decided_by` to
    `owner` and leaves `confidence` alone unless one is passed: promotion means
    a person has now looked, which is a fact about the DECISION; whether anyone
    counted the stores is a separate fact about the NUMBER, and conflating them
    is how a row ends up reading `verified` because somebody clicked yes.

    REJECTION KEEPS THE ROW. It is not deleted: a deleted rejection is a brand
    that comes back next month with nothing recorded against it, which is the
    failure the tier exists to prevent."""
    if tier not in TIER_VALUES:
        raise ValueError(f"tier {tier!r} not in {TIER_VALUES}")
    if sales_role is not None and sales_role not in SALES_ROLE_VALUES:
        raise ValueError(f"sales_role {sales_role!r} not in {SALES_ROLE_VALUES}")
    today = today or dt.date.today()
    row = by_key(doc).get(key)
    if row is None:
        raise KeyError(key)

    row["tier"] = tier
    if tier == "rejected":
        row["rejection_reason"] = reason
    else:
        row["admission_reason"] = reason
    row["decided_on"] = today.isoformat()
    row["decided_by"] = decided_by
    if confidence is not None:
        if confidence not in CONFIDENCE_VALUES:
            raise ValueError(f"confidence {confidence!r} not in {CONFIDENCE_VALUES}")
        row["confidence"] = confidence
    if sales_role is not None:
        row["sales_role"] = sales_role
    elif _empty(row.get("sales_role")) and tier == "admitted":
        row["sales_role"] = "prospect"
    if locations_at_decision is not None:
        row["locations_at_decision"] = int(locations_at_decision)
    elif row.get("locations_at_decision") is None \
            and isinstance(row.get("nyc_locations_now"), int):
        # The escape hatch needs A NUMBER at the moment of the decision. The
        # curated count is the best one available when no snapshot was read;
        # with neither, the doubling arm is simply dormant for this row, which
        # `loci chains reject` says out loud rather than leaving to be found.
        row["locations_at_decision"] = int(row["nyc_locations_now"])
    for field in FIELDS:
        row.setdefault(field, None)
    doc["updated_on"] = today.isoformat()
    return row


def auto_admit(doc: dict, candidates: list[dict], *, month: str | None = None,
               today: dt.date | None = None,
               limit: int = 0) -> tuple[dict, list[dict], list[str]]:
    """Write one row per candidate the owner has not already decided on.

    The 2026-09-15 owner ruling: the monthly job admits everything that clears
    the predicate and the owner rejects after the fact. Returns
    (doc, added rows, skipped messages).

    THE COUNT IS NOT WRITTEN TO `nyc_locations_now`. That field means "a person
    counted this"; detect's number is a floor off open data and putting it
    there would manufacture 900 curated counts nobody produced. It goes to
    `locations_at_decision` (where the escape hatch reads it) and into the
    prose of `admission_reason` (where a reader sees it with its provenance).

    NEVER TOUCHES AN EXISTING ROW -- not a hand-vetted one, not a rejected one,
    not one this job wrote last month. An existing key is skipped in silence by
    the predicate upstream; anything reaching here that already exists is a
    bug, and is reported rather than merged."""
    today = today or dt.date.today()
    existing = by_key(doc)
    added: list[dict] = []
    skipped: list[str] = []

    for cand in candidates:
        if limit and len(added) >= limit:
            break
        key = cand.get("brand_key")
        if not key:
            skipped.append(f"{cand.get('display_name')!r}: no brand_key")
            continue
        if key in existing:
            skipped.append(f"{key}: already on the watchlist — not touched")
            continue

        # `brand` MUST normalize back to `brand_key` or validate() fails and
        # the row would join to nothing. display_name is the modal raw
        # spelling of a group whose members all normalize to this key, so it
        # normally does; the fallback keeps a pathological one out of the file
        # rather than writing an invalid row.
        display = cand.get("display_name") or key
        brand = display if normalize_brand(display) == key else key
        if normalize_brand(brand) != key:
            skipped.append(f"{key}: no display name normalizes back to the key")
            continue

        cat = cand.get("loci_category")
        if cat not in CATEGORIES:
            cat = None
        total = int(cand.get("locations_total") or 0)
        new_12m = int(cand.get("locations_new_12m") or 0)
        reason = cand.get("reason") or "cleared the D109 candidate predicate"
        detect_note = f"detect {month}: {total} locations, {new_12m} new 12m" \
            if month else f"detect: {total} locations, {new_12m} new 12m"

        row = {f: None for f in FIELDS}
        row.update({
            "brand": brand,
            "brand_key": key,
            "category": None,               # the company's own word; nobody asked it
            "loci_category": cat,
            "nyc_locations_now": None,      # null means NOT COUNTED, never zero
            "evidence": [],                 # allowed only because confidence is `auto`
            "confidence": "auto",
            "tier": "admitted",
            "sales_role": cand.get("sales_role") or "prospect",
            "admission_reason": f"{reason}; {detect_note}",
            "decided_on": today.isoformat(),
            "decided_by": "auto",
            "locations_at_decision": total,
            "first_added": today.isoformat(),
        })
        doc.setdefault("brands", []).append(row)
        existing[key] = row
        added.append(row)

    if added:
        doc["updated_on"] = today.isoformat()
    return doc, added, skipped


def dump(doc: dict, path: pathlib.Path | None = None, *, header: str | None = None) -> str:
    """Serialize, preserving the file's comment header by default.

    PyYAML drops comments, and the header of watchlist.yaml is the field
    documentation a curator reads before editing. It is re-attached verbatim."""
    target = path or PATH
    if header is None and target.exists():
        header = _leading_comment(target.read_text())
    ordered = {
        "version": doc.get("version", 1),
        "updated_on": doc.get("updated_on"),
        "brands": [{f: row.get(f) for f in FIELDS} for row in doc.get("brands") or []],
    }
    body = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=88)
    return f"{header}\n{body}" if header else body


def write(doc: dict, path: pathlib.Path | None = None) -> pathlib.Path:
    target = path or PATH
    target.write_text(dump(doc, target))
    return target


def _leading_comment(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
            if lines and not line.startswith("#") and any(x.startswith("#") for x in lines):
                break
        else:
            break
    return "\n".join(lines).rstrip()
