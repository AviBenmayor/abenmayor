"""Static check: the three modules that used to carry their OWN "is this POI
still open" logic must route it through the shared predicate
(`model.poi_presence.poi_is_open`, owner rule 2026-09-14, GTM-153):

  * `src/loci/validation/retrodiction.py` -- the cohort's still-open /
    closure logic (the refused survival gate and the closure-panel section).
  * `src/loci/model/recommendation_ledger.py` -- the rubric's `still_open`
    component and the outcome row's stored `still_open` value.
  * `src/loci/viz/webmap_export.py` -- the REALIZED layer's closure marks
    (`collect_realized`).

Prose explaining the HISTORY ("the ad hoc `closed_on IS NOT NULL` check this
module used before 2026-09-14...") is fine and expected -- these modules'
docstrings say exactly that on purpose, so a future reader knows why the
predicate is there. A live WHERE/AND clause built from the raw comparison, or
a bare `last_seen_month` equality standing in for "still open", is not: that
is precisely the duplicate definition the predicate exists to remove. The
export's own DISPLAY of the closure date itself (`closed_on` selected, or
passed to `strftime`) is exempt -- this test forbids TESTING the raw column
directly as a status predicate, not reading the date it carries.

model/poi_presence.py itself is exempt: it IS the predicate, and its owner
docstring already explains why `closed_on` is read directly there (D79's
"ledger:closed_on_..." branch).
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

MODULES = (
    REPO_ROOT / "src" / "loci" / "validation" / "retrodiction.py",
    REPO_ROOT / "src" / "loci" / "model" / "recommendation_ledger.py",
    REPO_ROOT / "src" / "loci" / "viz" / "webmap_export.py",
)

#: A raw closed_on null-test used as a LIVE SQL predicate (a WHERE/AND
#: clause), not prose describing one.
_RAW_SQL_CLOSED_ON = re.compile(
    r"(WHERE|AND)\s+\w*\.?closed_on\s+IS\s+(NOT\s+)?NULL", re.IGNORECASE)

#: The old recommendation_ledger.py bug: "still open" read as a bare
#: `last_seen_month` equality against the newest ledger month, rather than
#: through the predicate.
_RAW_LAST_SEEN_EQUALITY = re.compile(
    r'last_seen_month.{0,20}==\s*(ctx|newest)'
    r'|(ctx|newest).{0,20}==\s*.{0,10}last_seen_month', re.IGNORECASE)


def test_no_module_tests_closed_on_directly_as_a_live_predicate():
    for path in MODULES:
        text = path.read_text()
        hits = _RAW_SQL_CLOSED_ON.findall(text)
        assert not hits, (
            f"{path.relative_to(REPO_ROOT)} still tests closed_on IS [NOT] "
            f"NULL directly as a live SQL predicate -- route it through "
            f"model.poi_presence.poi_is_open instead: {hits}")


def test_no_module_reads_still_open_as_a_bare_last_seen_month_equality():
    for path in MODULES:
        text = path.read_text()
        assert not _RAW_LAST_SEEN_EQUALITY.search(text), (
            f"{path.relative_to(REPO_ROOT)} still compares last_seen_month "
            f"directly as a 'still open' test -- route it through "
            f"model.poi_presence.poi_is_open instead")


def test_all_three_modules_actually_call_the_shared_predicate():
    """The absence of the old patterns above is meaningless if the logic just
    moved somewhere unchecked -- each module must import/call `poi_is_open`."""
    for path in MODULES:
        text = path.read_text()
        assert "poi_is_open" in text, (
            f"{path.relative_to(REPO_ROOT)} does not reference "
            f"model.poi_presence.poi_is_open at all")
