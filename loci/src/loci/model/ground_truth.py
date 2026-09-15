"""`loci ground-truth` -- WHAT IS PHYSICALLY AT THE ANCHOR, checked by a human
on Google Maps / Street View, and stored (D105).

Every other instrument in this project reads a FEED. `analysis.poi_presence`
knows what Overture, OSM, Foursquare, SNAP, DOHMH, DCWP, SLA and DOS published;
`analysis.address_category` turns that into "nothing of this category within
reach"; `analysis.recommendation` turns THAT into a dated claim. Nothing in the
chain has ever looked at the doorway. This module is the channel that does: a
human-supervised browser session opens the anchor on Maps and Street View,
writes down every storefront it can see, and the observation lands here.

---------------------------------------------------------------------------
WHY THE OBSERVATION IS THE OUTPUT, NOT THE VERDICT
---------------------------------------------------------------------------
The load-bearing row is `analysis.address_observation_miss`: an OPEN storefront
of the recommended category, standing at an anchor where the supply model says
there is nothing. That row is not a data-entry error, it is a MEASURED FALSE
POSITIVE of the screen -- the exact quantity D90's coverage validation had to
estimate by design-weighted sampling, here observed directly at the fifteen
places the project actually staked a claim on.

So the row is stored whatever it says, including when it says nothing.

D79 IN FULL. An empty `storefronts` list writes ONE row with
`storefront_name IS NULL` and `status='vacant'`. "We looked and saw nothing"
is an observation and is recorded; it is never inferred from the absence of a
row, and a rec with no row at all still reads "not yet checked". The two are
different states and the table can tell them apart.

---------------------------------------------------------------------------
THE EVIDENCE ROW, AND WHY IT IS source='web', domain_class='maps_ui'
---------------------------------------------------------------------------
When an observed storefront MATCHES a known POI and the observer read a status
off the Maps card ('open' / 'closed'), that is closure evidence and belongs in
`analysis.poi_closure_evidence` beside the Places and web channels, so
`poi_status` picks it up through the one precedence rule in
`model/poi_evidence.py` rather than through a second one written here.

It is written with `source='web'` and `domain_class='maps_ui'`, NOT a new
`source` value. sql/033's `source` column carries
`CHECK (source IN ('places','web'))`, DuckDB 1.5.5 implements neither
`ALTER TABLE ... DROP CONSTRAINT` nor `ADD CONSTRAINT` (probed, 2026-09-14),
and the only other way to widen it is a create-copy-swap of a table that
concurrent sessions are writing -- `db.init_schema` applies every .sql file on
disk, including uncommitted ones, so a swap would fire inside a peer's session
at a moment nobody chose. The provenance is not lost: `domain_class` is
exactly the field sql/033 reserves for "which KIND of web source", `basis()`
renders it as `web_evidence:<verdict>:maps_ui:<date>:<url>`, and `query` is
`ground-truth <rec_id>`, so every such row is recoverable with one predicate.

ONE RULE DOES CHANGE SHAPE HERE, DELIBERATELY: `evidence/web_rules.py` refuses
to ever emit 'open', because a page that does not say "closed" is not evidence
that a business is trading. That reasoning is about SEARCH HITS. A person
looking at a storefront on Street View and reading "Open" off its Maps card is
a POSITIVE observation of the thing itself, and it is allowed to say 'open'.
What is still forbidden is the inference this module never makes: 'vacant' and
'unknown' write NO evidence row at all. Seeing nothing is not seeing a closure.

---------------------------------------------------------------------------
IDEMPOTENCE
---------------------------------------------------------------------------
`observation_id = sha1(rec_id | observed_at | storefront_name)` and the insert
is INSERT OR REPLACE, so re-ingesting the same JSONL file changes nothing. The
evidence rows are idempotent already, by sql/033's own
`evidence_id = sha1(poi_id|source|url)` rule. A SECOND observation session on
the same anchor is a different `observed_at` and therefore new rows -- which is
right: it is a second observation, not a correction of the first.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from loci import db as locidb
from loci.categories import CATEGORIES
from loci.db import METRES_SQL
from loci.model import poi_evidence as pe
from loci.model import poi_presence as pp

SQL_036 = locidb.SQL_DIR / "036_address_observation.sql"

#: Match radius for "is this observed storefront a POI we already hold". The
#: SAME number the `analysis.address_observation_miss` view uses -- sql/036
#: writes it literally and tests/test_ground_truth.py pins the two together.
#: 40 m, not the 400 m catchment radius used everywhere else: this is not
#: "within walking distance of the anchor", it is "this is the same doorway",
#: and a geocode that is a building-width off should still match.
MATCH_RADIUS_M = 40.0

#: `domain_class` marking an evidence row as a human's reading of the Google
#: Maps UI. See the module docstring for why this is not a `source` value.
MAPS_DOMAIN_CLASS = "maps_ui"
MAPS_SOURCE_NAME = "Google Maps (browser, human-supervised)"

#: The link key, re-exported rather than re-derived: an observed name must
#: normalize through EXACTLY the function that minted `poi_presence.name_key`,
#: or the match silently never fires.
name_key = pp.name_key_of

STATUSES = ("open", "closed", "vacant", "unknown")
GAP_VERDICTS = ("confirmed_gap", "supply_missed", "closure_missed", "inconclusive")

#: The statuses that are a POSITIVE reading of a business's state and may
#: therefore become closure evidence. 'vacant' and 'unknown' are absence and
#: never do (D79).
EVIDENCE_STATUSES = ("open", "closed")


# --------------------------------------------------------------- the URLs

def maps_url(lat: float, lon: float) -> str:
    """The anchor on Google Maps. Search-by-coordinate, not a place id: we do
    not know the place yet -- finding out what is there is the whole job."""
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"


def streetview_url(lat: float, lon: float) -> str:
    """The anchor in Street View. `map_action=pano` with a `viewpoint` snaps to
    the nearest panorama, whose capture month the observer records in
    `streetview_capture_date` -- imagery two years old is a real limit on what
    an observation can claim, and it is only knowable at observation time."""
    return (f"https://www.google.com/maps/@?api=1&map_action=pano"
            f"&viewpoint={lat},{lon}")


# --------------------------------------------------------------- plumbing

def ensure_schema(con) -> None:
    """Apply sql/036, plus the files whose objects it reads.

    sql/036's view references `analysis.poi_presence` (018) and its rows
    reference `analysis.recommendation` (026); `record()` also writes
    `analysis.poi_closure_evidence` (033). Applying 036 alone onto a bare
    warehouse fails at the view, so the dependencies are applied here rather
    than left to the caller to remember -- the `poi_presence.ensure_schema`
    pattern, and the f8142e0 lesson about a migration that needs another one
    to have run first.

    sql/036 does NOT alter any object sql/033 created, so there is no
    re-application ordering to hold here: 033 before 036 is enough. WRITE-ONLY
    (DuckDB refuses CREATE on a read-only connection); read paths call
    `require_schema`.
    """
    pp.ensure_schema(con)                       # 018 + 027
    from loci.model.recommendation_ledger import SQL_026
    con.execute(SQL_026.read_text())
    sql_033 = locidb.SQL_DIR / "033_poi_closure_evidence.sql"
    if sql_033.exists():
        con.execute(sql_033.read_text())
    con.execute(SQL_036.read_text())


def require_schema(con) -> None:
    """Fail with a runnable instruction, not a DuckDB Catalog Error. The read
    paths (`plan`, `summary`) must work on a read-only connection."""
    try:
        con.execute("SELECT 1 FROM analysis.address_observation LIMIT 1")
    except Exception as exc:                    # noqa: BLE001 -- duckdb raises several
        raise RuntimeError(
            "analysis.address_observation does not exist yet. Run "
            "`loci ground-truth record <file.jsonl>`, which applies "
            "sql/036_address_observation.sql.") from exc


def _dist_sql(lon_expr: str, lat_expr: str) -> str:
    """Metres from (`lon_expr`, `lat_expr`) to a bound `(?, ?)` point. D16:
    DuckDB's ST_Distance_Sphere reads POINT(x, y) as (lat, lon), so both sides
    are flipped -- via `db.METRES_SQL`, never by hand."""
    return METRES_SQL.format(a=f"ST_Point({lon_expr}, {lat_expr})",
                             b="ST_Point(?, ?)")


# ------------------------------------------------------------------- plan

def plan(con, limit: int | None = None, category: str | None = None) -> list[dict]:
    """The manifest a browser session works through: one entry per OPEN
    recommendation, carrying the two URLs to open and the claim to check.

    OPEN ONLY, on purpose. A withdrawn recommendation is a claim we retracted
    and a filled one already has its answer; spending a human's attention on
    either buys nothing. An anchorless recommendation (no anchor_lon/lat --
    an NTA-wide card) is skipped too: there is no doorway to stand at.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; "
                         f"one of {sorted(CATEGORIES)}")
    where, params = ["r.status = 'open'",
                     "r.anchor_lon IS NOT NULL", "r.anchor_lat IS NOT NULL"], []
    if category:
        where.append("r.category = ?")
        params.append(category)
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    rows = con.execute(f"""
        SELECT r.rec_id, r.anchor_address_id, r.area_label, r.area_id,
               r.anchor_lon, r.anchor_lat, r.category, r.proposed_solution,
               r.grade, r.issued_on
        FROM analysis.recommendation r
        WHERE {' AND '.join(where)}
        ORDER BY r.issued_on DESC, r.category, r.rec_id
        {limit_sql}
    """, params).fetchall()

    # The address labels in ONE lookup keyed by the ids we actually have --
    # `analysis.address` is the largest table in the warehouse and its primary
    # key is (borough, address_id), so a LEFT JOIN on address_id alone would
    # scan it whether or not any anchor is an address.
    ids = sorted({r[1] for r in rows if r[1]})
    labels: dict[str, str] = {}
    if ids:
        ph = ", ".join("?" for _ in ids)
        for aid, street, hood, boro in con.execute(
                f"SELECT address_id, street_name, neighborhood, borough "
                f"FROM analysis.address WHERE address_id IN ({ph})", ids).fetchall():
            parts = [p for p in (street, hood, boro) if p]
            labels[aid] = " — ".join(parts) if parts else aid

    out = []
    for (rec_id, aid, area_label, area_id, lon, lat, cat, solution,
         grade, issued_on) in rows:
        out.append({
            "rec_id": rec_id,
            "anchor_address_id": aid,
            "address_label": labels.get(aid) or area_label or area_id,
            "anchor_lon": lon,
            "anchor_lat": lat,
            "category": cat,
            "proposed_solution": solution,
            "grade": grade,
            "issued_on": issued_on.isoformat() if hasattr(issued_on, "isoformat")
                         else issued_on,
            "maps_url": maps_url(lat, lon),
            "streetview_url": streetview_url(lat, lon),
        })
    return out


def write_manifest(entries: list[dict], path: pathlib.Path | str) -> pathlib.Path:
    """Manifest JSON for the browser session. Carries `observation_schema` so
    the session writing the JSONL back does not have to be told the shape in
    prose that can drift from `record()`."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_anchors": len(entries),
        "match_radius_m": MATCH_RADIUS_M,
        "observation_schema": {
            "rec_id": "str, from this manifest",
            "observed_at": "ISO-8601 timestamp",
            "observer": "str",
            "maps_url": "str", "streetview_url": "str|null",
            "streetview_capture_date": "str|null, Google's imagery month e.g. '2025-06'",
            "screenshot_path": "str|null",
            "storefronts": [{"name": "str",
                             "category_guess": f"one of {sorted(CATEGORIES)} or null",
                             "status": "|".join(STATUSES),
                             "maps_status_label": "str|null, the raw label text",
                             "notes": "str|null"}],
            "gap_verdict": "|".join(GAP_VERDICTS),
            "notes": "str|null",
        },
        "anchors": entries,
    }, indent=2) + "\n")
    return p


# ----------------------------------------------------------------- record

@dataclass
class RecordResult:
    run_id: str
    n_records: int = 0
    n_rows: int = 0
    n_vacant_rows: int = 0
    n_matched: int = 0
    n_evidence: int = 0
    rec_ids: list[str] = field(default_factory=list)


def observation_id(rec_id: str, observed_at: str, storefront_name: str | None) -> str:
    payload = f"{rec_id}|{observed_at}|{storefront_name or ''}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def load_jsonl(path: pathlib.Path | str) -> list[dict]:
    """One JSON object per line; blank lines skipped."""
    out = []
    for i, line in enumerate(pathlib.Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{i}: not valid JSON -- {exc}") from exc
    return out


def _parse_dt(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    return dt.datetime.fromisoformat(s)


def _anchor(con, rec_id: str) -> dict:
    row = con.execute(
        "SELECT anchor_address_id, anchor_lon, anchor_lat, category "
        "FROM analysis.recommendation WHERE rec_id = ?", [rec_id]).fetchone()
    if row is None:
        raise ValueError(
            f"rec_id {rec_id!r} is not in analysis.recommendation. An "
            f"observation is a check OF a dated claim; there is nothing to "
            f"attach this one to.")
    if row[1] is None or row[2] is None:
        raise ValueError(f"rec_id {rec_id!r} has no anchor point to observe.")
    return {"anchor_address_id": row[0], "anchor_lon": row[1],
            "anchor_lat": row[2], "category": row[3]}


def _match(con, name_key: str, lon: float, lat: float):
    """The nearest `analysis.poi_presence` location with the SAME name_key
    within `MATCH_RADIUS_M`, ANY category. Any category on purpose: an
    observed hardware store that the warehouse holds under `convenience` is a
    category error, not a missing POI, and conflating the two would let a
    mis-typed POI be reported as supply the model never had."""
    if not name_key:
        return None, None
    d = _dist_sql("p.lon", "p.lat")
    row = con.execute(f"""
        SELECT p.poi_id_latest, {d} AS distance_m
        FROM analysis.poi_presence p
        WHERE p.name_key = ?
          AND p.lon IS NOT NULL AND p.lat IS NOT NULL
          AND {d} <= ?
        ORDER BY distance_m
        LIMIT 1
    """, [lon, lat, name_key, lon, lat, MATCH_RADIUS_M]).fetchone()
    if row is None:
        return None, None
    return row[0], float(row[1])


def _validate(rec: dict, sf: dict) -> None:
    status = sf.get("status")
    if status not in STATUSES:
        raise ValueError(f"{rec.get('rec_id')}: storefront status {status!r} "
                         f"must be one of {STATUSES}")
    guess = sf.get("category_guess")
    if guess is not None and guess not in CATEGORIES:
        raise ValueError(f"{rec.get('rec_id')}: category_guess {guess!r} is not "
                         f"a loci category; one of {sorted(CATEGORIES)}")


def record(con, observations: Iterable[dict], run_id: str | None = None) -> RecordResult:
    """Ingest observation records (see the module docstring for the shape) and
    write `analysis.address_observation`, plus a `maps_ui` closure-evidence row
    for every MATCHED storefront the observer read a positive status off.

    Validation is UP FRONT and fatal: a bad status or a category_guess that is
    not a loci category stops the whole file rather than landing a partial
    ingest that the CHECK constraints would reject halfway through.
    """
    run_id = run_id or uuid.uuid4().hex
    res = RecordResult(run_id=run_id)
    now = dt.datetime.now()

    for obs in observations:
        rec_id = obs["rec_id"]
        anchor = _anchor(con, rec_id)
        observed_at = _parse_dt(obs["observed_at"])
        observed_key = observed_at.isoformat()
        verdict = obs.get("gap_verdict")
        if verdict not in GAP_VERDICTS:
            raise ValueError(f"{rec_id}: gap_verdict {verdict!r} must be one "
                             f"of {GAP_VERDICTS}")
        storefronts = list(obs.get("storefronts") or [])
        for sf in storefronts:
            _validate(obs, sf)

        # An empty list is "we looked and saw nothing" and gets ONE row, with a
        # NULL name -- absence RECORDED, never inferred (D79). A rec with no
        # row at all still reads "not yet checked"; the two are different.
        rows = storefronts or [{"name": None, "category_guess": None,
                                "status": "vacant", "maps_status_label": None,
                                "notes": None}]

        for sf in rows:
            name = sf.get("name")
            name_key = pp.name_key_of(name) if name else None
            matched_poi_id, distance_m = (
                _match(con, name_key, anchor["anchor_lon"], anchor["anchor_lat"])
                if name_key else (None, None))
            oid = observation_id(rec_id, observed_key, name)
            con.execute("""
                INSERT OR REPLACE INTO analysis.address_observation
                (observation_id, rec_id, anchor_address_id, anchor_lon, anchor_lat,
                 category, observed_at, observer, maps_url, streetview_url,
                 streetview_capture_date, screenshot_path, storefront_name, name_key,
                 category_guess, status, maps_status_label, matched_poi_id,
                 match_distance_m, gap_verdict, notes, raw, run_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?)
            """, [oid, rec_id, anchor["anchor_address_id"], anchor["anchor_lon"],
                  anchor["anchor_lat"], anchor["category"], observed_at,
                  obs.get("observer"), obs.get("maps_url"), obs.get("streetview_url"),
                  obs.get("streetview_capture_date"), obs.get("screenshot_path"),
                  name, name_key, sf.get("category_guess"), sf["status"],
                  sf.get("maps_status_label"), matched_poi_id, distance_m,
                  verdict, sf.get("notes") or obs.get("notes"),
                  json.dumps(sf), run_id, now])
            res.n_rows += 1
            if name is None:
                res.n_vacant_rows += 1
            if matched_poi_id:
                res.n_matched += 1

            # Closure evidence ONLY from a positive reading of a MATCHED POI.
            # No match -> there is no poi_id to attach a verdict to; 'vacant'
            # or 'unknown' -> absence, which is never a closure (D79).
            if matched_poi_id and sf["status"] in EVIDENCE_STATUSES:
                pe.insert_evidence(con, pe.EvidenceRow(
                    poi_id=matched_poi_id,
                    verdict=sf["status"],
                    source=pe.SOURCE_WEB,
                    source_name=MAPS_SOURCE_NAME,
                    domain_class=MAPS_DOMAIN_CLASS,
                    url=obs.get("maps_url") or maps_url(anchor["anchor_lat"],
                                                        anchor["anchor_lon"]),
                    evidence_date=observed_at.date(),
                    dated_by=pe.DATED_RETRIEVAL,
                    retrieved_at=observed_at,
                    query=f"ground-truth {rec_id}",
                    raw=sf,
                    run_id=run_id))
                res.n_evidence += 1

        res.n_records += 1
        res.rec_ids.append(rec_id)
    return res


# ---------------------------------------------------------------- summary

def summary(con) -> dict:
    """Per-rec_id counts, plus every row of the miss view.

    The misses are the output. The counts are only there so a reader can see
    how many anchors have been checked at all before reading a miss rate off
    a denominator that is still three.
    """
    require_schema(con)
    by_rec = con.execute("""
        SELECT o.rec_id,
               any_value(o.category)                                  AS category,
               max(o.observed_at)                                     AS observed_at,
               any_value(o.gap_verdict)                               AS gap_verdict,
               count(*) FILTER (WHERE o.storefront_name IS NOT NULL)   AS n_storefronts,
               count(*) FILTER (WHERE o.status = 'open')               AS n_open,
               count(*) FILTER (WHERE o.status = 'closed')             AS n_closed,
               count(*) FILTER (WHERE o.storefront_name IS NULL)       AS n_vacant,
               count(*) FILTER (WHERE o.matched_poi_id IS NOT NULL)    AS n_matched,
               count(*) FILTER (WHERE o.category_guess = o.category
                                  AND o.status = 'open')              AS n_same_category_open,
               any_value(o.streetview_capture_date)                    AS imagery
        FROM analysis.address_observation o
        GROUP BY o.rec_id
        ORDER BY o.rec_id
    """).fetchdf().to_dict("records")
    misses = con.execute("""
        SELECT rec_id, category, storefront_name, category_guess, status,
               maps_status_label, anchor_address_id, observed_at
        FROM analysis.address_observation_miss
        ORDER BY rec_id, storefront_name
    """).fetchdf().to_dict("records")
    return {"by_rec": by_rec, "misses": misses}
