"""The guarded warehouse rebuilds: idempotent, and they refuse to lose rows.

Every step in loci/migrate.py rewrites a table by CREATE-INSERT-DROP-RENAME,
because DuckDB has no `ALTER TABLE ADD CONSTRAINT` (verified 1.5.5). That shape
has one catastrophic failure mode -- a rebuild that silently drops rows -- and
`_swap`'s count assertion is the only thing standing in front of it. These
tests exist to prove that assertion actually fires, because an untested safety
check is decoration.
"""
from __future__ import annotations

import duckdb
import pytest

from loci import migrate


def _forecast_fixture(tmp_path, rows=6):
    con = duckdb.connect(str(tmp_path / "f.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE analysis.forecast (
            forecast_id VARCHAR PRIMARY KEY, issued_month VARCHAR,
            horizon_months INTEGER, model_version VARCHAR, address_id VARCHAR,
            category VARCHAR, frame VARCHAR, borough VARCHAR, nta_code VARCHAR,
            surprise_cell VARCHAR, p_opening DOUBLE, expected_openings DOUBLE,
            support VARCHAR, features_json VARCHAR, frozen_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE analysis.forecast_outcome (
            forecast_id VARCHAR, scored_month VARCHAR, horizon_elapsed INTEGER,
            realized_openings INTEGER, realized_flag BOOLEAN,
            scored_at TIMESTAMP, PRIMARY KEY (forecast_id, scored_month))""")
    for i in range(rows):
        fid = f"f-202609-abc-{i}-bar"
        con.execute(
            "INSERT INTO analysis.forecast VALUES "
            "(?, '2026-09', 12, '0.1.1+abc', ?, 'bar', 'lot', ?, 'BK01', "
            "'738:5627', 0.1, 0.2, 'fitted', ?, TIMESTAMP '2026-09-15 17:53:22')",
            [fid, f"a{i}", "MN" if i % 2 else "BK", '{"homes_400m": %d}' % i])
        con.execute(
            "INSERT INTO analysis.forecast_outcome VALUES "
            "(?, '2026-10', 1, 0, FALSE, TIMESTAMP '2026-10-01 00:00:00')",
            [fid])
    return con


def test_rekey_then_slim_preserves_every_row(tmp_path):
    con = _forecast_fixture(tmp_path)
    before_f = con.execute("SELECT count(*) FROM analysis.forecast").fetchone()[0]
    before_o = con.execute(
        "SELECT count(*) FROM analysis.forecast_outcome").fetchone()[0]

    migrate.step_forecast_outcome_rekey(con, apply=True)
    migrate.step_forecast_slim(con, apply=True)

    assert con.execute("SELECT count(*) FROM analysis.forecast").fetchone()[0] == before_f
    assert con.execute(
        "SELECT count(*) FROM analysis.forecast_outcome").fetchone()[0] == before_o
    cols_f = {c[0] for c in con.execute(
        "SELECT column_name FROM duckdb_columns() "
        "WHERE table_name = 'forecast'").fetchall()}
    assert "features_json" not in cols_f and "forecast_id" not in cols_f
    assert "features_hash" in cols_f
    cols_o = {c[0] for c in con.execute(
        "SELECT column_name FROM duckdb_columns() "
        "WHERE table_name = 'forecast_outcome'").fetchall()}
    assert "forecast_id" not in cols_o
    assert {"issued_month", "model_version", "address_id", "category"} <= cols_o


def test_every_vintage_is_kept(tmp_path):
    """Owner ruling (1), 2026-09-16: keep EVERY vintage.

    The audit proposed keeping one shipped vintage per issued_month and was
    overruled. A step that quietly pruned a superseded rerun would be doing the
    thing the owner said not to do, so it is pinned.
    """
    con = _forecast_fixture(tmp_path, rows=2)
    con.execute("""
        INSERT INTO analysis.forecast SELECT
            replace(forecast_id, 'abc', 'def'), issued_month, horizon_months,
            '0.1.1+def', address_id, category, frame, borough, nta_code,
            surprise_cell, p_opening, expected_openings, support, features_json,
            TIMESTAMP '2026-09-14 22:51:39'
        FROM analysis.forecast""")
    before = con.execute("SELECT count(DISTINCT (issued_month, model_version)) "
                         "FROM analysis.forecast").fetchone()[0]
    assert before == 2
    migrate.step_forecast_outcome_rekey(con, apply=True)
    migrate.step_forecast_slim(con, apply=True)
    after = con.execute("SELECT count(DISTINCT (issued_month, model_version)) "
                        "FROM analysis.forecast").fetchone()[0]
    assert after == before, "a vintage was dropped; owner ruling (1) says keep every one"


def test_features_hash_is_stable_and_distinguishes_feature_sets(tmp_path):
    con = _forecast_fixture(tmp_path, rows=3)
    migrate.step_forecast_outcome_rekey(con, apply=True)
    migrate.step_forecast_slim(con, apply=True)
    hashes = [r[0] for r in con.execute(
        "SELECT features_hash FROM analysis.forecast ORDER BY address_id").fetchall()]
    assert all(len(h) == 16 for h in hashes)
    # three different features_json values -> three different hashes
    assert len(set(hashes)) == 3


def test_steps_are_idempotent(tmp_path):
    con = _forecast_fixture(tmp_path)
    migrate.step_forecast_outcome_rekey(con, apply=True)
    migrate.step_forecast_slim(con, apply=True)
    assert migrate.probe_forecast_slim(con)
    assert migrate.probe_forecast_outcome_rekey(con)
    # second run is a no-op, not an error
    r1 = migrate.step_forecast_slim(con, apply=True)
    r2 = migrate.step_forecast_outcome_rekey(con, apply=True)
    assert not r1.applied and not r2.applied
    assert any("no-op" in n for n in r1.notes)


def test_dry_run_writes_nothing(tmp_path):
    con = _forecast_fixture(tmp_path)
    migrate.step_forecast_slim(con, apply=False)
    cols = {c[0] for c in con.execute(
        "SELECT column_name FROM duckdb_columns() "
        "WHERE table_name = 'forecast'").fetchall()}
    assert "features_json" in cols, "dry run modified the schema"


def test_rekey_refuses_to_drop_orphaned_outcomes(tmp_path):
    """An outcome with no forecast row cannot be re-keyed.

    The join that recovers the natural key would silently discard it, and
    forecast_outcome is a FROZEN LEDGER -- a dropped row cannot be re-scored.
    The step must refuse rather than lose it.
    """
    con = _forecast_fixture(tmp_path, rows=2)
    con.execute("INSERT INTO analysis.forecast_outcome VALUES "
                "('f-orphan', '2026-10', 1, 0, FALSE, NULL)")
    with pytest.raises(RuntimeError, match="orphaned"):
        migrate.step_forecast_outcome_rekey(con, apply=True)
    assert con.execute(
        "SELECT count(*) FROM analysis.forecast_outcome").fetchone()[0] == 3


def test_swap_refuses_when_the_rebuild_loses_rows(tmp_path):
    """The count assertion must actually fire."""
    con = duckdb.connect(str(tmp_path / "s.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.t (x INTEGER, borough VARCHAR)")
    con.execute("INSERT INTO analysis.t VALUES (1,'MN'),(2,'BK'),(3,'QN')")
    notes = []
    with pytest.raises(RuntimeError, match="Refusing to swap"):
        migrate._swap(
            con, "analysis.t",
            "CREATE TABLE __TARGET__ (x INTEGER, borough VARCHAR)",
            "(x, borough) SELECT x, borough FROM analysis.t WHERE borough <> 'QN'",
            notes)
    # the original survives untouched and the temp is cleaned up
    assert con.execute("SELECT count(*) FROM analysis.t").fetchone()[0] == 3
    assert not con.execute(
        "SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name = 't__rebuild'").fetchone()[0]


def test_scope_checks_refuses_rather_than_deleting_out_of_scope_rows(tmp_path):
    """If a screen table somehow holds a QN row, the fix is not to delete it."""
    con = duckdb.connect(str(tmp_path / "c.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.dev_pipeline "
                "(job_number VARCHAR, borough VARCHAR)")
    con.execute("INSERT INTO analysis.dev_pipeline VALUES ('j1','MN'),('j2','QN')")
    original = dict(migrate.SCREEN_TABLES)
    migrate.SCREEN_TABLES.clear()
    migrate.SCREEN_TABLES["analysis.dev_pipeline"] = "job_number"
    try:
        with pytest.raises(RuntimeError, match="out-of-scope"):
            migrate.step_scope_checks(con, apply=True)
        assert con.execute(
            "SELECT count(*) FROM analysis.dev_pipeline").fetchone()[0] == 2
    finally:
        migrate.SCREEN_TABLES.clear()
        migrate.SCREEN_TABLES.update(original)


def test_demographics_clip_removes_only_orphans(tmp_path):
    con = duckdb.connect(str(tmp_path / "d.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("CREATE TABLE analysis.address (address_id VARCHAR, frame VARCHAR)")
    con.execute("INSERT INTO analysis.address VALUES ('a1','lot'),('a2','street')")
    con.execute("CREATE TABLE analysis.address_demographics "
                "(address_id VARCHAR, acs_year SMALLINT, population FLOAT)")
    con.execute("INSERT INTO analysis.address_demographics VALUES "
                "('a1',2023,100.0),('a2',2023,200.0),('zz',2023,300.0)")

    assert not migrate.probe_demographics_clip(con)
    migrate.step_demographics_clip(con, apply=True)
    assert migrate.probe_demographics_clip(con)

    kept = {r[0] for r in con.execute(
        "SELECT address_id FROM analysis.address_demographics").fetchall()}
    assert kept == {"a1", "a2"}, "clip removed an in-universe address"
    # frame='street' rows must survive the clip -- owner ruling (4)
    assert "a2" in kept


def test_rebuild_preserves_not_null_and_defaults(tmp_path):
    """A CTAS carries columns and rows and nothing else.

    analysis.address declares 11 NOT NULL columns -- including `lon`, `lat` and
    `borough` -- plus `frame DEFAULT 'lot'`. A rebuild that reconstructed the
    DDL from name+type alone would silently drop all of them, and the table
    would look identical until something wrote a NULL coordinate a month later.
    """
    con = duckdb.connect(str(tmp_path / "n.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE analysis.dev_pipeline (
            job_number VARCHAR NOT NULL,
            borough    VARCHAR NOT NULL,
            lon        DOUBLE  NOT NULL,
            frame      VARCHAR DEFAULT 'lot',
            note       VARCHAR)""")
    con.execute("INSERT INTO analysis.dev_pipeline (job_number, borough, lon) "
                "VALUES ('j1','MN',-73.9), ('j2','BK',-73.95)")

    original = dict(migrate.SCREEN_TABLES)
    migrate.SCREEN_TABLES.clear()
    migrate.SCREEN_TABLES["analysis.dev_pipeline"] = "job_number"
    try:
        migrate.step_scope_checks(con, apply=True)
    finally:
        migrate.SCREEN_TABLES.clear()
        migrate.SCREEN_TABLES.update(original)

    cols = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT column_name, is_nullable, column_default FROM duckdb_columns() "
        "WHERE table_name = 'dev_pipeline'").fetchall()}
    assert cols["lon"][0] is False, "NOT NULL was dropped by the rebuild"
    assert cols["job_number"][0] is False
    assert cols["borough"][0] is False
    assert cols["note"][0] is True, "a nullable column must stay nullable"
    assert cols["frame"][1] is not None and "lot" in cols["frame"][1], (
        "DEFAULT 'lot' was dropped by the rebuild")

    # the CHECK is on, the PK is on, and the rows survived
    assert migrate._has_check(con, "analysis.dev_pipeline")
    assert con.execute(
        "SELECT count(*) FROM analysis.dev_pipeline").fetchone()[0] == 2
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO analysis.dev_pipeline (job_number, borough, lon) "
                    "VALUES ('j3','QN',-73.8)")
    with pytest.raises(duckdb.Error):
        con.execute("INSERT INTO analysis.dev_pipeline (job_number, borough, lon) "
                    "VALUES ('j4','MN',NULL)")


# ------------------------------------ observation_category_check (GTM-198)

def _old_observation_fixture(tmp_path):
    """analysis.address_observation as the SHARED warehouse holds it: built
    from 036's DDL with the fifteen-slug CHECK sql/036 carried before
    2026-09-17, plus one row per branch. No init_schema -- 036 alone is the
    dependency this step has, and the fixture must not inherit a peer's
    in-flight migration."""
    from loci.categories import CATEGORIES
    con = duckdb.connect(str(tmp_path / "o.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    ddl = migrate._observation_create_ddl().replace("__TARGET__", "analysis.address_observation")
    # Strips BOTH new slugs (bathhouse_sauna 2026-09-17, brewery 2026-09-22,
    # D137) to simulate the genuinely-old fifteen-slug CHECK.
    ddl = ddl.replace(",\n                        'bathhouse_sauna', 'brewery')", ")")
    assert "'bathhouse_sauna'" not in ddl
    assert "'brewery'" not in ddl
    con.execute(ddl)
    con.execute("""INSERT INTO analysis.address_observation
        (observation_id, rec_id, category, status, created_at, observed_at, category_guess)
        VALUES ('o1', 'r1', 'grocery', 'open', now(), now(), 'grocery'),
               ('o2', 'r1', 'grocery', 'vacant', now(), now(), NULL)""")
    assert not migrate.probe_observation_category_check(con)
    assert all(f"'{s}'" in migrate._observation_check_text(con)
               for s in CATEGORIES if s not in ("bathhouse_sauna", "brewery"))
    return con


def test_observation_check_dry_run_writes_nothing(tmp_path):
    con = _old_observation_fixture(tmp_path)
    r = migrate.step_observation_category_check(con, apply=False)
    assert r.applied is False and r.before == {"rows": 2}
    assert any("DRY RUN" in n for n in r.notes)
    assert not migrate.probe_observation_category_check(con)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO analysis.address_observation "
                    "(observation_id, rec_id, category, status, created_at, observed_at, category_guess) "
                    "VALUES ('o3', 'r1', 'bathhouse_sauna', 'open', now(), now(), 'bathhouse_sauna')")


def test_observation_check_apply_widens_the_check_and_keeps_every_row(tmp_path, monkeypatch):
    con = _old_observation_fixture(tmp_path)
    # the step re-applies 036 after the swap; 036's index/view statements need
    # analysis.poi_presence and analysis.recommendation, which this bare fixture
    # does not have -- stub the re-apply to a no-op (the swap is what is tested).
    monkeypatch.setattr(migrate, "_reapply_036", lambda con: None)
    r = migrate.step_observation_category_check(con, apply=True)
    assert r.applied is True and r.before == r.after == {"rows": 2}
    assert migrate.probe_observation_category_check(con)
    con.execute("INSERT INTO analysis.address_observation "
                "(observation_id, rec_id, category, status, created_at, observed_at, category_guess) "
                "VALUES ('o3', 'r1', 'bathhouse_sauna', 'open', now(), now(), 'bathhouse_sauna')")
    assert con.execute("SELECT count(*) FROM analysis.address_observation").fetchone()[0] == 3
    # NOT NULL / PK survived the rebuild (the whole point of using 036's DDL)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO analysis.address_observation "
                    "(observation_id, rec_id, category, status, created_at, observed_at) "
                    "VALUES ('o1', 'r1', 'grocery', 'open', now(), now())")
    # a second run is a no-op
    r2 = migrate.step_observation_category_check(con, apply=True)
    assert r2.applied is False and any("already applied" in n for n in r2.notes)
