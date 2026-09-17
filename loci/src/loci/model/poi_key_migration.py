"""LOCATION-KEY MIGRATION -- carrying the first-seen ledger across a change to
the key's own recipe.

Read `sql/035_poi_key_map.sql` first: it carries the schema rationale, the four
`reason` values, the inventory of every table keyed on the ledger key, and the
five caveats the database cannot enforce.

THE PROBLEM IN ONE PARAGRAPH. `model/poi_presence.mint_key` hashes
`category | name-tokens | lon,lat @ 4dp` (plus the canonical `poi_id` when the
name normalises to nothing). CATEGORY IS IN THE PAYLOAD. So the owner's
category-precedence ruling "B" of 2026-09-14 -- a finer food category wins, so a
cluster carried by both a DOHMH `restaurant` record and an aggregator
`cafe_bakery` / `bar` record becomes `cafe_bakery` / `bar` -- re-mints the key
of every affected storefront. The business did not move, rename or open. Its
key changed. To `loci poi-snapshot` those are indistinguishable from new
storefronts, and `first_seen_month` is WRITE ONCE, NEVER UPDATED (sql/018):
the peer's dry run puts it at ~4,363 fake openings and ~15,700 fake
disappearances, written permanently, in the one table whose entire value is
being a continuous honest observation history.

THREE THINGS THIS MODULE DOES, and the order matters:

  `plan(con)`   reads the CURRENT dedup, mints what the key WOULD be for every
                cluster, and diffs that against the ledger. Writes rows to
                `analysis.poi_key_map` (`planned_at` stamped, `applied_at`
                NULL). Touches nothing else. `--dry-run` writes not even that.

  `apply(con)`  rewrites the key, in ONE transaction, in `analysis.poi_presence`
                and in every table keyed on it. Idempotent: a rewritten old key
                no longer exists to be matched, and an already-applied map row
                is skipped.

  `guard_snapshot(con)` REFUSES a snapshot whose dedup key set has drifted from
                the ledger's by more than GUARD_ABSENT_PCT, unless a map for
                that month exists and is fully applied. This is the part that
                does not rely on an operator remembering.

WHAT IS DELIBERATELY NOT DONE HERE
----------------------------------
* NOTHING IS EVER DELETED FOR BEING GONE. A ledger key absent from the new
  dedup with no content match is recorded 'unmapped' and LEFT ALONE, keeping
  its `last_seen_month` at the previous month, exactly as an ordinary
  disappearance does (sql/018 caveat 3: a disappearance is not a closure).
  The map row is the audit that we looked; it is not an instruction.

* NOTHING IS EVER MERGED INTO AN OCCUPIED KEY. A candidate whose target is
  already held by a surviving ledger row, or whose content matches more than
  one new cluster, is recorded 'collision' and refused. Fusing two histories
  onto one storefront is the failure sql/018's "WHY location_key IS NOT
  cluster_id" section exists to prevent, and a migration is a spectacularly
  easy place to commit it.

* THE MATCH IS NEVER LOOSER THAN THE KEY ITSELF. The only candidate map is an
  EXACT match on the hash payload MINUS the category -- same normalised name,
  same 4 dp coordinate, same canonical poi_id where the name is empty. No
  fuzzy name rule, no distance radius. Widening that would manufacture merges
  the dedup never asked for.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from dataclasses import dataclass, field

from loci.model.poi_presence import (
    KEY_PRECISION,
    current_locations_sql,
    mint_key,
    name_key_of,
)

SQL_035 = pathlib.Path(__file__).resolve().parents[1] / "sql" / "035_poi_key_map.sql"

#: Fraction of the CURRENT ledger (rows seen in the newest snapshot month) that
#: may vanish from the dedup's minted key set before `guard_snapshot` refuses.
#:
#: 0.5% of the 2026-09 ledger is ~1,138 locations. Ordinary month-to-month
#: churn sits far below that: a storefront that closes keeps its key (the key
#: is a hash of content, not a function of being observed), so the only things
#: that move a key are a rename past `norm_tokens`, a canonical-member change
#: that crosses a 4 dp boundary, or a change to the key recipe. The B-rule
#: event is ~8.8% -- more than an order of magnitude over.
GUARD_ABSENT_PCT = 0.005

#: AND an absolute floor, because a percentage over a small ledger is noise.
#: A test fixture that deliberately retires one of four POIs is 100% drift; a
#: fresh city's first ingest can be too. The failure this guard exists to catch
#: is a MASS re-mint -- 12,011 keys on the B rule -- so requiring BOTH the
#: fraction and the count keeps it silent on warehouses too small for the
#: arithmetic to mean anything without weakening the real case by a hair.
#:
#: Deliberately a floor on the ABSENT COUNT and not on the ledger size: Loci is
#: meant to be city-agnostic, and a smaller city's warehouse must still be
#: guarded. 25 absent keys out of a 200-location town trips it; four out of
#: four in a unit-test fixture does not.
GUARD_MIN_ABSENT = 25

#: Which `first_seen_kind` wins when two merged rows share the earliest
#: `first_seen_month`. A dated kind beats an observed one beats a censored one:
#: 'backfill_censored' means "existed before the ledger, date unknown and
#: unbounded below", so it is the WEAKEST claim, never the tiebreak winner.
_KIND_RANK = {"gov_filing": 0, "source_date": 1, "observed": 2,
              "backfill_censored": 3}

#: The ledger's full column list, in table order. Named explicitly for the same
#: reason `poi_presence._UPSERT_TEMPLATE` names its seventeen: a later ALTER
#: that silently changes the positional shape of an INSERT ... SELECT * is how
#: a migration writes `closed_src` into `ledger_started_month`.
LEDGER_COLUMNS = (
    "location_key", "category", "name_key", "display_name", "lon", "lat",
    "borough", "first_seen_month", "last_seen_month", "first_seen_kind",
    "first_seen_src_date", "first_seen_src_field", "n_months_seen",
    "cluster_id_latest", "poi_id_latest", "ledger_started_month",
    "last_snapshot_at", "closed_on", "closed_src",
)

#: Every table keyed on the LEDGER key, as (table, column). Inventoried against
#: `information_schema.columns WHERE column_name ILIKE '%location_key%'` on the
#: live warehouse, 2026-09-14, minus the two VIEWS (analysis.poi_first_seen,
#: analysis.recommendation_latest) which follow their base tables, and minus
#: `analysis.poi_supply_status.colocation_key`, which is a DIFFERENT key
#: (category + 5 dp coordinate, sql/029) and must not be touched.
#:
#: `analysis.poi_presence` is absent on purpose: it is rewritten by hand
#: because a merge has to fold whole rows together, not just relabel a column.
DEPENDENT_TABLES = (
    # chains.brand_location is handled separately: location_key is part of its
    # PRIMARY KEY, so a merge can collide there and needs de-duplication.
    ("analysis.recommendation_outcome", "matched_location_key"),
    ("staging.poi_closure", "location_key"),
    ("analysis.poi_closure_evidence", "location_key"),
)


# ---------------------------------------------------------------------------
# the content key -- the hash payload MINUS the category
# ---------------------------------------------------------------------------
def content_key(name_key: str, lon, lat, poi_id: str | None) -> str:
    """Everything `mint_key` hashes EXCEPT the category.

    This is the whole identity claim of the migration: two rows with the same
    content key differ only by category, so remapping one onto the other's key
    is a relabelling and not a re-identification. `tests/test_poi_key_migration`
    asserts `mint_key(cat, ...) == 'loc_' + blake2b(cat + '|' + content_key)`,
    so this function cannot drift away from the one it mirrors.

    NAMELESS ROWS FOLD IN THE CANONICAL poi_id, exactly as `mint_key` does --
    and that is also where this function's reach ends. `poi_snapshot` NULLs
    `poi_id_latest` on every ledger row whose `last_seen_month` is behind the
    newest, so a nameless row that already stopped appearing cannot be content
    matched at all. It falls to 'unmapped' and is left alone, which is the
    right outcome: sql/018 caveat 6 already says the nameless population has a
    weaker identity guarantee than the rest.
    """
    tail = (f"{name_key}|{round(float(lon), KEY_PRECISION):.{KEY_PRECISION}f}|"
            f"{round(float(lat), KEY_PRECISION):.{KEY_PRECISION}f}")
    if not name_key:
        tail += f"|{poi_id}"
    return tail


def ensure_schema(con) -> None:
    """Apply sql/035. Idempotent."""
    con.execute(SQL_035.read_text())


# ---------------------------------------------------------------------------
# reading both sides
# ---------------------------------------------------------------------------
def minted_from_dedup(con):
    """One row per CURRENT deduplicated location with the key it WOULD mint.

    Reuses `poi_presence.current_locations_sql` verbatim rather than writing a
    second query over `analysis.poi_dedup`: two definitions of "the locations
    the ledger is about" is how the migration ends up planning against a
    different universe than the snapshot writes."""
    cur = con.execute(current_locations_sql()).fetchdf()
    if cur.empty:
        raise RuntimeError(
            "analysis.poi_dedup is empty -- refusing to plan a key migration "
            "against nothing. Every ledger key would read as 'unmapped' and "
            "the guard would then wave through a snapshot that marks every "
            "storefront in the city as disappeared. Run `loci dedup` first.")
    cur["name_key"] = [name_key_of(s) for s in cur["name"]]
    cur["new_key"] = [
        mint_key(c, nk, lon, lat, pid) for c, nk, lon, lat, pid in
        zip(cur["category"], cur["name_key"], cur["lon"], cur["lat"],
            cur["poi_id"], strict=True)]
    cur["content"] = [
        content_key(nk, lon, lat, pid) for nk, lon, lat, pid in
        zip(cur["name_key"], cur["lon"], cur["lat"], cur["poi_id"], strict=True)]
    return cur


def ledger_frame(con, columns: str = "location_key, category, name_key, lon, lat, "
                                     "poi_id_latest, last_seen_month"):
    return con.execute(f"SELECT {columns} FROM analysis.poi_presence").fetchdf()


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------
@dataclass
class PlanResult:
    planned_at: dt.datetime
    n_dedup: int = 0             # current deduplicated locations (clusters)
    n_ledger: int = 0            # ledger rows, all months
    n_ledger_current: int = 0    # ledger rows seen in the newest month
    n_surviving: int = 0         # ledger keys the new dedup still mints
    n_absent: int = 0            # ledger keys the new dedup no longer mints
    relabel_poi: int = 0         # 1:1 via the canonical/member poi_id. STRONGEST.
    relabel_loc: int = 0         # 1:1 via name + 4 dp coordinate. WEAKER.
    merged_groups: int = 0       # new keys receiving 2+ contributing ledger rows
    merged_old_keys: int = 0     # absent old keys inside those groups
    merged_into_existing: int = 0  # groups whose target key a ledger row ALREADY holds
    unmapped: int = 0            # genuinely gone; never deleted
    collisions: int = 0          # refused: weak route into a contested key
    new_keys: int = 0            # minted keys with no old key behind them
    absent_pct: float = 0.0      # n_absent / n_ledger_current
    rows: object = None          # DataFrame written to analysis.poi_key_map
    written: int = 0
    dry_run: bool = False
    by_transition: dict = field(default_factory=dict)  # 'old -> new' -> count
    by_route: dict = field(default_factory=dict)       # route -> count

    @property
    def mapped(self) -> int:
        """1:1 relabels, both routes. Kept as a name because it is the number
        anyone asks for first."""
        return self.relabel_poi + self.relabel_loc


#: How an absent ledger row was matched to a new cluster, in DECREASING
#: strength. The route decides what the match is ALLOWED to do, which is the
#: whole point of naming them:
#:
#:   'poi_canonical'  the ledger row's `poi_id_latest` is the CANONICAL poi of a
#:                    new cluster. The dedup itself says this is that location.
#:   'poi_member'     `poi_id_latest` is a MEMBER of a new cluster whose
#:                    canonical pick is someone else -- i.e. this ledger row was
#:                    ABSORBED by a cross-category merge. Still the dedup's own
#:                    assertion, so it may merge.
#:   'content'        no live poi_id (the ledger NULLs `poi_id_latest` on rows
#:                    behind the newest month, and a dropped feed can retire a
#:                    poi entirely), but the hash payload minus the category --
#:                    same normalised name, same 4 dp cell -- matches exactly one
#:                    new cluster. Good enough to RELABEL, NEVER good enough to
#:                    MERGE: a name+cell match carries no evidence that two
#:                    storefronts are one business, and merging on it is the
#:                    fusing bug wearing a costume.
_POI_ROUTES = ("poi_canonical", "poi_member")


def plan(con, *, dry_run: bool = False, now: dt.datetime | None = None) -> PlanResult:
    """Diff the CURRENT dedup's minted keys against the ledger.

    Returns a PlanResult and (unless `dry_run`) writes the map to
    `analysis.poi_key_map`. Nothing else is touched, so this is safe to run at
    any time; on a warehouse whose dedup has not changed it reports zero
    candidates, and that no-op is itself the useful signal.

    THE SHAPE OF THE B-RULE EVENT it was written for (peer's dry run against
    dedup 13f0fec, 2026-09-14): 12,011 clusters gone, 3,596 minted, net -8,415
    (227,548 -> 219,133). Of the minted, 3,514 keep the same canonical member
    and only change category; 82 genuinely change canonical member, ~67 of
    which did not move. The 12,011 are mostly ABSORBED DUPLICATES of a
    cross-category merge -- and 8,415 of them are absorbed into a cluster whose
    key a ledger row ALREADY HOLDS. That last number is why merging into an
    occupied key must be ALLOWED on a poi route: refusing it (the obvious
    conservative choice) would strand 8,415 histories and report them as
    disappearances, which is the very damage this module exists to prevent.

    THE ROUTES ARE TRIED STRONGEST FIRST and the route constrains the verdict:

      poi_id route    `poi_id_latest` -> `analysis.poi_dedup.cluster_id` -> the
                      key that cluster mints. The dedup's own membership, so it
                      may RELABEL (sole claimant, free target) or MERGE.
      content route   name + 4 dp coordinate, exactly one new cluster. May
                      RELABEL ONLY. Contested or occupied -> 'collision'.
      neither         'unmapped'. Left completely alone.

    Leaving the residual canonical-member changes unmapped is not a loss: the
    snapshot's own pass B (name + `dedup.MATCH_METERS` = 40 m, against ledger
    rows pass A did not claim) links most of them back. This plan is the
    belt; that link is the braces."""
    import pandas as pd

    ensure_schema(con)
    now = now or dt.datetime.now()
    res = PlanResult(planned_at=now)

    cur = minted_from_dedup(con)
    led = ledger_frame(con)
    res.n_dedup = len(cur)
    res.n_ledger = len(led)

    if led.empty:
        # No ledger yet: every key is new and nothing can be migrated. Saying
        # so beats writing an empty table.
        res.new_keys = len(cur)
        res.rows = pd.DataFrame(columns=["old_key", "new_key", "reason",
                                         "old_category", "new_category", "poi_id"])
        res.dry_run = dry_run
        return res

    newest = led["last_seen_month"].max()
    res.n_ledger_current = int((led["last_seen_month"] == newest).sum())

    minted_keys = set(cur["new_key"])
    ledger_keys = set(led["location_key"])
    surviving = ledger_keys & minted_keys
    res.n_surviving = len(surviving)

    key_by_cluster = dict(zip(cur["cluster_id"], cur["new_key"], strict=True))
    cat_by_cluster = dict(zip(cur["cluster_id"], cur["category"], strict=True))
    canon_by_cluster = dict(zip(cur["cluster_id"], cur["poi_id"], strict=True))

    # EVERY member, not just the canonical one: the absorbed half of a
    # cross-category merge is by definition NOT the canonical pick of the
    # cluster that swallowed it, so a canonical-only lookup would find nothing
    # for the 12,011 rows that matter most.
    memb = con.execute("SELECT poi_id, cluster_id FROM analysis.poi_dedup").fetchdf()
    cluster_by_poi = dict(zip(memb["poi_id"], memb["cluster_id"], strict=True))

    # Content index over the NEW clusters. One content string can carry several
    # clusters (same name, same 4 dp cell, different categories) -- precisely
    # the ambiguity we refuse rather than guess at.
    by_content: dict[str, list[int]] = {}
    for i, c in enumerate(cur["content"]):
        by_content.setdefault(c, []).append(i)

    absent = led[~led["location_key"].isin(minted_keys)]
    res.n_absent = len(absent)
    res.absent_pct = (res.n_absent / res.n_ledger_current
                      if res.n_ledger_current else 0.0)

    # (old_key, new_key, route, old_category, new_category, poi_id)
    cand: list[tuple] = []
    refused: list[tuple] = []
    gone: list[tuple[str, str]] = []

    cols = ("location_key", "category", "name_key", "lon", "lat", "poi_id_latest")
    for k, cat, nk, lon, lat, pid in zip(*(absent[c].tolist() for c in cols),
                                         strict=True):
        pid = None if pid is None or pid != pid else str(pid)
        cl = cluster_by_poi.get(pid) if pid else None
        if cl is not None:
            route = "poi_canonical" if canon_by_cluster.get(cl) == pid else "poi_member"
            cand.append((k, str(key_by_cluster[cl]), route, cat,
                         str(cat_by_cluster[cl]), str(canon_by_cluster[cl])))
            continue
        if lon is None or lat is None or lon != lon or lat != lat:
            gone.append((k, cat))
            continue
        want = content_key("" if nk is None else nk, lon, lat, pid)
        hits = by_content.get(want, ())
        if not hits:
            gone.append((k, cat))
            continue
        if len(hits) > 1:
            # Same name, same cell, more than one new cluster. Picking one
            # would be a coin flip that permanently attaches this storefront's
            # history to a 50/50 guess.
            refused.append((k, None, cat, "ambiguous", None))
            continue
        j = hits[0]
        cand.append((k, str(cur["new_key"].iat[j]), "content", cat,
                     str(cur["category"].iat[j]), str(cur["poi_id"].iat[j])))

    # ---- decide relabel vs merge vs refusal, per TARGET key.
    per_new: dict[str, list[int]] = {}
    for idx, c in enumerate(cand):
        per_new.setdefault(c[1], []).append(idx)

    rows: list[tuple] = []
    for new_key, idxs in per_new.items():
        occupied = new_key in surviving
        contributors = len(idxs) + (1 if occupied else 0)
        poi_backed = [i for i in idxs if cand[i][2] in _POI_ROUTES]

        if contributors == 1:
            k, nkey, route, oc, nc, pid = cand[idxs[0]]
            reason = "relabel_poi" if route in _POI_ROUTES else "relabel_loc"
            rows.append((k, nkey, reason, oc, nc, pid))
            if reason == "relabel_poi":
                res.relabel_poi += 1
            else:
                res.relabel_loc += 1
            res.by_route[route] = res.by_route.get(route, 0) + 1
            res.by_transition[f"{oc} -> {nc}"] = res.by_transition.get(f"{oc} -> {nc}", 0) + 1
            continue

        # A MERGE. Only the dedup's own membership may authorise one; a
        # content match is refused here rather than allowed to fuse two
        # storefronts that merely share a name and a 4 dp cell.
        if not poi_backed:
            for i in idxs:
                k, nkey, route, oc, nc, pid = cand[i]
                refused.append((k, nkey, oc, nc, pid))
            continue
        res.merged_groups += 1
        if occupied:
            res.merged_into_existing += 1
        for i in idxs:
            k, nkey, route, oc, nc, pid = cand[i]
            if route in _POI_ROUTES:
                rows.append((k, nkey, "merged", oc, nc, pid))
                res.merged_old_keys += 1
                res.by_route[route] = res.by_route.get(route, 0) + 1
                res.by_transition[f"{oc} -> {nc}"] = (
                    res.by_transition.get(f"{oc} -> {nc}", 0) + 1)
            else:
                # A content-route candidate riding along on someone else's
                # merge. Refused: the merge's evidence is not its evidence.
                refused.append((k, nkey, oc, nc, pid))

    for k, nkey, oc, nc, pid in refused:
        rows.append((k, nkey, "collision", oc, nc, pid))
        res.collisions += 1
    for k, cat in gone:
        rows.append((k, None, "unmapped", cat, None, None))
    res.unmapped = len(gone)
    res.new_keys = len(minted_keys - surviving - set(per_new))

    frame = pd.DataFrame(rows, columns=["old_key", "new_key", "reason",
                                        "old_category", "new_category", "poi_id"])
    # INVARIANT: no new key may also be an old key, or apply would chain
    # A->B->C and the ORDER of the rewrites would decide the answer. (A merge
    # target that a SURVIVING ledger row holds is fine: it is not an old key,
    # because a surviving key is by definition one the dedup still mints.)
    chained = set(frame["new_key"].dropna()) & set(frame["old_key"])
    if chained:
        raise RuntimeError(
            f"{len(chained)} keys appear as BOTH an old and a new key "
            f"(e.g. {sorted(chained)[0]}) -- the map is not a function and "
            "applying it would depend on rewrite order. Refusing to write it.")
    # INVARIANT: identical content AND identical category is the SAME key, so
    # it would have survived. A 1:1 relabel whose category did not change means
    # content_key and mint_key have drifted apart.
    same = frame[frame["reason"].str.startswith("relabel")
                 & (frame["old_category"] == frame["new_category"])]
    if len(same):
        raise RuntimeError(
            f"{len(same)} map rows claim a category-only relabel but the "
            f"category is unchanged (e.g. {same['old_key'].iat[0]}) -- "
            "content_key and mint_key have drifted apart. Refusing to write.")

    frame["planned_at"] = now
    res.rows = frame
    res.dry_run = dry_run
    if dry_run or frame.empty:
        return res

    con.register("_key_map_in", frame)
    try:
        con.execute("""
            INSERT INTO analysis.poi_key_map
                (old_key, new_key, reason, old_category, new_category, poi_id,
                 planned_at, applied_at)
            SELECT old_key, new_key, reason, old_category, new_category, poi_id,
                   planned_at, NULL
            FROM _key_map_in
            ON CONFLICT (old_key, planned_at) DO NOTHING""")
    finally:
        con.unregister("_key_map_in")
    res.written = len(frame)
    return res

# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
#: The `reason` values `apply` acts on. 'unmapped' and 'collision' are
#: RECORDED ONLY -- they are the audit that we looked and chose to do nothing.
ACTIONABLE = ("relabel_poi", "relabel_loc", "merged")
_ACTIONABLE_SQL = ", ".join(f"'{r}'" for r in ACTIONABLE)


@dataclass
class ApplyResult:
    planned_at: object = None
    n_rows_migrated: int = 0     # ledger rows whose key was rewritten (1:1)
    n_relabel_poi: int = 0       # ... of those, found via the canonical poi_id
    n_relabel_loc: int = 0       # ... of those, found via name + 4 dp coordinate
    n_merged_into_existing: int = 0   # merge targets a ledger row already held
    n_merged_groups: int = 0
    n_merged_absorbed: int = 0   # ledger rows folded away by a merge
    n_unmapped: int = 0          # recorded, untouched
    n_collisions: int = 0        # recorded, refused
    dependents: dict = field(default_factory=dict)
    ledger_before: int = 0
    ledger_after: int = 0
    dry_run: bool = False
    noop: bool = False


def _pending(con):
    """The newest plan that still has unapplied mapped/merged rows."""
    row = con.execute(f"""
        SELECT max(planned_at) FROM analysis.poi_key_map
        WHERE applied_at IS NULL AND reason IN ({_ACTIONABLE_SQL})""").fetchone()
    return row[0] if row else None


def apply(con, *, dry_run: bool = False, now: dt.datetime | None = None) -> ApplyResult:
    """Rewrite the ledger key everywhere, in ONE transaction.

    Acts only on the NEWEST plan that still has unapplied 'mapped' / 'merged'
    rows. IDEMPOTENT three times over: the row is stamped `applied_at`, the
    rewritten old key no longer exists to be matched, and a second call finds
    no pending plan and returns `noop`."""
    import pandas as pd

    ensure_schema(con)
    now = now or dt.datetime.now()
    res = ApplyResult()
    planned_at = _pending(con)
    if planned_at is None:
        res.noop = True
        res.ledger_before = res.ledger_after = con.execute(
            "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
        return res
    res.planned_at = planned_at

    mp = con.execute(f"""
        SELECT old_key, new_key, reason, new_category FROM analysis.poi_key_map
        WHERE planned_at = ? AND applied_at IS NULL
          AND reason IN ({_ACTIONABLE_SQL})""", [planned_at]).fetchdf()
    res.n_unmapped = con.execute(
        "SELECT count(*) FROM analysis.poi_key_map WHERE planned_at = ? "
        "AND reason = 'unmapped'", [planned_at]).fetchone()[0]
    res.n_collisions = con.execute(
        "SELECT count(*) FROM analysis.poi_key_map WHERE planned_at = ? "
        "AND reason = 'collision'", [planned_at]).fetchone()[0]

    res.ledger_before = con.execute(
        "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]

    # Re-assert the two invariants at APPLY time, not just at plan time: the
    # dedup may have been rebuilt in between (caveat 1), and a stale map that
    # chains keys would silently depend on rewrite order.
    chained = set(mp["new_key"]) & set(mp["old_key"])
    if chained:
        raise RuntimeError(
            f"map {planned_at} chains {len(chained)} keys (both old and new) -- "
            "refusing to apply. Re-run `loci poi-keys plan`.")
    one_to_one = mp[mp["reason"].str.startswith("relabel")]
    merged = mp[mp["reason"] == "merged"]
    res.n_rows_migrated = int(len(one_to_one))
    res.n_relabel_poi = int((mp["reason"] == "relabel_poi").sum())
    res.n_relabel_loc = int((mp["reason"] == "relabel_loc").sum())
    res.n_merged_groups = int(merged["new_key"].nunique()) if len(merged) else 0
    # A merge whose TARGET KEY a surviving ledger row already holds folds that
    # row in too, so it costs one row fewer than a merge into a free key. This
    # is the dominant shape of the B-rule event (8,415 of 12,011) and getting
    # the arithmetic wrong here is how `ledger_after` stops being checkable.
    if len(merged):
        con.register("_mp", merged[["new_key"]].drop_duplicates())
        try:
            res.n_merged_into_existing = int(con.execute(
                "SELECT count(*) FROM _mp m JOIN analysis.poi_presence pp "
                "ON pp.location_key = m.new_key").fetchone()[0])
        finally:
            con.unregister("_mp")
    res.n_merged_absorbed = int(len(merged)) - (
        res.n_merged_groups - res.n_merged_into_existing)

    if dry_run:
        res.dry_run = True
        res.ledger_after = res.ledger_before - res.n_merged_absorbed
        return res

    # ---- build the merged ledger rows BEFORE the transaction (pandas work,
    #      no locks held while we do it).
    merged_rows = _build_merged_rows(con, merged) if len(merged) else None

    cols = ", ".join(LEDGER_COLUMNS)
    con.execute("BEGIN")
    try:
        con.register("_map", mp[["old_key", "new_key", "reason", "new_category"]])

        # A RELABEL target must not already exist in the ledger -- a relabel
        # carries no evidence that two storefronts are one, so landing on an
        # occupied key would fuse two histories. plan() refuses those; this
        # catches a map applied against a ledger that moved on since. A MERGE
        # target is a different matter and is ALLOWED to be occupied: the dedup
        # itself put those POIs in one cluster, and `_build_merged_rows` folds
        # the sitting row in rather than overwriting it.
        n_occupied = con.execute("""
            SELECT count(*) FROM analysis.poi_presence pp
            JOIN _map m ON pp.location_key = m.new_key
            WHERE m.reason LIKE 'relabel%'""").fetchone()[0]
        if n_occupied:
            raise RuntimeError(
                f"{n_occupied} relabel target keys already exist in the ledger "
                "-- applying would fuse two storefront histories onto one key. "
                "Re-run `loci poi-keys plan` against the current dedup.")

        # ---- 1:1. The CATEGORY MOVES WITH THE KEY, and that is load-bearing,
        # not cosmetic: poi_presence.link_to_ledger's pass A matches on the key
        # AND `by_key[k] == cur.category`, so a row whose key was rewritten but
        # whose category was not would fail pass A and mint a fresh key anyway
        # -- the exact fake opening this whole module exists to prevent.
        con.execute("""
            UPDATE analysis.poi_presence AS pp
            SET location_key = m.new_key, category = m.new_category
            FROM _map m
            WHERE pp.location_key = m.old_key AND m.reason LIKE 'relabel%'""")

        # ---- merges: fold the group into one row, then delete the originals.
        if merged_rows is not None and len(merged_rows):
            con.register("_merged_in", merged_rows)
            # The TARGET key is deleted too when a ledger row already held
            # it: `_build_merged_rows` folded that row into the survivor, so
            # leaving it would duplicate the primary key.
            con.execute(
                "DELETE FROM analysis.poi_presence WHERE location_key IN "
                "(SELECT old_key FROM _map WHERE reason = 'merged') "
                "OR location_key IN (SELECT new_key FROM _map "
                "                    WHERE reason = 'merged')")
            con.execute(f"INSERT INTO analysis.poi_presence ({cols}) "
                        f"SELECT {cols} FROM _merged_in")

        # ---- chains.brand_location: location_key is part of the PRIMARY KEY,
        # so a merge can collide there. Move the affected rows out, rewrite,
        # keep ONE row per (month, brand, key) -- earliest first_seen_on wins,
        # poi_id breaking the tie so the choice is reproducible -- and let an
        # already-present target row win over an incoming one.
        bl = _rewrite_brand_location(con)
        res.dependents["chains.brand_location"] = bl

        # ---- the rest: location_key is not part of any key, so a plain
        # UPDATE ... FROM cannot collide.
        for table, column in DEPENDENT_TABLES:
            if not _table_exists(con, table):
                res.dependents[table] = {"skipped": "table does not exist"}
                continue
            n = con.execute(
                f"SELECT count(*) FROM {table} t JOIN _map m "
                f"ON t.{column} = m.old_key").fetchone()[0]
            if n:
                con.execute(
                    f"UPDATE {table} AS t SET {column} = m.new_key "
                    f"FROM _map m WHERE t.{column} = m.old_key")
            res.dependents[table] = {"rewritten": int(n)}

        con.execute(
            "UPDATE analysis.poi_key_map SET applied_at = ? "
            "WHERE planned_at = ? AND applied_at IS NULL", [now, planned_at])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        for name in ("_map", "_merged_in"):
            try:
                con.unregister(name)
            except Exception:          # noqa: BLE001 -- never registered
                pass

    res.ledger_after = con.execute(
        "SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
    return res


def _table_exists(con, qualified: str) -> bool:
    schema, name = qualified.split(".", 1)
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, name]).fetchone()[0])


def _build_merged_rows(con, merged):
    """Fold each merge group into ONE ledger row.

    THE RULES, and why each one:
      first_seen_month/kind/src_date/src_field  from the row with the EARLIEST
          first_seen_month, ties broken by _KIND_RANK. Earliest is right
          because a merge asserts these rows were always one business, so the
          earliest evidence about it is evidence about it. A censored row
          carries the ledger's start month as a placeholder, which is already
          the earliest possible value and stays flagged as censored -- it never
          silently becomes a real opening date.
      last_seen_month   MAX. The business was seen as recently as either row
          saw it.
      n_months_seen     MAX, NEVER THE SUM. Two rows seen in the same months
          would double-count; the max is the tightest honest lower bound
          (sql/035 caveat 4).
      ledger_started_month  MIN -- when we FIRST HELD any of these rows.
      closed_on/closed_src  the LATEST published closure among the group, or
          NULL if none published one (sql/035 caveat 3). NULL means "no closure
          observed", never "still open" (sql/027 caveat 2).
      category and the display fields  from the NEW cluster: `category` MUST be
          the new one or link_to_ledger's pass A rejects the row next snapshot.
    """
    import pandas as pd

    target = dict(zip(merged["old_key"], merged["new_key"], strict=True))
    newcat = dict(zip(merged["new_key"], merged["new_category"], strict=True))
    # THE SITTING ROW IS A CONTRIBUTOR, NOT A BYSTANDER. 8,415 of the B rule's
    # 12,011 absorbed clusters merge into a key a ledger row ALREADY HOLDS
    # (peer's dry run). Folding only the absent keys and leaving that row alone
    # would throw away the surviving storefront's first_seen -- usually the
    # OLDEST of the group, because it is the row that never moved.
    contributors = pd.DataFrame({"k": list(dict.fromkeys(
        merged["old_key"].tolist() + merged["new_key"].tolist()))})
    con.register("_merge_keys", contributors)
    try:
        cols = ", ".join(f"pp.{c}" for c in LEDGER_COLUMNS)
        rows = con.execute(
            f"SELECT {cols} FROM analysis.poi_presence pp "
            "JOIN _merge_keys k ON pp.location_key = k.k").fetchdf()
    finally:
        con.unregister("_merge_keys")

    rows["_new_key"] = [target.get(k, k) for k in rows["location_key"]]
    rows["_rank"] = [_KIND_RANK.get(k, 9) for k in rows["first_seen_kind"]]

    out = []
    for new_key, grp in rows.groupby("_new_key", sort=True):
        win = grp.sort_values(["first_seen_month", "_rank"]).iloc[0]
        clo = grp[grp["closed_on"].notna()].sort_values("closed_on")
        rec = {c: win[c] for c in LEDGER_COLUMNS}
        rec["location_key"] = new_key
        rec["category"] = newcat[new_key]
        rec["last_seen_month"] = grp["last_seen_month"].max()
        rec["n_months_seen"] = int(grp["n_months_seen"].max())
        rec["ledger_started_month"] = grp["ledger_started_month"].min()
        rec["last_snapshot_at"] = grp["last_snapshot_at"].max()
        rec["closed_on"] = clo["closed_on"].iloc[-1] if len(clo) else None
        rec["closed_src"] = clo["closed_src"].iloc[-1] if len(clo) else None
        # cluster_id_latest / poi_id_latest are re-derived by the next
        # snapshot; carrying the winner's is harmless and keeps the row valid
        # in between. They are NOT identity (sql/018).
        out.append(rec)
    return pd.DataFrame(out, columns=list(LEDGER_COLUMNS))


def _rewrite_brand_location(con) -> dict:
    """Rewrite chains.brand_location, de-duplicating the PK a merge can break."""
    if not _table_exists(con, "chains.brand_location"):
        return {"skipped": "table does not exist"}
    moved = con.execute(
        "SELECT count(*) FROM chains.brand_location bl JOIN _map m "
        "ON bl.location_key = m.old_key").fetchone()[0]
    if not moved:
        return {"rewritten": 0, "collapsed": 0}
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _bl_moved AS
        SELECT bl.snapshot_month, bl.brand_key, m.new_key AS location_key,
               bl.poi_id, bl.category, bl.borough, bl.lon, bl.lat,
               bl.first_seen_on, bl.first_seen_src
        FROM chains.brand_location bl
        JOIN _map m ON bl.location_key = m.old_key""")
    con.execute("DELETE FROM chains.brand_location WHERE location_key IN "
                "(SELECT old_key FROM _map)")
    # Named on BOTH sides (`chains.detect.LOCATION_COLUMNS` is the same list).
    # The SELECT list was already explicit, but DuckDB binds INSERT ... SELECT
    # by POSITION, so without the target list a future ALTER on
    # chains.brand_location would shift the ordinals under it.
    kept = con.execute("""
        INSERT INTO chains.brand_location
               (snapshot_month, brand_key, location_key, poi_id, category,
                borough, lon, lat, first_seen_on, first_seen_src)
        SELECT snapshot_month, brand_key, location_key, poi_id, category,
               borough, lon, lat, first_seen_on, first_seen_src
        FROM (SELECT *, row_number() OVER (
                  PARTITION BY snapshot_month, brand_key, location_key
                  ORDER BY first_seen_on NULLS LAST, poi_id) AS rn
              FROM _bl_moved)
        WHERE rn = 1
        ON CONFLICT DO NOTHING
        RETURNING 1""").fetchall()
    con.execute("DROP TABLE IF EXISTS _bl_moved")
    return {"rewritten": int(moved), "collapsed": int(moved) - len(kept)}


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------
class KeyDriftError(RuntimeError):
    """The dedup's key set has moved away from the ledger's without a map."""


def guard_snapshot(con, *, month: str | None = None, force: bool = False,
                   threshold: float = GUARD_ABSENT_PCT) -> dict:
    """REFUSE a snapshot whose key set has drifted, unless a map explains it.

    Called from `poi_presence.snapshot` before anything is written. Raises
    `KeyDriftError` when more than `threshold` of the CURRENT ledger (rows seen
    in the newest snapshot month -- not the whole ledger, which accumulates
    genuinely-departed rows forever and would trip this permanently) has a key
    the current dedup no longer mints.

    ALLOWED WITHOUT A MAP when:
      * the ledger is empty or has no snapshot yet -- nothing to corrupt;
      * drift is at or below the threshold -- ordinary churn;
      * `force=True` -- the operator said so, and `--force` already means
        "I have read sql/018 caveat 2".

    ALLOWED WITH A MAP when every 'mapped' / 'merged' row planned in `month`
    has an `applied_at`. A PLANNED-BUT-UNAPPLIED map is NOT a pass: that is
    precisely the state in which the snapshot would write the fake openings.

    WHAT THIS MEASURES, stated honestly: PASS-A (exact hash) misses only. The
    snapshot's pass B rescues a location whose coordinate drifted across a 4 dp
    boundary by a name+40 m link, so a guard trip OVERSTATES the damage -- it
    is a demand that a human look at the plan, not a proof of corruption. It
    will not fire on the reverse mistake (a key that stayed but whose meaning
    changed), which no diff of key sets can see.
    """
    stats: dict = {"threshold": threshold, "bypass": None}
    if not _table_exists(con, "analysis.poi_presence"):
        stats["bypass"] = "no ledger"
        return stats
    n_ledger = con.execute("SELECT count(*) FROM analysis.poi_presence").fetchone()[0]
    if not n_ledger:
        stats["bypass"] = "empty ledger"
        return stats
    if force:
        stats["bypass"] = "force"
        return stats
    if not _table_exists(con, "analysis.poi_dedup"):
        # Nothing to diff against. The snapshot refuses on an empty dedup two
        # lines later with a better message than this one could give.
        stats["bypass"] = "no dedup table"
        return stats

    newest = con.execute(
        "SELECT max(last_seen_month) FROM analysis.poi_presence").fetchone()[0]
    cur = minted_from_dedup(con)
    minted = set(cur["new_key"])
    led = con.execute(
        "SELECT location_key FROM analysis.poi_presence WHERE last_seen_month = ?",
        [newest]).fetchdf()
    current_keys = set(led["location_key"])
    absent = current_keys - minted
    stats.update({
        "newest_month": newest,
        "n_dedup": len(cur),
        "n_ledger_current": len(current_keys),
        "n_absent": len(absent),
        "absent_pct": (len(absent) / len(current_keys)) if current_keys else 0.0,
        "n_new": len(minted - current_keys),
    })
    stats["min_absent"] = GUARD_MIN_ABSENT
    if stats["absent_pct"] <= threshold or stats["n_absent"] < GUARD_MIN_ABSENT:
        stats["ok"] = True
        return stats

    month = month or dt.date.today().strftime("%Y-%m")
    stats["month"] = month
    if _table_exists(con, "analysis.poi_key_map"):
        row = con.execute("""
            SELECT count(*), count(*) FILTER (WHERE applied_at IS NULL
                                                AND reason IN ('relabel_poi',
                                                               'relabel_loc',
                                                               'merged'))
            FROM analysis.poi_key_map
            WHERE strftime(planned_at, '%Y-%m') = ?""", [month]).fetchone()
        stats["map_rows"], stats["map_unapplied"] = int(row[0]), int(row[1])
        if row[0] and not row[1]:
            stats["bypass"] = "poi_key_map"
            stats["ok"] = True
            return stats
        if row[0] and row[1]:
            raise KeyDriftError(
                f"{stats['n_absent']:,} of {stats['n_ledger_current']:,} current "
                f"ledger keys ({100 * stats['absent_pct']:.2f}%) are absent from the "
                f"dedup, and the {month} key map has {row[1]:,} rows PLANNED BUT NOT "
                "APPLIED. Run `loci poi-keys apply` before `loci poi-snapshot`, or "
                "the snapshot will record those as new openings.")
    else:
        stats["map_rows"] = stats["map_unapplied"] = 0

    raise KeyDriftError(
        f"refusing to snapshot: {stats['n_absent']:,} of "
        f"{stats['n_ledger_current']:,} ledger keys seen in {newest} "
        f"({100 * stats['absent_pct']:.2f}%, threshold "
        f"{100 * threshold:.2f}% and {GUARD_MIN_ABSENT} keys) are absent from "
        f"the current dedup, and no "
        f"applied analysis.poi_key_map exists for {month}. A key that re-mints "
        "looks EXACTLY like a new storefront to this ledger, and "
        "first_seen_month is write-once -- the damage is permanent. Run "
        "`loci poi-keys plan` to see what moved, `loci poi-keys apply` to carry "
        "the histories across, then snapshot. Pass --force only if you have "
        "read sql/035 and know these are real disappearances.")


# ---------------------------------------------------------------------------
# what `loci check-presence` reports
# ---------------------------------------------------------------------------
def migration_report(con) -> dict:
    """Read-only summary of every key migration this warehouse has seen.

    Includes ONE INTEGRITY CHECK the coverage assertions cannot make: no ledger
    row may still carry a key that an APPLIED map moved away from. A row like
    that means the apply half-landed, and the next snapshot would mint the new
    key beside the stale old one -- one storefront, two histories, both wrong.
    """
    if not _table_exists(con, "analysis.poi_key_map"):
        return {}
    row = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE reason LIKE 'relabel%'
                                  AND applied_at IS NOT NULL),
               count(*) FILTER (WHERE reason = 'merged'   AND applied_at IS NOT NULL),
               count(DISTINCT new_key) FILTER (WHERE reason = 'merged'
                                                 AND applied_at IS NOT NULL),
               count(*) FILTER (WHERE reason = 'unmapped'),
               count(*) FILTER (WHERE reason = 'collision'),
               count(*) FILTER (WHERE applied_at IS NULL
                                  AND reason IN ('relabel_poi', 'relabel_loc',
                                                 'merged')),
               max(planned_at), max(applied_at)
        FROM analysis.poi_key_map""").fetchone()
    out = {
        "map_rows": int(row[0]), "migrated": int(row[1]), "merged_rows": int(row[2]),
        "merged_groups": int(row[3]), "unmapped": int(row[4]),
        "collisions": int(row[5]), "pending": int(row[6]),
        "last_planned": row[7], "last_applied": row[8], "errors": [],
    }
    stale = con.execute("""
        SELECT count(*) FROM analysis.poi_presence pp
        JOIN analysis.poi_key_map m ON pp.location_key = m.old_key
        WHERE m.applied_at IS NOT NULL
          AND m.reason IN ('relabel_poi', 'relabel_loc', 'merged')
    """).fetchone()[0]
    out["stale_old_keys"] = int(stale)
    if stale:
        out["errors"].append(
            f"{stale} ledger rows still carry a location_key that an APPLIED "
            "poi_key_map moved away from -- the migration half-landed. Re-run "
            "`loci poi-keys apply`; do NOT snapshot first.")
    if out["pending"]:
        out["errors"].append(
            f"{out['pending']} poi_key_map rows are PLANNED BUT NOT APPLIED. "
            "`loci poi-snapshot` will refuse until `loci poi-keys apply` runs "
            "(or will write fake openings if forced past the guard).")
    return out


def format_migration(con) -> tuple[str | None, list[str]]:
    """(one printable line, errors) for `loci check-presence`."""
    r = migration_report(con)
    if not r or not r.get("map_rows"):
        return None, []
    return (f"key migrations: {r['migrated']:,} rows re-keyed 1:1, "
            f"{r['merged_rows']:,} rows merged into {r['merged_groups']:,} keys, "
            f"{r['unmapped']:,} unmapped (left alone), "
            f"{r['collisions']:,} collisions refused, {r['pending']:,} pending; "
            f"last applied {r['last_applied']}"), r["errors"]
