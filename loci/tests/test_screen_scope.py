"""EVERY SCREEN QUERY CARRIES ITS BOROUGH PREDICATE (audit finding 4/5).

The screen is Manhattan + Brooklyn. `analysis.address`, `address_category`,
`forecast` and `dev_pipeline` hold MN+BK and nothing else, so a query against
them cannot leak. SEVEN OBJECTS DO NOT, and nothing in the schema says so:

    object                      MN       BK       QN       BX      SI     NULL
    analysis.storefront      155,450   98,069   89,251   55,286  16,828     --
    analysis.storefront_pipeline 40,318 32,775  27,597   11,945   5,745  17,532
    staging.storefront_filing 339,893 238,181  225,510   85,147  47,031  53,412
    analysis.licence_interval 10,357   13,632   13,555    6,392   3,078  25,437
    chains.brand_location     22,826   13,379   12,662    5,080   2,549  22,434
    analysis.poi_presence     57,725   40,752   34,550   16,176   6,058  63,872
    staging.alcohol_licences  -- statewide: reaches lon -78.87 / lat 43.21, Buffalo

`analysis.storefront` alone is 39% out of scope. Most readers are saved
INCIDENTALLY, by a distance filter applied after the fetch; the one that was
not — `validation/retrodiction.py:486` — put five boroughs of vacancy counts
into an MN+BK narrative for as long as it stood, and no error was ever raised.

This is the machine-check the audit asked for, over `src/loci/validation/` and
`src/loci/report/` — the two packages whose output is a NUMBER A HUMAN READS.
It reads the CURRENT tree, so a query added tomorrow with no predicate fails
here rather than in a memo.

THE RULE. A SQL string literal that names one of these objects after FROM or
JOIN must also carry, IN THE SAME LITERAL, either
  * a borough predicate (the word `borough`, in any rendering — the vocabulary
    is split, 'MN'/'BK' on the address family and 'Manhattan'/'Brooklyn' on
    `poi_presence` and `brand_location`, with no FK between them), or
  * a bounding spatial predicate (ST_DWithin / ST_Within / ST_Intersects, or an
    explicit lon/lat BETWEEN box).
A literal that fails is retried against every string literal in its ENCLOSING
FUNCTION (docstrings excluded), because these queries are routinely ASSEMBLED:
`retrodiction._premises_year_cte` builds one CTE from three pieces and the
`WHERE` can only live in the piece after the JOIN, and `report/evidence.py`
interpolates a `WHERE ... AND {_borough_sql(...)} AND {_bbox_sql(...)}`
fragment that carries no SQL verb at all. Anything still failing must be named
in `ALLOWED` with a one-line reason.

WHAT THIS CANNOT CHECK, and the database cannot either: that the predicate is
the RIGHT one. `poi_presence` and `brand_location` spell the borough
'Manhattan'; everything else spells it 'MN'; there is no FK and no constraint,
so the wrong vocabulary returns zero rows silently and passes here.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

import loci

PKG = pathlib.Path(loci.__file__).resolve().parent
SCANNED = ("validation", "report")

#: The objects that carry all five boroughs (or, for `alcohol_licences`, all of
#: New York State) while the screen is MN+BK.
FIVE_BOROUGH_TABLES = (
    "analysis.storefront",
    "analysis.storefront_year",
    "analysis.storefront_pipeline",
    "analysis.licence_interval",
    "analysis.poi_presence",
    "chains.brand_location",
    "staging.storefront_filing",
    "staging.alcohol_licences",
)

#: Sites that genuinely cannot carry a predicate, each with its reason, keyed
#: `(path relative to src/loci, table)`. An entry is a PROMISE that the rows
#: are bounded some other way, not a mute button — `test_every_allowed_entry_
#: still_points_at_a_real_site` fails on any entry that has gone stale.
#:
#: EMPTY as of 2026-09-16, and that is the point: the four `report/evidence.py`
#: readers that used to fetch a whole five-borough table and bound it by
#: `haversine_m` in PYTHON (`_vacant_storefront_rows`, `_pipeline_rows`,
#: `_chains_watch_rows`, `_sla_500ft_context`) now carry `_borough_sql` +
#: `_bbox_sql` in the SQL itself. They were correct before — the RESULT was
#: scoped — and they were still a 414,884-row scan per one-address report
#: (audit finding 13). Nothing in this tree is now exempt.
ALLOWED: dict[tuple[str, str], str] = {}

_SQL_VERB = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.I)
_BOROUGH = re.compile(r"\bborough\b", re.I)
_SPATIAL = re.compile(
    r"ST_DWithin|ST_Within|ST_Intersects|ST_Contains"
    r"|\blat\s+BETWEEN\b|\blon\s+BETWEEN\b|\blatitude\s+BETWEEN\b",
    re.I)


def _render(node: ast.AST) -> str | None:
    """The text of a string literal, with f-string holes rendered as the
    expression that fills them — so `borough IN ({BORO_CODE_SQL})` still reads
    as a borough predicate."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                try:
                    out.append(ast.unparse(part.value))
                except Exception:                       # noqa: BLE001
                    out.append(" ")
        return "".join(out)
    return None


def _table_re(table: str) -> re.Pattern:
    """`FROM|JOIN <table>` — anchored on the clause so a docstring that merely
    NAMES the table is not mistaken for a query against it. `\\b` after the
    name keeps `analysis.storefront` from matching `analysis.storefront_year`
    (`_` is a word character)."""
    return re.compile(rf"\b(?:FROM|JOIN)\s+{re.escape(table)}\b", re.I)


TABLE_RES = {t: _table_re(t) for t in FIVE_BOROUGH_TABLES}


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Every docstring node. Prose that NAMES a borough must never excuse a
    query that does not filter on one."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    body[0].value, ast.Constant) and isinstance(
                    body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _sql_literals(tree: ast.AST, skip: set[int]) -> list[tuple[ast.AST, str]]:
    """String literals that look like a STATEMENT — the sites to check."""
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            text = _render(node)
            if text and _SQL_VERB.search(text):
                out.append((node, text))
    return out


def _any_literals(tree: ast.AST, skip: set[int]) -> list[str]:
    """EVERY string literal — the stage-two union. A predicate is routinely a
    FRAGMENT with no verb in it at all (`report/evidence.py` builds
    `WHERE ... AND {_borough_sql('borough')} AND {_bbox_sql(...)}` and
    interpolates it), so stage two cannot require one. Docstrings are excluded:
    a function that only TALKS about boroughs has not filtered on any."""
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            text = _render(node)
            if text:
                out.append(text)
    return out


def _scoped(text: str) -> bool:
    return bool(_BOROUGH.search(text) or _SPATIAL.search(text))


def _scan(path: pathlib.Path) -> list[tuple[str, int, str]]:
    """(table, lineno, snippet) for every unscoped site in one file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    skip = _docstring_ids(tree)

    # every function's own string literals, for stage two of the rule
    owner: dict[int, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            texts = _any_literals(node, skip)
            for inner in ast.walk(node):
                owner.setdefault(id(inner), texts)

    bad = []
    for node, text in _sql_literals(tree, skip):
        for table, rx in TABLE_RES.items():
            if not rx.search(text):
                continue
            if _scoped(text):
                continue
            if any(_scoped(t) for t in owner.get(id(node), ())):
                continue
            bad.append((table, getattr(node, "lineno", 0),
                        " ".join(text.split())[:120]))
    return bad


PY_FILES = sorted(
    p for d in SCANNED for p in (PKG / d).rglob("*.py")
    if "__pycache__" not in p.parts)


def test_the_scan_actually_finds_files():
    """A rename that empties `SCANNED` must fail loudly, not pass vacuously."""
    assert len(PY_FILES) >= 8
    assert any(p.name == "retrodiction.py" for p in PY_FILES)
    assert any(p.name == "evidence.py" for p in PY_FILES)


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: p.name)
def test_every_five_borough_query_carries_a_scope(path):
    rel = path.relative_to(PKG).as_posix()
    unexplained = [(t, ln, snip) for t, ln, snip in _scan(path)
                   if (rel, t) not in ALLOWED]
    assert not unexplained, "\n".join(
        f"{rel}:{ln} reads {t} with no borough or spatial predicate: {snip}"
        for t, ln, snip in unexplained)


def test_the_detector_would_catch_a_new_unscoped_query(tmp_path):
    """The check is only worth having if it fails on the thing it exists to
    catch. This is the exact shape of `retrodiction.py:486` before the fix."""
    f = tmp_path / "leak.py"
    f.write_text(
        "def counts(con):\n"
        "    return con.execute('''SELECT max(reporting_year), count(*)\n"
        "        FROM analysis.storefront''').fetchone()\n")
    found = _scan(f)
    assert [t for t, _, _ in found] == ["analysis.storefront"]

    f.write_text(
        "def counts(con):\n"
        "    return con.execute('''SELECT max(reporting_year), count(*)\n"
        "        FROM analysis.storefront\n"
        "        WHERE borough IN ('MN', 'BK')''').fetchone()\n")
    assert _scan(f) == []


def test_a_docstring_that_merely_names_a_table_is_not_a_query(tmp_path):
    f = tmp_path / "prose.py"
    f.write_text(
        "def f(con):\n"
        "    '''analysis.storefront is a premises x year panel; SELECT from it\n"
        "    only with a borough predicate.'''\n"
        "    return 1\n")
    assert _scan(f) == []


def test_every_allowed_entry_still_points_at_a_real_site():
    """An ALLOWED entry that no longer matches anything is a stale excuse, and
    a stale excuse is how the next unscoped query gets waved through."""
    live = {(p.relative_to(PKG).as_posix(), t)
            for p in PY_FILES for t, _, _ in _scan(p)}
    stale = sorted(set(ALLOWED) - live)
    assert not stale, f"ALLOWED entries with no matching site: {stale}"
