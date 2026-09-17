"""The warehouse inventory is generated, complete, and mechanically checked.

These tests build a FRESH database from every migration on disk -- including
the `.sql.draft` files staged for the Phase B go, renamed into a temp SQL
directory -- so the drafts are proven to apply cleanly BEFORE anything touches
the shared warehouse. That is the point of the two-phase split.
"""
from __future__ import annotations

import pathlib
import shutil

import duckdb
import pytest

from loci import db as locidb
from loci import warehouse as wh

SQL_DIR = pathlib.Path(locidb.SQL_DIR)


def _staged_sql_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Every *.sql plus every *.sql.draft, with the drafts un-suffixed.

    Phase A keeps the migrations as `.sql.draft` precisely because
    `db.init_schema` applies every *.sql on disk in every session and a shared
    warehouse with an ingest running is not where untested DDL should land by
    accident. Here, in a temp directory against a temp database, applying them
    is exactly what we want.
    """
    staged = tmp_path / "sql"
    staged.mkdir()
    for path in sorted(SQL_DIR.iterdir()):
        if path.suffix == ".sql" or path.name.endswith(".yaml"):
            shutil.copy(path, staged / path.name)
        elif path.name.endswith(".sql.draft"):
            shutil.copy(path, staged / path.name[: -len(".draft")])
    return staged


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A fresh warehouse with every migration AND every draft applied."""
    tmp_path = tmp_path_factory.mktemp("warehouse")
    staged = _staged_sql_dir(tmp_path)
    target = tmp_path / "w.duckdb"
    con = duckdb.connect(str(target))
    con.execute((staged / "001_bootstrap.sql").read_text())
    original = locidb.SQL_DIR
    locidb.SQL_DIR = staged
    try:
        locidb.init_schema(con)
    finally:
        locidb.SQL_DIR = original
    # The classification is applied AFTER the sweep, never inside it: a
    # CREATE OR REPLACE VIEW drops the view's comment, so anything written
    # mid-sweep would be silently erased by a later migration.
    wh.apply_classification(con)
    yield con
    con.close()


def test_drafts_apply_to_a_fresh_database(built):
    """The Phase B migrations are not hypothetical -- they run."""
    names = {f"{o.schema}.{o.name}" for o in wh.catalog(built)}
    # created by 045
    assert "analysis.borough" in names
    assert "analysis.storefront_year" in names
    assert "analysis.storefront_screen" in names
    # dropped by 046, even though 004/010/019/020 re-create them earlier in the
    # same sweep -- 046 sorts after, which is what makes the drop stick.
    assert "analysis.address_laundry_gaps" not in names
    assert "analysis.storefront_pipeline_census" not in names
    assert "staging.storefront_filing_census" not in names


def test_every_object_states_its_grain(built):
    """No object may exist without layer, grain and key.

    This is "inventory before adding a table" (owner, 2026-09-09) made
    mechanical: add an `analysis.*` object without a row in
    sql/051_warehouse_catalog.sql and this test names it.
    """
    unclassified = sorted(o.qualified for o in wh.catalog(built) if not o.layer)
    assert not unclassified, (
        "these objects carry no 'layer=…; grain=…; key=…' comment — add them "
        "to warehouse.CLASSIFICATION in the same edit that created them: "
        + ", ".join(unclassified))


def test_layers_are_the_declared_set(built):
    for obj in wh.catalog(built):
        assert obj.layer in wh.LAYERS, f"{obj.qualified} has layer={obj.layer!r}"


def test_new_object_without_a_row_fails_the_check(built, tmp_path):
    """The drift check must actually catch a new, undeclared object."""
    built.execute("CREATE TABLE analysis.sneaky_new_table (x INTEGER)")
    try:
        errors = wh.drift(built)
        assert any("sneaky_new_table" in e for e in errors), errors
    finally:
        built.execute("DROP TABLE analysis.sneaky_new_table")


def test_render_is_deterministic(built):
    objects = wh.catalog(built)
    counts = wh.readers(objects)
    assert wh.render(objects, counts) == wh.render(objects, counts)


def test_reader_scan_resolves_module_constants():
    """A literal grep undercounts, and an undercount is what makes a live
    object look droppable.

    `staging.poi_closure` is reached through `TABLE = "staging.poi_closure"` in
    model/poi_closure.py, interpolated into f-strings. The audit flagged this
    exact failure mode.
    """
    objects = [wh.Object("staging", "poi_closure", "table", "staging",
                         "one venue", "fsq_place_id", None, 0)]
    counts = wh.readers(objects)
    assert counts["staging.poi_closure"] > 1, (
        "reader scan did not resolve the module-level TABLE constant")
