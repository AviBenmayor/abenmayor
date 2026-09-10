"""StreetEasy advertised-laundry parser, slug construction, and budget.

Fixtures in tests/fixtures/listings/ are REAL Tavily markdown captured from the
2026-09-08 probe (navigation chrome trimmed), not hand-written mockups. The
whole point of this source is that its silences are meaningless, so the tests
that matter most are the ones asserting a NULL rather than a False.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from loci.sources.cities.nyc import listings as L

FIX = pathlib.Path(__file__).parent / "fixtures" / "listings"


def md(name: str) -> str:
    return (FIX / name).read_text()


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def test_in_building_laundry_detected():
    p = L.parse_streeteasy(
        "https://streeteasy.com/building/51-schermerhorn-street-brooklyn/1l",
        md("se_in_building.md"))
    assert p.laundry_in_building is True
    assert p.laundry_in_unit is None        # building laundry is not in-unit laundry
    assert p.amenities_present is True
    assert p.unit == "1L"
    assert p.address_raw == "51 Schermerhorn Street, Brooklyn, NY 11201"
    assert p.borough == "Brooklyn"


def test_in_unit_laundry_detected_and_not_promoted_to_building():
    """109 Montague 3R lists Washer/dryer under Home features while Building
    amenities says 'No info'. In-unit must NOT leak into in-building."""
    p = L.parse_streeteasy(
        "https://streeteasy.com/building/109-montague-street-brooklyn/3r",
        md("se_in_unit.md"))
    assert p.laundry_in_unit is True
    assert p.laundry_in_building is None
    assert p.laundry_none is None


def test_absent_amenity_block_yields_all_null():
    """A building page with 'No info on amenities' is UNKNOWN, not NO."""
    p = L.parse_streeteasy(
        "https://streeteasy.com/building/1156-bergen-avenue-brooklyn",
        md("se_absent.md"))
    assert p.amenities_present is False
    assert p.laundry_in_building is None
    assert p.laundry_in_unit is None
    assert p.laundry_none is None
    assert p.unit is None
    assert p.status == "no_listing"


def test_silence_is_not_absence():
    """CAVEAT ZERO. 42 Carlton Ave 3L carries a real amenity list (Doorman,
    Live-in super) and omits laundry -- while 4A in the SAME BUILDING lists
    'Laundry in building'. The silent listing must never report False."""
    silent = L.parse_streeteasy(
        "https://streeteasy.com/building/42-carlton-avenue-brooklyn/3l",
        md("se_silent.md"))
    loud = L.parse_streeteasy(
        "https://streeteasy.com/building/42-carlton-avenue-brooklyn/4a",
        md("se_carlton_yes.md"))
    assert loud.laundry_in_building is True
    assert silent.amenities_present is True          # a real list was present...
    assert silent.laundry_in_building is None        # ...and it still tells us nothing
    assert silent.laundry_none is None               # emphatically not a negative


def test_explicit_negative_is_the_only_route_to_false():
    body = md("se_silent.md").replace("Doorman", "No laundry")
    p = L.parse_streeteasy("https://streeteasy.com/building/x-brooklyn/1a", body)
    assert p.laundry_none is True


def test_hookup_is_not_a_machine():
    body = ("## Home features\n\n*   Washer/dryer hookup\n\n"
            "## Building amenities\n\nNo info on building amenities\n")
    p = L.parse_streeteasy("https://streeteasy.com/building/x-brooklyn/1a", body)
    assert p.laundry_in_unit is None


def test_coordinates_and_listed_date():
    p = L.parse_streeteasy(
        "https://streeteasy.com/building/51-schermerhorn-street-brooklyn/1l",
        md("se_in_building.md"))
    assert p.page_lat == pytest.approx(40.691032)   # center=<lat>,<lon>, not lon,lat
    assert p.page_lon == pytest.approx(-73.9914)
    assert -74.3 < p.page_lon < -73.6 and 40.4 < p.page_lat < 41.0
    assert p.listed_date == dt.date(2025, 6, 5)
    assert p.status == "past"


# --------------------------------------------------------------------------
# Address normalization / URL construction
# --------------------------------------------------------------------------
@pytest.mark.parametrize("addr,boro,slug", [
    ("1156 BERGEN AVENUE", "BK", "1156-bergen-avenue-brooklyn"),
    ("1103 EAST 72 STREET", "BK", "1103-east-72-street-brooklyn"),
    ("8810 7 AVENUE", "BK", "8810-7-avenue-brooklyn"),
    ("31 89 STREET", "BK", "31-89-street-brooklyn"),
    ("42  Carlton   Ave.", "BK", "42-carlton-ave-brooklyn"),
])
def test_slug_for(addr, boro, slug):
    assert L.slug_for(addr, boro) == slug


def test_slug_rejects_empty():
    with pytest.raises(ValueError):
        L.slug_for("   ", "BK")


def test_manhattan_emits_both_slug_forms():
    urls = L.candidate_urls("100 WEST 57 STREET", "MN")
    assert urls == ["https://streeteasy.com/building/100-west-57-street",
                    "https://streeteasy.com/building/100-west-57-street-manhattan"]


def test_unit_url_gate_rejects_a_different_street():
    """Searching '78 Marcy Avenue Brooklyn' really returns
    /building/78-division-avenue-brooklyn at 0.63. Accepting it would attach
    one building's amenities to another building's BBL."""
    hits = [
        {"url": "https://streeteasy.com/building/78-division-avenue-brooklyn", "score": 0.63},
        {"url": "https://streeteasy.com/building/78-marcy-avenue-brooklyn", "score": 0.94},
        {"url": "https://streeteasy.com/building/78-marcy-avenue-brooklyn/3a", "score": 0.91},
        {"url": "https://streeteasy.com/building/78-marcy-avenue-brooklyn/1b", "score": 0.40},
    ]
    got = L.unit_urls_for("78-marcy-avenue-brooklyn", hits)
    assert got == ["https://streeteasy.com/building/78-marcy-avenue-brooklyn/3a"]


# --------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------
def test_budget_raises_at_cap():
    b = L.TavilyBudget(max_calls=2)
    b.reserve("search"); b.reserve("extract")
    with pytest.raises(L.BudgetExceeded):
        b.reserve("extract")
    assert b.calls == 2


def test_budget_cannot_exceed_hard_ceiling():
    with pytest.raises(ValueError):
        L.TavilyBudget(max_calls=L.MAX_CALLS_CEILING + 1)


def test_budget_records_credits_separately_from_calls():
    b = L.TavilyBudget(max_calls=5)
    b.reserve("extract", 20)
    b.record(endpoint="extract", n_urls=20, credits=4.0, http_status=200, n_ok=20, n_failed=0)
    assert (b.calls, b.credits) == (1, 4.0)     # one call, four credits


class _NoNetwork:
    def post(self, *a, **k):                     # pragma: no cover
        raise AssertionError("dry-run made a network call")


def test_dry_run_makes_no_network_calls():
    targets = [{"bbl": "3000010001", "address": "1 MAIN STREET", "borough": "BK",
                "lon": -73.9, "lat": 40.6}] * 3
    f = L.TavilyFetcher.__new__(L.TavilyFetcher)
    f.s = _NoNetwork()
    f.budget = L.TavilyBudget(max_calls=1)
    out = L.build_listings(None, targets, dry_run=True, fetcher=f)
    assert out["dry_run"] is True
    assert out["calls"] == out["search_calls"] + out["extract_calls"]
    assert out["credits"] > 0


def test_plan_arithmetic():
    p = L.plan([{}] * 10, units_per_address=4)
    assert p["search_calls"] == 10                 # one search per address
    assert p["extract_calls"] == 2                 # 40 URLs / batch of 20
    assert p["search_credits"] == 10
    assert p["extract_credits"] == 16              # 2 credits per 5 URLs, 40 URLs


def test_total_failure_raises_rather_than_writing_zero():
    class Dead(L.TavilyFetcher):
        def __init__(self):
            self.budget = L.TavilyBudget(max_calls=10)
        def search_building(self, address, borough):
            self.budget.reserve("search")
            self.budget.record(endpoint="search", n_urls=1, credits=None,
                               http_status=503, n_ok=0, n_failed=1)
            return []
    with pytest.raises(L.SourceUnavailable):
        L.build_listings(None, [{"bbl": "3000010001", "address": "1 MAIN STREET",
                                 "borough": "BK", "lon": -73.9, "lat": 40.6}],
                         max_calls=10, fetcher=Dead())


# --------------------------------------------------------------------------
# Throttling. Tavily BILLS the URLs it fails to render, so a failed URL is a
# spent credit with nothing to show for it. The Bay Ridge pilot (run
# a48a0a69650a) failed 151 of 301 extract URLs, all-or-nothing per call, at a
# rate that climbed 23% -> 82% across the run. These two tests pin the
# machinery that makes a retry pass cheap and a long sweep survivable.
# --------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, body):
        self.status_code, self._b = 200, body

    def json(self):
        return self._b


def test_failed_extract_urls_are_recorded_not_silently_dropped():
    body = {
        "usage": {"credits": 2},
        "results": [{"url": "https://streeteasy.com/building/x-brooklyn/1a",
                     "raw_content": "## Amenities\n\n* Doorman\n"}],
        "failed_results": [{"url": "https://streeteasy.com/building/x-brooklyn/2b",
                            "error": "timeout"},
                           {"url": "https://streeteasy.com/building/x-brooklyn/3c/"}],
    }

    class _S:
        headers = {}
        def post(self, *a, **k):
            return _FakeResp(body)

    f = L.TavilyFetcher(L.TavilyBudget(max_calls=5), api_key="k", session=_S())
    out = f.extract(["https://streeteasy.com/building/x-brooklyn/1a",
                     "https://streeteasy.com/building/x-brooklyn/2b",
                     "https://streeteasy.com/building/x-brooklyn/3c"])
    assert len(out) == 1                                    # only the page that rendered
    assert f.failed_urls == ["https://streeteasy.com/building/x-brooklyn/2b",
                             "https://streeteasy.com/building/x-brooklyn/3c"]
    # the credit was still spent, and the log has to say so
    assert f.budget.credits == 2 and f.budget.log[0]["n_failed"] == 2


def test_pace_throttles_between_calls_but_not_before_the_first(monkeypatch):
    slept = []
    monkeypatch.setattr(L.time, "sleep", lambda s: slept.append(s))

    class _S:
        headers = {}
        def post(self, *a, **k):
            return _FakeResp({"usage": {"credits": 1}, "results": []})

    f = L.TavilyFetcher(L.TavilyBudget(max_calls=5), api_key="k", session=_S(), pace_s=1.5)
    f.search_building("1 MAIN STREET", "BK")
    assert slept == []                                      # first call is not delayed
    f.search_building("2 MAIN STREET", "BK")
    f.search_building("3 MAIN STREET", "BK")
    assert slept == [1.5, 1.5]


# --------------------------------------------------------------------------
# Manhattan slug forms. StreetEasy uses BOTH /building/<addr> and
# /building/<addr>-manhattan. `slug_for` returns only the bare form for MN, so
# gating on it alone would reject every -manhattan unit page and report the
# Manhattan half of a sweep as zero coverage -- a fabricated gap.
# --------------------------------------------------------------------------
def test_manhattan_accept_list_covers_both_slug_forms():
    assert L.slugs_for("100 WEST 57 STREET", "MN") == (
        "100-west-57-street", "100-west-57-street-manhattan")
    assert L.slugs_for("42 CARLTON AVENUE", "BK") == ("42-carlton-avenue-brooklyn",)

    hits = [
        {"url": "https://streeteasy.com/building/100-west-57-street/12a", "score": 0.9},
        {"url": "https://streeteasy.com/building/100-west-57-street-manhattan/3b", "score": 0.9},
        {"url": "https://streeteasy.com/building/100-west-58-street-manhattan/1a", "score": 0.9},
        {"url": "https://streeteasy.com/building/100-west-57-street-manhattan", "score": 0.9},
    ]
    got = L.unit_urls_for(L.slugs_for("100 WEST 57 STREET", "MN"), hits)
    assert got == ["https://streeteasy.com/building/100-west-57-street/12a",
                   "https://streeteasy.com/building/100-west-57-street-manhattan/3b"]


# --------------------------------------------------------------------------
# Adaptive throttle
# --------------------------------------------------------------------------
def _fetcher(body, **kw):
    class _S:
        headers = {}
        def post(self, *a, **k):
            return _FakeResp(body() if callable(body) else body)
    return L.TavilyFetcher(L.TavilyBudget(max_calls=50), api_key="k", session=_S(), **kw)


def test_all_failed_extract_backs_off_and_a_clean_call_decays(monkeypatch):
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    state = {"fail": True}

    def body():
        if state["fail"]:
            return {"usage": {"credits": 2}, "results": [],
                    "failed_results": [{"url": "https://streeteasy.com/building/x-brooklyn/1a"}]}
        return {"usage": {"credits": 2},
                "results": [{"url": "https://streeteasy.com/building/x-brooklyn/1a",
                             "raw_content": "## Amenities\n\n*   Doorman\n"}],
                "failed_results": []}

    f = _fetcher(body, pace_s=1.0, cooldown_s=30.0, max_pace_s=8.0)
    f.extract(["https://streeteasy.com/building/x-brooklyn/1a"])
    assert (f.n_backoffs, f._pace_now) == (1, 2.0)
    f.extract(["https://streeteasy.com/building/x-brooklyn/1a"])
    assert (f.n_backoffs, f._pace_now) == (2, 4.0)
    state["fail"] = False
    f.extract(["https://streeteasy.com/building/x-brooklyn/1a"])
    assert f._pace_now == pytest.approx(3.6)          # decays, never below pace_s
    for _ in range(40):
        f._recovered()
    assert f._pace_now == 1.0


def test_backoff_is_capped():
    f = _fetcher({}, pace_s=1.0, max_pace_s=4.0)
    for _ in range(10):
        f._throttled()
    assert f._pace_now == 4.0


# --------------------------------------------------------------------------
# Parquet sink. DuckDB is single-writer; a multi-hour sweep must not hold the
# file lock. These tests pin that the fetch writes NOTHING to the database and
# that the later merge is idempotent and does not double-count.
# --------------------------------------------------------------------------
def _sink_fetcher(budget, n_addresses_pages=1):
    class _F(L.TavilyFetcher):
        def __init__(self):
            self.budget = budget
            self.failed_urls = []
            self.n_backoffs = 0
            self._pace_now = 0.0
            self.seen = 0

        def search_building(self, address, borough):
            self.budget.reserve("search")
            self.budget.record(endpoint="search", n_urls=1, credits=1, note=address,
                               http_status=200, n_ok=1, n_failed=0)
            slug = L.slugs_for(address, borough)[0]
            return [{"url": f"https://streeteasy.com/building/{slug}/1a", "score": 0.9}]

        def extract(self, urls):
            self.budget.reserve("extract", len(urls))
            self.budget.record(endpoint="extract", n_urls=len(urls), credits=2,
                               http_status=200, n_ok=len(urls), n_failed=0)
            return {u: ("## Building amenities\n\nServices and facilities\n\n"
                        "*   Laundry in building\n\n"
                        "## About the building\n\n"
                        "###### 51 Schermerhorn Street\n\n"
                        "51 Schermerhorn Street, Brooklyn, NY 11201\n") for u in urls}
    return _F()


def _targets(n):
    return [{"bbl": f"300001{i:04d}", "address": f"{i} MAIN STREET", "borough": "BK",
             "lon": -73.99, "lat": 40.69, "units": 12.0} for i in range(1, n + 1)]


def test_sink_writes_parquet_and_progress_and_never_touches_the_database(tmp_path):
    from loci import db as locidb

    mem = locidb.connect(":memory:")          # spatial only -- no project DB, no lock
    budget = L.TavilyBudget(max_calls=100)
    sink = tmp_path / "run"
    rep = L.build_listings(mem, _targets(7), fetcher=_sink_fetcher(budget),
                           sink_dir=sink, part_every=3, log=None)

    assert rep["rows_written"] == 7
    assert rep["sink_dir"] == str(sink)
    parts = sorted(p.name for p in sink.glob("listings-*.parquet"))
    assert parts == [f"listings-{rep['run_id']}-{i:05d}.parquet" for i in (1, 2, 3)]
    prog = json.loads((sink / "progress.json").read_text())
    assert prog["finished"] is True and prog["addresses"] == 7
    assert prog["run_id"] == rep["run_id"] and prog["credits"] == rep["credits"] == 21.0
    assert L.fetched_bbls(sink) == {t["bbl"] for t in _targets(7)}
    # resume key half 2: every SEARCHED address, including ones with no result
    assert L.searched_addresses(sink) == {L._addr_key(t["address"]) for t in _targets(7)}

    # ---- merge, and only now does anything reach a database ---------------
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    assert con.execute("SELECT count(*) FROM staging.listings").fetchone()[0] == 0
    out = L.merge_sink(con, sink)
    assert out["rows_in_sink"] == 7 and out["rows_replaced"] == 0
    assert out["staging_rows"] == 7 and out["bbl_rows"] == 7
    assert out["log_rows"] == 14          # 7 searches + 7 extracts, every call logged

    # totals reconcile: rollup sums == staging counts, no double count, no drop
    row = con.execute("""
        SELECT (SELECT count(*) FROM staging.listings),
               (SELECT sum(n_listings) FROM analysis.address_laundry_evidence WHERE source = 'listing'),
               (SELECT count(*) FROM staging.listings WHERE laundry_in_building),
               (SELECT sum(n_in_building) FROM analysis.address_laundry_evidence WHERE source = 'listing'),
               (SELECT count(*) FROM staging.listings WHERE laundry_in_unit = FALSE),
               (SELECT count(*) FROM staging.listings WHERE laundry_in_building = FALSE)
    """).fetchone()
    assert row[0] == row[1] == 7
    assert row[2] == row[3] == 7
    assert row[4] == row[5] == 0              # CAVEAT ZERO: no FALSE ever written


def test_merge_is_idempotent_and_deduplicates_overlapping_parts(tmp_path):
    """A resumed run legitimately re-fetches an address. Merging twice, or
    merging overlapping parts, must not insert the same page twice -- that
    would inflate n_listings and manufacture evidence."""
    from loci import db as locidb

    mem = locidb.connect(":memory:")
    sink = tmp_path / "run"
    L.build_listings(mem, _targets(3), fetcher=_sink_fetcher(L.TavilyBudget(max_calls=99)),
                     sink_dir=sink, part_every=99, log=None)
    L.build_listings(mem, _targets(3)[:2], fetcher=_sink_fetcher(L.TavilyBudget(max_calls=99)),
                     sink_dir=sink, part_every=99, log=None)   # overlapping second pass
    assert len(list(sink.glob("listings-*.parquet"))) == 2

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    first = L.merge_sink(con, sink)
    assert first["rows_in_sink"] == 3          # 5 part rows collapse to 3 URLs
    assert con.execute("SELECT count(*) FROM staging.listings").fetchone()[0] == 3
    second = L.merge_sink(con, sink)
    assert second["rows_replaced"] == 3
    assert con.execute("SELECT count(*) FROM staging.listings").fetchone()[0] == 3
    assert con.execute(
        "SELECT max(n_listings) FROM analysis.address_laundry_evidence "
        "WHERE source = 'listing'").fetchone()[0] == 1


def test_merge_refuses_an_empty_sink(tmp_path):
    from loci import db as locidb

    (tmp_path / "empty").mkdir()
    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    with pytest.raises(L.SourceUnavailable):
        L.merge_sink(con, tmp_path / "empty")


def test_parquet_schema_matches_the_staging_ddl_column_order(tmp_path):
    """A column added to staging.listings without adding it to LISTING_COLS
    would shift every value one position left at merge time."""
    from loci import db as locidb

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    ddl = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='staging' AND table_name='listings' "
        "ORDER BY ordinal_position").fetchall()]
    assert tuple(ddl) == L.LISTING_COLS
    log_ddl = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='staging' AND table_name='listings_fetch_log' "
        "ORDER BY ordinal_position").fetchall()]
    assert tuple(log_ddl) == L.LOG_COLS


# --------------------------------------------------------------------------
# Named-building slugs. Measured 2026-09-09 launching the MN+BK sweep: 1515
# Surf Avenue (324 units) lives at /building/1515-surf/1325, and the strict
# slug gate rejected all eight of its unit pages -- a fabricated zero in
# exactly the large buildings the sweep prioritises.
# --------------------------------------------------------------------------
SURF_HITS = [
    {"url": "https://streeteasy.com/building/1515-surf/1325", "score": 0.89},
    {"url": "https://streeteasy.com/building/1515-surf/721", "score": 0.89},
    {"url": "https://streeteasy.com/building/1515-surf", "score": 0.88},
    {"url": "https://streeteasy.com/building/2929-west-15-street-brooklyn/4a", "score": 0.60},
]


def test_named_building_slug_is_invisible_to_the_strict_gate():
    assert L.unit_urls_for(L.slugs_for("1515 SURF AVENUE", "BK"), SURF_HITS) == []


def test_fallback_reaches_named_buildings_but_only_high_score_unit_pages():
    got = L.fallback_unit_urls(SURF_HITS)
    assert got == ["https://streeteasy.com/building/1515-surf/1325",
                   "https://streeteasy.com/building/1515-surf/721"]
    assert L.fallback_unit_urls(SURF_HITS, cap=1) == got[:1]


@pytest.mark.parametrize("page_addr,address,ok", [
    ("1515 Surf Avenue, Brooklyn, NY 11224", "1515 SURF AVENUE", True),
    ("2882 West 15th Street, Brooklyn, NY 11224", "2882 WEST 15 STREET", True),
    ("78 Division Avenue, Brooklyn, NY 11249", "78 MARCY AVENUE", False),
    ("782 Marcy Avenue, Brooklyn, NY 11216", "78 MARCY AVENUE", False),
    ("100 West 57th Street, New York, NY 10019", "100 WEST 57 STREET", True),
])
def test_page_address_verification(page_addr, address, ok):
    p = L.ParsedListing(listing_url="u", address_raw=page_addr)
    assert L.page_matches(p, address, None) is ok


def test_a_page_that_states_no_address_falls_back_to_the_point_check():
    p = L.ParsedListing(listing_url="u")
    assert L.page_matches(p, "1515 SURF AVENUE", 40.0) is True
    assert L.page_matches(p, "1515 SURF AVENUE", 400.0) is False
    assert L.page_matches(p, "1515 SURF AVENUE", None) is False


def test_fallback_rows_that_fail_verification_are_dropped_not_written(tmp_path):
    """The gate exists because '78 Marcy Avenue' really returns
    78-division-avenue-brooklyn. The fallback fetches it; verification must
    stop it reaching a BBL."""
    from loci import db as locidb

    class _F(L.TavilyFetcher):
        def __init__(self):
            self.budget = L.TavilyBudget(max_calls=20)
            self.failed_urls, self.n_backoffs, self._pace_now = [], 0, 0.0

        def search_building(self, address, borough):
            self.budget.reserve("search")
            self.budget.record(endpoint="search", n_urls=1, credits=1, note=address,
                               http_status=200, n_ok=2, n_failed=0)
            return [{"url": "https://streeteasy.com/building/marcy-tower/3a", "score": 0.9},
                    {"url": "https://streeteasy.com/building/division-house/1b", "score": 0.9}]

        def extract(self, urls):
            self.budget.reserve("extract", len(urls))
            self.budget.record(endpoint="extract", n_urls=len(urls), credits=2,
                               http_status=200, n_ok=len(urls), n_failed=0)
            block = ("## Building amenities\n\nServices and facilities\n\n"
                     "*   Laundry in building\n\n## About the building\n\n")
            return {
                "https://streeteasy.com/building/marcy-tower/3a":
                    block + "78 Marcy Avenue, Brooklyn, NY 11249\n",
                "https://streeteasy.com/building/division-house/1b":
                    block + "78 Division Avenue, Brooklyn, NY 11249\n",
            }

    mem = locidb.connect(":memory:")
    sink = tmp_path / "run"
    rep = L.build_listings(
        mem, [{"bbl": "3021850001", "address": "78 MARCY AVENUE", "borough": "BK",
               "lon": -73.957, "lat": 40.707, "units": 20.0}],
        fetcher=_F(), sink_dir=sink, log=None)

    assert rep["fallback_addresses"] == 1
    assert rep["parsed"] == 2                    # both pages were fetched and parsed
    assert rep["fallback_rejected"] == 1         # ...and the wrong street was dropped
    assert rep["rows_written"] == 1

    con = locidb.connect(":memory:")
    locidb.init_schema(con)
    L.merge_sink(con, sink)
    row = con.execute("SELECT listing_url, address_raw, match_method, match_confidence "
                      "FROM staging.listings").fetchall()
    assert len(row) == 1
    assert row[0][0] == "https://streeteasy.com/building/marcy-tower/3a"
    assert row[0][1] == "78 Marcy Avenue, Brooklyn, NY 11249"
    assert row[0][2] == "search_verified"        # provenance says it was not a slug match
    assert row[0][3] < 0.9                       # ...and is scored below a slug_exact row


def test_sustained_all_failure_trips_the_circuit_breaker_but_keeps_the_sink(tmp_path):
    """Tavily bills failed URLs. A run that renders nothing must stop, not
    spend the whole cap discovering it -- and must keep what it already got."""
    from loci import db as locidb

    class _F(L.TavilyFetcher):
        def __init__(self):
            self.budget = L.TavilyBudget(max_calls=999)
            self.failed_urls, self.n_backoffs, self._pace_now = [], 0, 0.0

        def search_building(self, address, borough):
            self.budget.reserve("search")
            self.budget.record(endpoint="search", n_urls=1, credits=1, note=address,
                               http_status=200, n_ok=1, n_failed=0)
            slug = L.slugs_for(address, borough)[0]
            return [{"url": f"https://streeteasy.com/building/{slug}/{i}a", "score": 0.9}
                    for i in range(4)]

        def extract(self, urls):
            self.budget.reserve("extract", len(urls))
            self.budget.record(endpoint="extract", n_urls=len(urls), credits=2,
                               http_status=200, n_ok=0, n_failed=len(urls))
            self.failed_urls.extend(urls)
            return {}

    mem = locidb.connect(":memory:")
    sink = tmp_path / "run"
    with pytest.raises(L.SourceUnavailable, match="renders nothing"):
        L.build_listings(mem, _targets(500), fetcher=_F(), sink_dir=sink,
                         throttle_after=60, log=None)
    prog = json.loads((sink / "progress.json").read_text())
    assert prog["aborted"] == "throttled"
    assert prog["addresses"] < 30            # stopped early, not at 500
    assert prog["calls"] < 70
