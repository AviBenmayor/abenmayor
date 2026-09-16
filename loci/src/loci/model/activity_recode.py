"""Undo DOF's 2024 LL157 `primary_business_activity` recode.

ONE PUBLIC FACT: `analysis.storefront.activity_canonical` is the column every
longitudinal question about storefront USE must read. `primary_business_activity`
stays, verbatim, because a corrected label is a derived opinion and the raw
value is the evidence -- but it is NOT comparable across 2024-06-03 and nothing
in the database says so.

WHY A CROSSWALK AND NOT A RE-INGEST
-----------------------------------
DOF did not republish the old filings. The 2019-2023 files still carry the old
vocabulary and the 2024/2025 files carry the new one; there is no vintage of
the data in which the series is consistent. The only repair is to map one
vocabulary onto the other, and the mapping is recoverable because the recode is
a PERMUTATION -- an off-by-one against a reordered code list -- rather than a
re-survey. See sql/012_activity_recode.yaml for the derivation and its caveats.

THE THREE THINGS THIS MODULE REFUSES TO DO SILENTLY
---------------------------------------------------
1. It re-derives the recode era from each filing's own marginals and RAISES if
   the derivation disagrees with the pinned `recoded_filings` list. A DOF
   filing that lands recoded and unlisted must break the build, not be mapped
   through the identity.
2. It asserts the crosswalk is a permutation (17 -> 17, domain == range) at
   load time. A hand-edit that collapses two codes onto one would otherwise
   manufacture false persistence -- the same class of bug as a dedup fusing
   two storefronts.
3. It never writes a NULL over a non-NULL raw value. A label outside the
   crosswalk's domain (a vocabulary DOF adds later) carries through
   case-normalised, and `recode_report` counts it.
"""
from __future__ import annotations

import datetime as dt
import functools
import pathlib

import yaml

#: Package data, beside the DDL it patches.
CROSSWALK_PATH = pathlib.Path(__file__).resolve().parents[1] / "sql" / "012_activity_recode.yaml"

TABLE = "analysis.storefront"
RAW_COLUMN = "primary_business_activity"
CANON_COLUMN = "activity_canonical"


class RecodeError(RuntimeError):
    """A recode the crosswalk cannot account for. Never a silent pass-through."""


@functools.lru_cache(maxsize=1)
def load(path: str | None = None) -> dict:
    """Read, validate and cache the crosswalk.

    Validation is the point of the function: an invalid crosswalk that loads
    is worse than no crosswalk, because every downstream persistence figure
    would then be a confident wrong answer.
    """
    p = pathlib.Path(path) if path else CROSSWALK_PATH
    doc = yaml.safe_load(p.read_text())

    rows = doc.get("crosswalk") or []
    canon = [str(r["canonical"]).upper().strip() for r in rows]
    coded = [str(r["recoded_as"]).upper().strip() for r in rows]

    if len(set(canon)) != len(canon):
        raise RecodeError(
            f"activity_recode: {p.name} repeats a canonical code "
            f"{sorted({c for c in canon if canon.count(c) > 1})}. The crosswalk "
            f"must be one-to-one; a many-to-one map would fuse two activity "
            f"classes and manufacture persistence that is not there.")
    if len(set(coded)) != len(coded):
        raise RecodeError(
            f"activity_recode: {p.name} maps two canonical codes onto the same "
            f"recoded code {sorted({c for c in coded if coded.count(c) > 1})}. "
            f"Not invertible -- refusing to load.")
    if set(canon) != set(coded):
        raise RecodeError(
            f"activity_recode: {p.name} is not a permutation. "
            f"canonical-only={sorted(set(canon) - set(coded))} "
            f"recoded-only={sorted(set(coded) - set(canon))}. The 2024 recode "
            f"was a relabelling of a fixed vocabulary; a crosswalk whose domain "
            f"and range differ is describing something else.")

    doc["_inverse"] = dict(zip(coded, canon))          # printed -> canonical
    doc["_forward"] = dict(zip(canon, coded))
    doc["_recoded_filings"] = {
        d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
        for d in (doc.get("recoded_filings") or [])
    }
    return doc


def inverse_map(path: str | None = None) -> dict[str, str]:
    """Printed-label -> canonical label, for filings inside the recode era."""
    return dict(load(path)["_inverse"])


def recoded_filings(path: str | None = None) -> set[dt.date]:
    return set(load(path)["_recoded_filings"])


# ----------------------------------------------------------------- detection

def detect_recoded_filings(con, path: str | None = None) -> dict[dt.date, str]:
    """Classify every filing in the warehouse from its OWN marginals.

    Returns {filing_due_date: 'recoded' | 'raw' | 'undecidable'}.

    The signature is the ratio of the two codes the permutation swaps hardest:
    in the pre vocabulary FOOD SERVICES is ~20% of a full filing and
    EDUCATIONAL SERVICES ~1.2%; inside the recode they are ~0.05% and ~33%.
    Three orders of magnitude apart, so the test is a comparison, not a
    threshold. A filing with too few labelled rows (the vacant-only files whose
    activity column is entirely NULL) is `undecidable` and is treated as raw --
    correct, because there is nothing to map.
    """
    doc = load(path)
    det = doc.get("detector") or {}
    pre_code = str(det.get("pre_dominant", "FOOD SERVICES")).upper()
    post_code = str(det.get("post_dominant", "EDUCATIONAL SERVICES")).upper()
    floor = int(det.get("min_labelled_rows", 200))

    rows = con.execute(f"""
        SELECT filing_due_date,
               count(*) FILTER (WHERE {RAW_COLUMN} IS NOT NULL)            AS labelled,
               count(*) FILTER (WHERE upper(trim({RAW_COLUMN})) = ?)       AS n_pre,
               count(*) FILTER (WHERE upper(trim({RAW_COLUMN})) = ?)       AS n_post
        FROM {TABLE}
        GROUP BY 1 ORDER BY 1
    """, [pre_code, post_code]).fetchall()

    out: dict[dt.date, str] = {}
    for filing, labelled, n_pre, n_post in rows:
        if labelled < floor:
            out[filing] = "undecidable"
        elif n_post > n_pre:
            out[filing] = "recoded"
        else:
            out[filing] = "raw"
    return out


def assert_era_pinned(con, path: str | None = None) -> dict[dt.date, str]:
    """Detection must agree with the pinned list. Raise, loudly, if not.

    This is the guard that makes the crosswalk safe to leave in place. The
    failure it exists for is a NEW DOF filing: if 2026-08-15 arrives recoded
    and is not in `recoded_filings`, the identity map would be applied to it
    and every comparison touching it would be wrong by the same factor of
    twelve this module was written to fix -- with no symptom.
    """
    pinned = recoded_filings(path)
    detected = detect_recoded_filings(con, path)
    det_set = {f for f, k in detected.items() if k == "recoded"}

    unlisted = sorted(det_set - pinned)
    listed_but_raw = sorted(f for f in pinned
                            if detected.get(f) == "raw")
    if unlisted or listed_but_raw:
        raise RecodeError(
            f"activity_recode: the recode era in {CROSSWALK_PATH.name} no longer "
            f"matches the data. Filings that LOOK recoded but are not listed: "
            f"{[str(f) for f in unlisted]}. Filings listed as recoded that look "
            f"raw: {[str(f) for f in listed_but_raw]}. Re-derive the crosswalk "
            f"against the new filing before ingesting -- do NOT widen the list "
            f"without re-running the premises crosstab.")
    return detected


# ------------------------------------------------------------------ SQL glue

def canonical_sql(raw_expr: str = RAW_COLUMN,
                  filing_expr: str = "filing_due_date",
                  path: str | None = None) -> str:
    """A SQL expression computing `activity_canonical`.

    Used both by the LL157 ingest (so a fresh `loci storefronts` run writes the
    column) and by the migration (so the warehouse standing today gets it
    without a re-ingest). One expression, two callers, no drift.

    Case normalisation is UPPER(TRIM(...)) and is applied to EVERY filing, in
    and out of the era -- it fixes `HEALTH CARE or` vs `HEALTH CARE OR`, which
    is a separate defect from the recode and predates it by four years.
    """
    doc = load(path)
    inv = doc["_inverse"]
    era = sorted(doc["_recoded_filings"])
    if not era:
        return f"NULLIF(upper(trim({raw_expr})), '')"

    dates = ", ".join(f"DATE '{d.isoformat()}'" for d in era)
    whens = "\n".join(
        f"                WHEN {_lit(k)} THEN {_lit(v)}"
        for k, v in sorted(inv.items()))
    return f"""CASE
            WHEN {filing_expr} IN ({dates}) THEN
              CASE NULLIF(upper(trim({raw_expr})), '')
{whens}
                ELSE NULLIF(upper(trim({raw_expr})), '')
              END
            ELSE NULLIF(upper(trim({raw_expr})), '')
          END"""


def _lit(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def backfill(con, path: str | None = None) -> int:
    """Populate `activity_canonical` on every existing row. Idempotent.

    Deliberately a full UPDATE rather than an UPDATE ... WHERE canonical IS
    NULL: a crosswalk revision must be able to correct rows it previously
    wrote, and the column is derived, so rewriting it loses nothing.
    """
    assert_era_pinned(con, path)
    expr = canonical_sql(path=path)
    con.execute(f"UPDATE {TABLE} SET {CANON_COLUMN} = {expr}")
    return con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE {CANON_COLUMN} IS NOT NULL"
    ).fetchone()[0]


# ------------------------------------------------------------------ reporting

def persistence(con, column: str = CANON_COLUMN,
                universe: str = "full") -> list[dict]:
    """Year-over-year same-activity persistence on single-storefront premises.

    THE ACCEPTANCE MEASURE. Restricted to premises reporting exactly one
    storefront in both filings of a pair, because `storefront_id` renumbers
    between filings (sql/012:72) and a premises with two storefronts offers no
    way to say which row is which. That restriction is why this is a
    PERSISTENCE DIAGNOSTIC and not a tenancy statistic.
    """
    rows = con.execute(f"""
        WITH one AS (
            SELECT premises_id, filing_due_date,
                   any_value(upper(trim({column}))) AS a
            FROM {TABLE}
            WHERE universe = ?
            GROUP BY 1, 2
            HAVING count(*) = 1
        ),
        filings AS (
            SELECT DISTINCT filing_due_date FROM one
        ),
        pairs AS (
            SELECT f.filing_due_date AS d0,
                   LEAD(f.filing_due_date) OVER (ORDER BY f.filing_due_date) AS d1
            FROM filings f
        )
        SELECT p.d0, p.d1, count(*) AS n,
               count(*) FILTER (WHERE a.a IS NOT DISTINCT FROM b.a) AS same
        FROM pairs p
        JOIN one a ON a.filing_due_date = p.d0
        JOIN one b ON b.filing_due_date = p.d1 AND b.premises_id = a.premises_id
        WHERE p.d1 IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1
    """, [universe]).fetchall()
    return [{"from": d0, "to": d1, "n": n, "same": same,
             "pct": (100.0 * same / n) if n else None}
            for d0, d1, n, same in rows]


def marginals(con, column: str = CANON_COLUMN,
              universe: str = "full") -> dict:
    """{filing_due_date: {activity: n}} -- the ±10% marginal check's input."""
    rows = con.execute(f"""
        SELECT filing_due_date, upper(trim({column})) AS a, count(*)
        FROM {TABLE} WHERE universe = ? AND {column} IS NOT NULL
        GROUP BY 1, 2
    """, [universe]).fetchall()
    out: dict = {}
    for filing, act, n in rows:
        out.setdefault(filing, {})[act] = n
    return out


def recode_report(con, path: str | None = None) -> dict:
    """Everything a reviewer needs to accept or reject the repair."""
    doc = load(path)
    unmapped = con.execute(f"""
        SELECT upper(trim({RAW_COLUMN})) AS a, count(*)
        FROM {TABLE}
        WHERE filing_due_date IN (SELECT UNNEST(?::DATE[]))
          AND {RAW_COLUMN} IS NOT NULL
          AND upper(trim({RAW_COLUMN})) NOT IN (SELECT UNNEST(?::VARCHAR[]))
        GROUP BY 1 ORDER BY 2 DESC
    """, [sorted(doc["_recoded_filings"]), sorted(doc["_inverse"])]).fetchall()
    return {
        "crosswalk_rows": len(doc["crosswalk"]),
        "recoded_filings": sorted(doc["_recoded_filings"]),
        "detected": detect_recoded_filings(con, path),
        "unmapped_labels_inside_era": [{"label": a, "n": n} for a, n in unmapped],
        "case_split_rows": con.execute(f"""
            SELECT count(*) FROM {TABLE}
            WHERE {RAW_COLUMN} <> upper(trim({RAW_COLUMN}))""").fetchone()[0],
        "persistence_raw": persistence(con, RAW_COLUMN),
        "persistence_canonical": persistence(con, CANON_COLUMN),
    }
