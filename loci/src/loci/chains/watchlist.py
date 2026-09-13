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
FIELDS = (
    "brand", "brand_key", "category", "loci_category", "hq",
    "nyc_locations_now", "nyc_locations_12m_ago", "net_new_12m",
    "pipeline", "ownership", "expansion_role_title", "why_they_grow",
    "evidence", "confidence", "first_added", "last_verified",
)

#: The confidence scale is about PROVENANCE, not certainty:
#:   verified   — a person on this team checked the count. `last_verified` dates it.
#:   reported   — a cited source says so; nobody here re-counted.
#:   unverified — a guess, or seeded to exercise the pipeline.
CONFIDENCE_VALUES = ("verified", "reported", "unverified")

#: Research payloads label confidence on a CERTAINTY scale (high/med/low). The
#: two scales do not line up, so the mapping is deliberately lossy in one
#: direction: an IMPORT CAN NEVER PRODUCE `verified`, because "the model was
#: confident" is not "someone here counted the stores". A curator promotes a row
#: to `verified` by hand, and sets `last_verified` at the same time.
CONFIDENCE_ALIASES = {
    "high": "reported", "medium": "reported", "med": "reported",
    "moderate": "reported", "low": "unverified", "none": "unverified",
}

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
        unknown = set(row) - set(FIELDS)
        if unknown:
            errors.append(f"{where}: unknown field(s) {sorted(unknown)}")
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
