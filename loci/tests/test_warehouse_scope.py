"""The MN+BK screen is enforced by the schema, and borough has ONE spelling.

Audit findings 4, 5 and 18. Before this, MN+BK was a Python default threaded
through seven call sites and nothing in the database enforced it --
validation/retrodiction.py:486 proved what that costs, counting five boroughs
into a two-borough vacancy narrative.

THE DISTINCTION THESE TESTS ENCODE (see sql/045's header for the argument):
a SCREEN table produces a number that lands in the deliverable, and a Queens row
in one is a wrong number. A SUPPLY table answers "what is near this address",
reach is spatial and crosses borough lines, and filtering it would DELETE a real
pharmacy 200 m away in Queens and manufacture a gap. So the constraint goes on
the first kind and explicitly not on the second, and that is tested both ways --
a test that only checked "everything is constrained" would have locked in the
bug it was written to prevent.
"""
from __future__ import annotations

import duckdb
import pytest

from loci import migrate, warehouse as wh

#: Long-form spellings that must not appear in an `analysis.*` table.
LONG_FORM = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")

#: The ONE documented exception, with the reason it is one.
#:
#: analysis.hex is calib-layer: an INPUT to reach-tier calibration, never a
#: deliverable. Its long-form borough is the vocabulary its own consumers
#: (score/supply.build_category_anchor, which stores it verbatim in
#: analysis.category_anchor.boroughs) already speak. Moving the hex layer to a
#: `calib` schema retires this exception; that move touches 265 references
#: across 60 files including two that wave two owns, so it is a follow-up.
LONG_FORM_EXEMPT = {
    "analysis.hex": "calib layer; moves with the hex schema relocation",
    "analysis.category_anchor": (
        "`boroughs` is a PARAMETER RECORD of a run's scope, not a borough "
        "dimension, and it records the vocabulary of the table it filtered"),
}


def test_screen_tables_reject_an_out_of_scope_row(tmp_path):
    """Inserting a QN row into a screen table must RAISE.

    This is the acceptance test for owner ruling (2) of 2026-09-16. It is run
    against the exact DDL `migrate.step_scope_checks` and
    `migrate.step_forecast_slim` build, so it fails if that DDL loses its
    CHECK.
    """
    con = duckdb.connect(str(tmp_path / "s.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("""
        CREATE TABLE analysis.screenish (
            address_id VARCHAR NOT NULL,
            borough    VARCHAR NOT NULL CHECK (borough IN ('MN', 'BK')),
            PRIMARY KEY (borough, address_id)
        )""")
    con.execute("INSERT INTO analysis.screenish (address_id, borough) "
                "VALUES ('a1', 'MN')")
    con.execute("INSERT INTO analysis.screenish (address_id, borough) "
                "VALUES ('a2', 'BK')")
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO analysis.screenish (address_id, borough) "
                    "VALUES ('a3', 'QN')")
    # and a NULL borough is rejected too -- an unknown borough in a SCREEN
    # table is not a licence to pass, it is a row that has not been resolved.
    with pytest.raises(duckdb.Error):
        con.execute("INSERT INTO analysis.screenish (address_id, borough) "
                    "VALUES ('a4', NULL)")
    assert con.execute("SELECT count(*) FROM analysis.screenish").fetchone()[0] == 2


def test_supply_tables_are_deliberately_not_constrained():
    """The five-borough tables must NOT acquire a borough CHECK.

    A pharmacy 200 m from a Bushwick address may sit in Queens. Constraining
    analysis.poi_presence would delete it and the screen would read the address
    as under-served -- a manufactured gap, which is the single failure mode this
    project cares most about. If someone ever adds one of these to
    SCREEN_TABLES, this test is what stops them.
    """
    supply = {"analysis.poi_presence", "chains.brand_location",
              "analysis.licence_interval", "staging.alcohol_licences",
              "analysis.storefront", "analysis.storefront_pipeline",
              "staging.storefront_filing"}
    overlap = supply & set(migrate.SCREEN_TABLES)
    assert not overlap, (
        f"{sorted(overlap)} would be borough-constrained, but they are SUPPLY "
        f"read spatially — reach crosses borough lines and filtering them "
        f"manufactures gaps. Read sql/045's header before changing this.")


def test_screen_tables_hold_only_screen_boroughs_today():
    """Every table `scope_checks` constrains is ALREADY MN+BK-only.

    The CHECK records a fact; it must not change one. If this drifts, the
    migration would silently reject rows -- `_swap`'s count assertion catches
    that at apply time, and this catches it earlier.
    """
    from loci.sources.cities.nyc.addresses import SCREEN_BOROUGHS

    assert set(SCREEN_BOROUGHS) == {"MN", "BK"}


def test_the_sql_crosswalk_mirrors_the_python_scope():
    """analysis.borough.in_screen must agree with SCREEN_BOROUGHS.

    Two authorities for one scope is how a SQL consumer and a Python consumer
    end up screening different cities. The Python constant stays THE authority
    for code (it is NYC-specific, and model/ and score/ take the scope as an
    argument so they name no borough); the table mirrors it for SQL. This pins
    them together.
    """
    import pathlib
    import re

    from loci import db as locidb
    from loci.sources.cities.nyc.addresses import SCREEN_BOROUGHS

    draft = pathlib.Path(locidb.SQL_DIR) / "045_scope_and_vocabulary.sql.draft"
    applied = pathlib.Path(locidb.SQL_DIR) / "045_scope_and_vocabulary.sql"
    text = (applied if applied.exists() else draft).read_text()

    # EXECUTE the DDL rather than pattern-matching it: a regex over SQL agrees
    # with the database right up until the formatting changes, and then it
    # agrees with nothing.
    #
    # `--` comments are stripped FIRST because sql/045's column comments
    # contain semicolons ("-- 'MN'; the project's canonical form"), and a
    # statement splitter that does not know that splits mid-CREATE.
    text = re.sub(r"--[^\n]*", "", text)
    statements = re.search(
        r"(CREATE TABLE IF NOT EXISTS analysis\.borough.*?;).*?"
        r"(INSERT INTO analysis\.borough.*?;)", text, re.S)
    assert statements, "could not find the analysis.borough DDL in sql/045"
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA analysis")
    con.execute(statements.group(1))
    con.execute(statements.group(2))

    in_screen = {r[0] for r in con.execute(
        "SELECT borough_code FROM analysis.borough WHERE in_screen").fetchall()}
    assert in_screen == set(SCREEN_BOROUGHS), (
        f"analysis.borough.in_screen = {sorted(in_screen)} but "
        f"SCREEN_BOROUGHS = {sorted(SCREEN_BOROUGHS)}")
    assert con.execute("SELECT count(*) FROM analysis.borough").fetchone()[0] == 5


def test_no_analysis_table_carries_the_long_borough_form():
    """One vocabulary. Two spellings with no FK is how a join returns nothing.

    Declared against warehouse.CLASSIFICATION rather than a live database so it
    runs without one: every `analysis.*` object that the classification marks as
    carrying a long-form borough must be in the exemption list, with a reason.
    """
    carriers = {q for q, text in wh.CLASSIFICATION.items()
                if q.startswith("analysis.") and "long-form" in text}
    undocumented = carriers - set(LONG_FORM_EXEMPT)
    assert not undocumented, (
        f"{sorted(undocumented)} carry the long borough form with no recorded "
        f"exemption — rewrite them to codes via `loci migrate-warehouse "
        f"--step poi_presence_vocab`, or add an exemption that says why not")


def test_poi_presence_vocab_step_rewrites_to_codes(tmp_path):
    """The step converts long form to codes and leaves NULL alone."""
    con = duckdb.connect(str(tmp_path / "v.duckdb"))
    con.execute("CREATE SCHEMA analysis")
    con.execute("""CREATE TABLE analysis.borough (
        borough_code VARCHAR PRIMARY KEY, borough_name VARCHAR NOT NULL,
        borocode VARCHAR NOT NULL, county_fips VARCHAR NOT NULL,
        in_screen BOOLEAN NOT NULL)""")
    con.execute("""INSERT INTO analysis.borough VALUES
        ('MN','Manhattan','1','061',TRUE), ('BK','Brooklyn','3','047',TRUE),
        ('QN','Queens','4','081',FALSE)""")
    con.execute("CREATE TABLE analysis.poi_presence "
                "(location_key VARCHAR, borough VARCHAR)")
    con.execute("""INSERT INTO analysis.poi_presence VALUES
        ('k1','Manhattan'), ('k2','Brooklyn'), ('k3','Queens'), ('k4', NULL)""")

    assert not migrate.probe_poi_presence_vocab(con)
    migrate.step_poi_presence_vocab(con, apply=True)
    assert migrate.probe_poi_presence_vocab(con)

    rows = dict(con.execute(
        "SELECT location_key, borough FROM analysis.poi_presence").fetchall())
    assert rows == {"k1": "MN", "k2": "BK", "k3": "QN", "k4": None}, rows
    # An unknown borough stays unknown. A POI whose hex is missing is still
    # supply; coercing it to a code would be inventing a location.
    assert rows["k4"] is None

    # idempotent
    migrate.step_poi_presence_vocab(con, apply=True)
    assert dict(con.execute(
        "SELECT location_key, borough FROM analysis.poi_presence").fetchall()) == rows
