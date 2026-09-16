"""The pinned as-of date (model/supply_asof.py, owner ruling 2026-09-16).

What these tests hold down, in order of how badly each would hurt:

1. THE PREDICATE NO LONGER READS THE WALL CLOCK. Every SQL rendering embeds
   the scalar subquery over `analysis.supply_asof`, and `current_date` appears
   in none of them. A regression here brings back a supply hash that moves at
   midnight with no write -- the failure this module exists to remove.
2. ONE RULE, ONE DATE. The Python twin `poi_status()` and the SQL
   `poi_is_open()` must evaluate at the SAME date when neither caller passes
   one. Two clocks is how two renderings of one rule disagree.
3. THE YAML ROUND-TRIPS. `supply_asof` survives save/load and is distinct from
   `asof` (the wall-clock stamp), because conflating them is how the pin comes
   undone.
4. THE CLI DRY RUN WRITES NOTHING and still prices the move.
"""
from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from loci.model import poi_presence as pp
from loci.model import supply_asof as sa


def _con(tmp_path, asof=dt.date(2026, 9, 15)):
    c = duckdb.connect(str(tmp_path / "w.duckdb"))
    sa.ensure_table(c, default=asof)
    return c


# ------------------------------------------- 1. no wall clock in the rendering

def test_no_sql_rendering_of_the_predicate_reads_current_date():
    from loci.model import poi_evidence as pe

    for sql in (pp.poi_is_open(), pp.poi_status_basis(),
                pe.poi_status_date_sql(), pp.colocation_view_sql(),
                pp.colocation_view_sql(evidence=True)):
        assert "current_date" not in sql, (
            "a rendering of the open/closed predicate still reads current_date. "
            "A DuckDB view evaluates that at QUERY time, so the supply set and "
            "score/supply.supply_hash move at every midnight with no write.")
        assert sa.ASOF_SQL in sql


def test_the_committed_sql_file_carries_the_pin_too():
    import pathlib

    from loci import db as locidb

    text = (pathlib.Path(locidb.SQL_DIR) / "029_poi_colocation.sql").read_text()
    body = text[text.index("CREATE OR REPLACE VIEW"):]
    assert "current_date" not in body
    assert sa.ASOF_SQL in body
    # The generator is still the single source of the rule (the sql/029 rule).
    assert pp.colocation_view_sql().strip() in text


def test_an_explicit_date_still_wins_over_the_pin():
    """A caller that passes its own date is NOT overridden -- retrodiction
    evaluates the predicate at a historical cohort date and must keep doing so."""
    sql = pp.poi_is_open("p", "f.closed_on", "DATE '2023-01-01'")
    assert "DATE '2023-01-01'" in sql
    assert sa.ASOF_SQL not in sql


# ------------------------------------------------ 2. the predicate at a date

def test_licence_expiry_is_read_against_the_given_date_not_today():
    attrs = {"active": True, "active_basis": "valid_to_2026-09-15",
             "expires": "2026-09-15"}
    on_the_day, _ = pp.poi_status(attrs, source_id="nys_dos",
                                  today=dt.date(2026, 9, 15))
    the_day_after, basis = pp.poi_status(attrs, source_id="nys_dos",
                                         today=dt.date(2026, 9, 16))
    assert on_the_day == "open"
    assert the_day_after == "closed"
    assert basis.endswith("expired_2026-09-15")


def test_the_open_evidence_window_is_read_against_the_given_date():
    seen = dt.date(2026, 9, 15) - dt.timedelta(days=pp.OPEN_EVIDENCE_MAX_AGE_DAYS)
    attrs = {"active": True, "active_basis": "inspected_731d_ago",
             "last_inspection_date": seen.isoformat()}
    assert pp.poi_status(attrs, today=dt.date(2026, 9, 15))[0] == "open"
    assert pp.poi_status(attrs, today=dt.date(2026, 9, 16))[0] == "unknown"


def test_the_python_twin_defaults_to_the_baselines_asof(monkeypatch):
    """poi_status() with no `today` must use the SAME date the SQL rendering
    reads, not dt.date.today()."""
    pinned = dt.date(2026, 9, 15)
    monkeypatch.setattr(sa, "baseline_asof", lambda path=None: pinned)
    assert sa.default_today() == pinned
    attrs = {"active": True, "active_basis": "valid_to_2026-09-15",
             "expires": "2026-09-15"}
    # 2026-09-15 is NOT past the pin, so this must read open however long ago
    # the pin was set -- that is the whole point.
    assert pp.poi_status(attrs, source_id="nys_dos")[0] == "open"


def test_default_today_falls_back_to_the_wall_clock_only_with_no_baseline(monkeypatch):
    monkeypatch.setattr(sa, "baseline_asof", lambda path=None: None)
    assert sa.default_today() == dt.date.today()


# -------------------------------------------------------- 3. the table

def test_ensure_table_is_idempotent_and_seeds_once(tmp_path):
    c = _con(tmp_path)
    assert sa.read(c) == dt.date(2026, 9, 15)
    sa.ensure_table(c, default=dt.date(2020, 1, 1))     # must NOT re-seed
    assert sa.read(c) == dt.date(2026, 9, 15)
    assert c.execute(f"SELECT count(*) FROM {sa.TABLE}").fetchone()[0] == 1


def test_read_raises_rather_than_falling_back_to_today(tmp_path):
    c = duckdb.connect(str(tmp_path / "empty.duckdb"))
    with pytest.raises(RuntimeError, match="does not exist"):
        sa.read(c)
    c.execute("CREATE SCHEMA analysis")
    c.execute(f"CREATE TABLE {sa.TABLE} (pin VARCHAR, asof_date DATE)")
    with pytest.raises(RuntimeError, match="empty"):
        sa.read(c)


def test_write_moves_the_pin_and_records_why(tmp_path):
    c = _con(tmp_path)
    sa.write(c, dt.date(2026, 10, 1), set_by="test", reason="month roll")
    assert sa.read(c) == dt.date(2026, 10, 1)
    row = c.execute(f"SELECT set_by, reason FROM {sa.TABLE}").fetchone()
    assert row == ("test", "month roll")


def test_check_flags_a_baseline_fitted_at_another_date(tmp_path, monkeypatch):
    c = _con(tmp_path, asof=dt.date(2026, 9, 15))
    monkeypatch.setattr(sa, "baseline_asof", lambda path=None: dt.date(2026, 9, 15))
    assert sa.check(c)[2] is True
    monkeypatch.setattr(sa, "baseline_asof", lambda path=None: dt.date(2026, 9, 10))
    live, doc, agree = sa.check(c)
    assert (live, doc, agree) == (dt.date(2026, 9, 15), dt.date(2026, 9, 10), False)


# --------------------------------------------------- 4. the YAML round-trip

def test_baseline_yaml_round_trips_supply_asof(tmp_path):
    from loci.model.supply_ratio import load_baselines, save_baselines

    p = tmp_path / "supply_baseline.yaml"
    save_baselines({"supply_hash": "deadbeefcafe", "supply_set": "principled",
                    "asof": "2026-09-20", "supply_asof": "2026-09-15",
                    "categories": {}}, p)
    doc = load_baselines(p)
    assert doc["supply_asof"] == "2026-09-15"
    # `asof` is the wall-clock day the fit RAN and is a DIFFERENT field.
    assert doc["asof"] == "2026-09-20"
    assert sa.baseline_asof(p) == dt.date(2026, 9, 15)


def test_baseline_asof_falls_back_to_the_older_asof_field(tmp_path):
    """The shipped 2026-09-15 baseline predates `supply_asof`. Reading `asof`
    is what lets this change land WITHOUT re-stamping the YAML."""
    from loci.model.supply_ratio import save_baselines

    p = tmp_path / "supply_baseline.yaml"
    save_baselines({"supply_hash": "ba944e18c57b", "asof": "2026-09-15",
                    "categories": {}}, p)
    assert sa.baseline_asof(p) == dt.date(2026, 9, 15)


def test_the_live_baseline_yaml_resolves_to_a_date():
    from loci.model.supply_ratio import BASELINE_PATH

    if not BASELINE_PATH.exists():
        pytest.skip("baseline not fitted")
    assert isinstance(sa.baseline_asof(), dt.date)


# ------------------------------------------------------- 5. the freeze marker

def test_advance_refuses_while_a_freeze_marker_is_set(tmp_path, monkeypatch):
    c = _con(tmp_path)
    monkeypatch.setenv(sa.FREEZE_ENV, "1")
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda con, s="principled", **kw: "x" * 12)
    monkeypatch.setattr(sa, "status_flips", lambda con, a, b: None)
    with pytest.raises(RuntimeError, match="freeze marker"):
        sa.advance(c, to=dt.date(2026, 9, 20), dry_run=False)
    # A DRY RUN is still allowed during a freeze: it writes nothing.
    rep = sa.advance(c, to=dt.date(2026, 9, 20), dry_run=True)
    assert rep["freeze_marker"] and rep["dry_run"]
    assert sa.read(c) == dt.date(2026, 9, 15)


def test_advance_refuses_to_move_the_date_backwards(tmp_path, monkeypatch):
    c = _con(tmp_path)
    monkeypatch.delenv(sa.FREEZE_ENV, raising=False)
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda con, s="principled", **kw: "x" * 12)
    monkeypatch.setattr(sa, "status_flips", lambda con, a, b: None)
    with pytest.raises(RuntimeError, match="backwards"):
        sa.advance(c, to=dt.date(2026, 9, 1), dry_run=False)
    assert sa.read(c) == dt.date(2026, 9, 15)


def test_advance_dry_run_writes_nothing(tmp_path, monkeypatch):
    c = _con(tmp_path)
    monkeypatch.delenv(sa.FREEZE_ENV, raising=False)
    seen = {}

    def _hash(con, s="principled", **kw):
        seen.setdefault("asofs", []).append(kw.get("asof"))
        return "aaaaaaaaaaaa" if kw.get("asof") == dt.date(2026, 9, 15) else "bbbbbbbbbbbb"

    monkeypatch.setattr("loci.score.supply.supply_hash", _hash)
    monkeypatch.setattr(sa, "status_flips", lambda con, a, b: None)
    rep = sa.advance(c, to=dt.date(2026, 9, 16), dry_run=True)
    assert rep["hash_before"] == "aaaaaaaaaaaa"
    assert rep["hash_after"] == "bbbbbbbbbbbb"
    assert rep["moved"] is True
    assert seen["asofs"] == [dt.date(2026, 9, 15), dt.date(2026, 9, 16)]
    assert sa.read(c) == dt.date(2026, 9, 15), "a dry run moved the pin"


def test_advance_writes_when_not_a_dry_run(tmp_path, monkeypatch):
    c = _con(tmp_path)
    monkeypatch.delenv(sa.FREEZE_ENV, raising=False)
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda con, s="principled", **kw: "x" * 12)
    monkeypatch.setattr(sa, "status_flips", lambda con, a, b: None)
    rep = sa.advance(c, to=dt.date(2026, 9, 16), dry_run=False, reason="date roll")
    assert rep["moved"] is False               # same stub hash both sides
    assert sa.read(c) == dt.date(2026, 9, 16)


# ------------------------------------------------------------- 6. the CLI

def test_cli_supply_asof_advance_dry_run_writes_nothing(tmp_path, monkeypatch):
    """The command exists, takes --dry-run and --to, and opens the warehouse
    READ-ONLY on a dry run -- so it cannot move the pin even by accident."""
    from typer.testing import CliRunner

    from loci import cli as locicli

    wh = tmp_path / "w.duckdb"
    c = duckdb.connect(str(wh))
    sa.ensure_table(c, default=dt.date(2026, 9, 15))
    c.close()

    opened = {}

    def _connect(path=None, read_only=False):
        opened["read_only"] = read_only
        return duckdb.connect(str(wh), read_only=read_only)

    monkeypatch.setattr(locicli.locidb, "connect", _connect)
    monkeypatch.setattr("loci.score.supply.supply_hash",
                        lambda con, s="principled", **kw: "x" * 12)
    monkeypatch.setattr(sa, "status_flips", lambda con, a, b: None)
    monkeypatch.delenv(sa.FREEZE_ENV, raising=False)

    res = CliRunner().invoke(locicli.app,
                             ["supply-asof", "advance", "--to", "2026-09-16",
                              "--dry-run"])
    assert res.exit_code == 0, res.output
    assert opened["read_only"] is True
    assert "nothing written" in res.output

    c = duckdb.connect(str(wh), read_only=True)
    try:
        assert sa.read(c) == dt.date(2026, 9, 15)
    finally:
        c.close()
