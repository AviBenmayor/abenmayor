"""AC-18, AC-20: `loci.report.ledger.Budget`/`CapExceeded`. Uses only
`analysis.spend_ledger` (sql/033), so an in-memory `db.init_schema()` is
enough -- no address/POI fixture needed here."""
from __future__ import annotations

import logging

import pytest

import loci.db as locidb
from loci.report.ledger import PRICES, Budget, CapExceeded


def _db():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    return con


def test_charge_writes_a_ledger_row_and_spent_reflects_it():
    con = _db()
    b = Budget(run_id="r1", cap_usd=1.0, con=con)
    b.charge("places", PRICES["places"])
    assert b.spent() == pytest.approx(PRICES["places"])
    run_id, kind, provider, usd = con.execute(
        "SELECT run_id, kind, provider, usd FROM analysis.spend_ledger").fetchone()
    assert (run_id, kind, provider) == ("r1", "report", "places")
    assert float(usd) == pytest.approx(PRICES["places"])


def test_charge_raises_before_exceeding_the_cap_and_writes_nothing():
    con = _db()
    b = Budget(run_id="r2", cap_usd=0.05, con=con)
    b.charge("places", 0.032)        # affordable: 0.032 <= 0.05
    with pytest.raises(CapExceeded):
        b.charge("places", 0.032)    # 0.064 > 0.05: must abort BEFORE writing
    assert b.spent() == pytest.approx(0.032)   # only the first charge landed
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 1


def test_cap_hit_is_logged(caplog):
    con = _db()
    b = Budget(run_id="r3", cap_usd=0.01, con=con)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(CapExceeded):
            b.charge("tavily", 0.008)
            b.charge("tavily", 0.008)
    assert any("budget_hit" in r.message for r in caplog.records)


def test_reserved_usd_counts_against_can_afford():
    con = _db()
    b = Budget(run_id="r4", cap_usd=0.10, con=con)
    b.reserve(0.09)
    assert b.can_afford(0.01) is True
    assert b.can_afford(0.02) is False
    with pytest.raises(CapExceeded):
        b.charge("tavily", 0.02)
    b.release_reserve(0.09)
    assert b.can_afford(0.02) is True


def test_dry_run_never_writes_the_ledger_and_only_plans():
    con = _db()
    b = Budget(run_id="r5", cap_usd=1.0, con=con, dry_run=True)
    b.charge("places", PRICES["places"], detail="poi:1")
    b.charge("tavily", PRICES["tavily"], detail="search:rents")
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0
    assert b.spent() == 0.0
    assert len(b.plan) == 2
    assert b.plan_total() == pytest.approx(PRICES["places"] + PRICES["tavily"])


def test_dry_run_never_raises_capexceeded_even_over_cap():
    con = _db()
    b = Budget(run_id="r6", cap_usd=0.01, con=con, dry_run=True)
    b.charge("places", PRICES["places"])     # 0.032 > 0.01 cap, but dry-run never raises
    b.charge("places", PRICES["places"])
    assert len(b.plan) == 2
    assert con.execute("SELECT count(*) FROM analysis.spend_ledger").fetchone()[0] == 0


def test_true_up_corrects_the_same_row_not_a_second_one():
    con = _db()
    b = Budget(run_id="r7", cap_usd=1.0, con=con)
    b.charge("anthropic", 0.45, detail="prose")
    b.true_up("anthropic", "prose", 0.41)
    rows = con.execute(
        "SELECT usd FROM analysis.spend_ledger WHERE run_id = 'r7' AND provider = 'anthropic'"
    ).fetchall()
    assert len(rows) == 1
    assert float(rows[0][0]) == pytest.approx(0.41)


def test_invalid_kind_and_provider_are_rejected():
    con = _db()
    with pytest.raises(ValueError):
        Budget(run_id="r8", cap_usd=1.0, con=con, kind="nonsense")
    b = Budget(run_id="r9", cap_usd=1.0, con=con)
    with pytest.raises(ValueError):
        b.charge("carrier_pigeon", 0.01)
