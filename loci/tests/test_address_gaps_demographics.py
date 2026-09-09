"""Drift test: the address screen's demographic carrier is
`analysis.address_demographics`, and it must not fall behind
`analysis.hex_demographics`.

HISTORY. This file used to assert the opposite arrangement -- that
model/address_gaps.py copied all 36 hex_demographics measure columns onto every
address row by CONTAINING HEX (sql/008, first version). D56 replaced that with
analysis.address_demographics, which takes each value DIRECTLY from the lot's
own 2020 census tract via PLUTO's bct2020: a BBL lookup, not an apportionment
followed by a containment step. The old copy is gone, so the assertions here
are inverted -- but the OWNER RULE they encode is unchanged, and is the reason
the file survives at all: a demographic that lands only on the hex grid is not
delivered, because nothing the owner looks at reads a hex table (D38).

So: every measure on hex_demographics must have a twin on
address_demographics, every estimate must carry its `_moe`, and the gap tables
must carry NO demographic columns at all (one number, one place).
"""
import pytest

from loci import db as locidb
from loci.model.address_demographics import (
    ADDRESS_DEMOGRAPHICS_COLUMNS,
    ADDRESS_DEMOGRAPHICS_MEASURES,
)

#: Identity/provenance columns on the two tables -- everything else is a measure.
_HEX_KEYS = {"h3_index", "acs_year"}
_ADDR_KEYS = {"address_id", "bbl", "tract_geoid", "acs_year"}


@pytest.fixture(scope="module")
def cols():
    con = locidb.connect(":memory:")
    locidb.init_schema(con)

    def _of(table: str) -> list[str]:
        return [r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analysis' AND table_name = ? "
            "ORDER BY ordinal_position", [table]).fetchall()]

    out = {t: _of(t) for t in
           ("hex_demographics", "address_demographics", "address", "address_category")}
    con.close()
    return out


def test_every_hex_demographic_measure_has_an_address_twin(cols):
    """THE drift test. Adding a measure to grid/acs.py (and so to
    hex_demographics) without adding it to address_demographics would strand it
    on the geography the project no longer uses -- the exact failure D38/D56
    exist to prevent. Both column lists are generated from grid/acs.py's own
    SHARE_SPECS/INTENSIVE_SPECS, so this should only ever fail when someone
    hand-adds a column to one DDL and not the other."""
    hex_measures = {c for c in cols["hex_demographics"] if c not in _HEX_KEYS}
    addr_measures = {c for c in cols["address_demographics"] if c not in _ADDR_KEYS}
    stranded = sorted(hex_measures - addr_measures)
    assert not stranded, (
        f"stranded on the hex grid with no address twin: {stranded} -- add them to "
        "model/address_demographics.py and sql/008_address_demographics.sql")


def test_address_demographics_table_matches_the_module_constant(cols):
    """The live DDL and ADDRESS_DEMOGRAPHICS_COLUMNS must agree, so an edit to
    one without the other fails here rather than writing a mis-shaped row."""
    assert sorted(cols["address_demographics"]) == sorted(ADDRESS_DEMOGRAPHICS_COLUMNS)


def test_every_address_estimate_carries_its_moe(cols):
    """CONTEXT.md 7.8: ACS margins of error are propagated, never dropped. A
    consumer must not be able to pick up a share without being able to see its
    precision."""
    for measure in ADDRESS_DEMOGRAPHICS_MEASURES:
        assert f"{measure}_moe" in ADDRESS_DEMOGRAPHICS_COLUMNS, \
            f"{measure} is carried without its MOE"
        assert f"{measure}_moe" in cols["address_demographics"], \
            f"{measure}_moe is missing from the DDL"


def test_the_gap_tables_carry_no_demographics(cols):
    """One number, one place. analysis.address / analysis.address_category must
    not re-acquire a demographic column: two median_hh_income values for the
    same address, differing because one was hex-interpolated, is the concrete
    harm D56 removed. h3_index survives on analysis.address as the borough/NTA
    join key and the roll-up-to-grid key -- it is geometry, not demography."""
    measures = {c for c in cols["hex_demographics"] if c not in _HEX_KEYS}
    for table in ("address", "address_category"):
        leaked = sorted(measures & set(cols[table]))
        assert not leaked, (
            f"analysis.{table} carries demographic columns {leaked} -- join "
            "analysis.address_demographics on address_id instead")
    assert "h3_index" in cols["address"]
