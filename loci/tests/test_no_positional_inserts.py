"""Lint: no positional ``INSERT`` anywhere under ``src/loci``.

WHY THIS TEST EXISTS
--------------------
DuckDB binds ``INSERT INTO t SELECT ...`` and ``INSERT INTO t VALUES (...)``
**by ordinal position**, never by name.  A table's column order is therefore a
load-bearing part of every such write, and it is exactly the thing this
codebase cannot hold still:

* ``db.init_schema`` replays every ``src/loci/sql/*.sql`` on the next WRITE
  connection, so a migration goes live on whichever session writes first.
* Migrations widen tables with ``ALTER TABLE ... ADD COLUMN`` (sql/039 does it
  three times to ``chains.brand_snapshot``).  A table built by a fresh CREATE
  and the same table built by CREATE-then-ALTER can end up with the SAME
  columns in a DIFFERENT order.
* Nothing in DuckDB rejects the resulting write.  It silently lands values in
  the wrong columns wherever the types happen to be compatible -- and Loci's
  wide staging tables are mostly VARCHAR, so they nearly always are.

Naming the columns on BOTH sides of the INSERT is the only thing that makes
these writes order-independent.  This lint keeps them that way.

WHAT IT FLAGS
-------------
Any ``INSERT [OR REPLACE] INTO <name>`` followed by ``SELECT`` / ``VALUES`` /
``WITH`` with **no intervening parenthesised column list**.  ``INSERT INTO t BY
NAME SELECT ...`` is accepted: DuckDB's ``BY NAME`` binds by column name and is
order-independent by construction.

HOW IT LOOKS
------------
Two passes, unioned:

1. ``ast`` -- string constants and f-strings, which is where SQL legitimately
   lives.  Catches statements the raw-text pass would mis-locate.
2. A tolerant regex over the RAW file text.  SQL in this tree is routinely
   split across implicit string concatenation and f-string fragments::

       con.execute("INSERT INTO analysis.hex_poi_distance "
                   "(h3_index, poi_id, category, network_m) "
                   "SELECT ...")

   so the scanner steps over quote characters, ``f``/``r`` prefixes, ``+``
   concatenation, line continuations and comments when deciding what token
   follows the table name.  The raw pass is what makes a column list written in
   a *different string literal* from the table name count as present.

THE ALLOWLIST IS KEYED ON SHAPE, NOT ON LINE NUMBER
---------------------------------------------------
The five remaining sites are in ``src/loci/sources/``, which wave two owns and
this tree may not edit.  Line numbers there drift daily, so the allowlist is
keyed on ``(relative path, target table, verb, SELECT-vs-VALUES, detail)``.

Two assertions, deliberately:

* every hit must be allowlisted -- a NEW positional insert turns this red;
* every allowlist entry must still match a real hit -- FIXING a site without
  deleting its entry also turns this red, so the list cannot rot into a lie
  that quietly re-permits the bug it was written for.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
from dataclasses import dataclass

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "loci"
ROOT = SRC.parents[1]

# --------------------------------------------------------------------------
# the allowlist
# --------------------------------------------------------------------------
# Two tuples, kept apart on purpose.  BLOCKED_SOURCES is EXACTLY the five sites
# this tree is forbidden to touch, each cleared by a written Phase B patch.
# UNOWNED_BY_PHASE_A is what the lint FOUND outside its remit -- an allowlist
# that mixed the two would let "not mine to fix" quietly become "fine".  Every
# reason names who owns the file and what clears it.  Deleting a fixed entry is
# part of landing the fix; see test_allowlist_has_no_dead_entries.

_PHASE_B = ("Phase B of the warehouse reshape: patch prepared, applies once "
            "wave two's edits to this file have landed")

@dataclass(frozen=True)
class Site:
    """An allowlisted positional insert, identified by SHAPE not by line."""
    path: str        # repo-relative, POSIX separators
    table: str       # target table exactly as the statement spells it
    verb: str        # 'INSERT INTO' | 'INSERT OR REPLACE INTO'
    kind: str        # 'SELECT' | 'VALUES'
    detail: str      # 'star' | 'cols' | '<n>?' -- DESCRIPTIVE, not part of key
    reason: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        # `detail` is deliberately OUT of the key: the ast pass sees only the
        # string fragment `"... VALUES ("` and counts 0 placeholders where the
        # raw pass sees `["?"] * 20`.  (path, table, verb, SELECT-vs-VALUES)
        # already separates all five allowlisted sites, and is the coarsest
        # key that does -- which is what keeps it stable under reformatting.
        return (self.path, self.table, self.verb, self.kind)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    table: str
    verb: str
    kind: str
    detail: str
    text: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.path, self.table, self.verb, self.kind)


#: The five sites this tree is BLOCKED from touching (wave two owns
#: src/loci/sources/ and Phase A is code+tests only).  Each is cleared by an
#: already-written Phase B patch.
# UNOWNED_BY_PHASE_A was what the lint FOUND outside its remit -- an allowlist
# that mixed the two would let "not mine to fix" quietly become "fine".  Every
# reason names who owns the file and what clears it.  Deleting a fixed entry is
# part of landing the fix; see test_allowlist_has_no_dead_entries.

_PHASE_B = ("Phase B of the warehouse reshape: patch prepared, applies once "
            "wave two's edits to this file have landed")

@dataclass(frozen=True)
class Site:
    """An allowlisted positional insert, identified by SHAPE not by line."""
    path: str        # repo-relative, POSIX separators
    table: str       # target table exactly as the statement spells it
    verb: str        # 'INSERT INTO' | 'INSERT OR REPLACE INTO'
    kind: str        # 'SELECT' | 'VALUES'
    detail: str      # 'star' | 'cols' | '<n>?' -- DESCRIPTIVE, not part of key
    reason: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        # `detail` is deliberately OUT of the key: the ast pass sees only the
        # string fragment `"... VALUES ("` and counts 0 placeholders where the
        # raw pass sees `["?"] * 20`.  (path, table, verb, SELECT-vs-VALUES)
        # already separates all five allowlisted sites, and is the coarsest
        # key that does -- which is what keeps it stable under reformatting.
        return (self.path, self.table, self.verb, self.kind)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    table: str
    verb: str
    kind: str
    detail: str
    text: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.path, self.table, self.verb, self.kind)


#: The five sites this tree is BLOCKED from touching (wave two owns
#: src/loci/sources/ and Phase A is code+tests only).  Each is cleared by an
#: already-written Phase B patch.
BLOCKED_SOURCES: tuple[Site, ...] = (
    # EMPTY as of Phase B, 2026-09-16. All five sites are fixed:
    #   listings.py  staging.listings_fetch_log  INSERT ... SELECT *   -> LOG_COLS
    #   listings.py  staging.listings            20 bare placeholders  -> LISTING_COLS
    #   listings.py  staging.listings_fetch_log  10 bare placeholders  -> LOG_COLS,
    #                and the values are now pulled BY KEY rather than by dict order
    #   nys_sla.py   staging.alcohol_licences    INSERT ... SELECT     -> 12 columns
    #   ll84_laundry.py staging.ll84_laundry     INSERT ... SELECT     ->  9 columns
    #
    # They were allowlisted in Phase A only because src/loci/sources/ was wave
    # two's tree; wave two committed as b0665c0 and they were applied in the
    # same edit that emptied this tuple, which is the rule the second assertion
    # enforces.
)

#: What the lint found OUTSIDE its remit, kept apart from BLOCKED_SOURCES so
#: that "not mine to fix" could not quietly become "fine". Every reason must
#: name who owns the file and what clears it.
#:
#: EMPTY. It held two src/loci/model/forecast.py sites in Phase A; the agent
#: that owned that file fixed them as part of the forecast reshape,
#: `test_allowlist_has_no_dead_entries` went red, and the entries were deleted.
#: That round trip is the point of the second assertion -- an allowlist entry
#: cannot outlive the exception it records.
UNOWNED_BY_PHASE_A: tuple[Site, ...] = ()

ALLOWLIST = BLOCKED_SOURCES + UNOWNED_BY_PHASE_A


# --------------------------------------------------------------------------
# the scanner
# --------------------------------------------------------------------------

_INSERT_RE = re.compile(r"\bINSERT\s+(?:OR\s+REPLACE\s+)?INTO\b", re.IGNORECASE)
_NAME_RE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_$]*|\{[^}]*\})"
                      r"(?:\s*\.\s*(?:[A-Za-z_][A-Za-z0-9_$]*|\{[^}]*\}))?")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PREFIX_QUOTE_RE = re.compile(r"(?:[rRfFbBuU]{1,2})?(?:\"\"\"|'''|\"|')")
#: the `",".join(["?"] * 20)` idiom: a placeholder list whose WIDTH is the only
#: thing recording the target's column count.
_JOIN_HOLES_RE = re.compile(r"""\[\s*["']\?["']\s*\]\s*\*\s*(\d+)""")

#: Characters and tokens that can sit BETWEEN two halves of one SQL statement
#: in Python source without being part of the SQL.
def _skip_noise(text: str, i: int) -> int:
    """Advance past whitespace, string delimiters, concatenation and comments.

    This is what lets a column list living in a different string literal from
    its table name still count as present.
    """
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace() or c in "+\\,":
            # a comma only ever appears here as the `execute(sql, params)`
            # separator or between concatenated fragments; SQL that matters
            # to this lint never starts with one.
            i += 1
            continue
        if c == "#":                       # Python comment
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if text.startswith("--", i):       # SQL comment
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        m = _PREFIX_QUOTE_RE.match(text, i)
        if m and m.end() > i:
            # only treat this as a delimiter if it really is a quote (the
            # prefix letters alone must not eat a SQL keyword)
            i = m.end()
            continue
        return i
    return n


def _detail_for_values(text: str, i: int) -> str:
    """How many placeholders, so two VALUES sites on one table stay distinct."""
    window = text[i:i + 240]
    stop = window.find(";")
    if stop > 0:
        window = window[:stop]
    mult = _JOIN_HOLES_RE.search(window)    # ",".join(["?"] * 20)
    if mult:
        return f"{mult.group(1)}?"
    return f"{window.count('?')}?"


def _is_scratch(table: str) -> bool:
    """Un-qualified ``_name`` targets are scratch tables -- out of scope.

    The hazard this lint exists for is MIGRATION-driven: a persisted warehouse
    table (``staging.``/``analysis.``/``chains.``/``raw.``) whose column order
    differs between a fresh CREATE and a CREATE-then-ALTER.  A target with no
    schema qualifier and a leading underscore is a scratch table created a few
    lines above the write -- e.g. ``_acs_geoid`` in model/address_demographics,
    a one-column in-memory table CREATEd and INSERTed in the same function.  No
    migration can reach it, so its ordinals cannot drift.

    NARROW ON PURPOSE: a schema-qualified target is NEVER exempt, whatever it
    is called, because a schema qualifier is what makes it reachable by
    src/loci/sql/.
    """
    return "." not in table and table.startswith("_")


def _blank_comments(text: str) -> str:
    """Overwrite Python ``#`` comments with spaces, PRESERVING every offset.

    Necessary, not cosmetic.  The comments in this tree quote the very bug
    this lint hunts -- ``dcp_housing.py`` explains at length that its write
    "used to be a bare ``INSERT INTO analysis.dev_pipeline SELECT ...``" --
    and a raw-text scanner that read prose would report the fix as the defect.

    SQL ``--`` comments are NOT blanked: they can sit between a table name and
    its SELECT (``analysis.forecast`` does exactly that), and stepping over
    them is how the scanner sees the statement underneath.
    """
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return text
    offs, acc = [0], 0
    for line in text.splitlines(keepends=True):
        acc += len(line)
        offs.append(acc)
    out = list(text)
    for tok in toks:
        if tok.type != tokenize.COMMENT:
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        for i in range(offs[r1 - 1] + c1, min(offs[r2 - 1] + c2, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _richer(a: str, b: str) -> str:
    """Keep the more informative of two `detail`s for the failure message."""
    def rank(d: str) -> int:
        return int(d[:-1]) if d.endswith("?") and d[:-1].isdigit() else 10 ** 6
    return a if rank(a) >= rank(b) else b


def scan(text: str, path: str, line_of=None) -> list[Hit]:
    """Return every positional INSERT in ``text``."""
    hits: list[Hit] = []
    for m in _INSERT_RE.finditer(text):
        verb = "INSERT OR REPLACE INTO" if re.search(
            r"OR\s+REPLACE", m.group(0), re.IGNORECASE) else "INSERT INTO"
        i = _skip_noise(text, m.end())
        nm = _NAME_RE.match(text, i)
        if not nm:
            continue
        table = re.sub(r"\s+", "", nm.group(0))
        if _is_scratch(table):
            continue
        i = _skip_noise(text, nm.end())
        if i >= len(text):
            continue
        if text[i] == "(":
            j = _skip_noise(text, i + 1)
            w = _WORD_RE.match(text, j)
            if not (w and w.group(0).upper() in {"SELECT", "VALUES", "WITH"}):
                continue                    # a real column list -> safe
            # `INSERT INTO t (SELECT ...)` -- parenthesised source, not a
            # column list.  Fall through and flag it.
            i = j
        w = _WORD_RE.match(text, i)
        if not w:
            continue
        kw = w.group(0).upper()
        if kw == "BY":                      # DuckDB `INSERT INTO t BY NAME ...`
            k = _skip_noise(text, w.end())
            w2 = _WORD_RE.match(text, k)
            if w2 and w2.group(0).upper() in {"NAME", "POSITION"}:
                # BY NAME binds by column name -> order-independent -> safe.
                # BY POSITION is an EXPLICIT, reviewed choice -> also accepted.
                continue
        if kw not in {"SELECT", "VALUES", "WITH"}:
            continue
        kind = "VALUES" if kw == "VALUES" else "SELECT"
        if kind == "VALUES":
            detail = _detail_for_values(text, _skip_noise(text, w.end()))
        else:
            j = _skip_noise(text, w.end())
            detail = "star" if j < len(text) and text[j] == "*" else "cols"
        line = line_of(m.start()) if line_of else text.count("\n", 0, m.start()) + 1
        snippet = re.sub(r"\s+", " ", text[m.start():m.start() + 160]).strip()
        hits.append(Hit(path, line, table, verb, kind, detail, snippet))
    return hits


def _ast_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """(lineno, text) for every string constant and f-string in the module."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append("{}")      # placeholder keeps tokens apart
            out.append((node.lineno, "".join(parts)))
    return out


def collect() -> list[Hit]:
    """Every positional INSERT under src/loci, deduped by (path, table, shape)."""
    by_key: dict[tuple, Hit] = {}
    for py in sorted(SRC.rglob("*.py")):
        rel = py.relative_to(ROOT).as_posix()
        raw = py.read_text(encoding="utf-8")
        text = _blank_comments(raw)

        # pass 1: raw text -- tolerant of SQL split across concatenation.
        line_starts = [0]
        for idx, ch in enumerate(text):
            if ch == "\n":
                line_starts.append(idx + 1)

        def line_of(off: int, _ls=line_starts) -> int:
            lo, hi = 0, len(_ls) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _ls[mid] <= off:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1

        found = scan(text, rel, line_of)

        # pass 2: ast -- string constants and f-strings only.
        try:
            tree = ast.parse(raw, filename=str(py))
        except SyntaxError:                  # not importable anyway; raw pass stands
            tree = None
        if tree is not None:
            for lineno, s in _ast_strings(tree):
                for h in scan(s, rel):
                    found.append(Hit(rel, lineno, h.table, h.verb,
                                     h.kind, h.detail, h.text))

        for h in found:
            prev = by_key.get(h.key)
            if prev is None:
                by_key[h.key] = h
            else:
                by_key[h.key] = Hit(
                    prev.path, min(prev.line, h.line), prev.table, prev.verb,
                    prev.kind, _richer(prev.detail, h.detail),
                    prev.text if prev.line <= h.line else h.text)
    return sorted(by_key.values(), key=lambda h: (h.path, h.line))


def _render(hits) -> str:
    return "\n".join(f"  {h.path}:{h.line}  [{h.table} | {h.verb} {h.kind}"
                     f" {h.detail}]\n      {h.text}" for h in hits)


# --------------------------------------------------------------------------
# the assertions
# --------------------------------------------------------------------------

def test_allowlist_is_the_five_blocked_source_sites_plus_declared_exceptions():
    """The five blocked sites are load-bearing; guard them against quiet growth.

    Anything added to the allowlist beyond them must land in
    UNOWNED_BY_PHASE_A, where the reason has to say who owns the file.
    """
    # EMPTY since Phase B: all five sites are fixed. It stays empty -- a new
    # entry here needs a reason naming who owns the file and what clears it.
    assert BLOCKED_SOURCES == (), (
        "BLOCKED_SOURCES is not empty; every src/loci/sources/ site was fixed "
        "in Phase B. A new entry needs an owner and a clearing condition.")
    assert len({s.key for s in ALLOWLIST}) == len(ALLOWLIST), "duplicate entry"


def test_no_unallowlisted_positional_inserts():
    """A NEW positional INSERT anywhere under src/loci turns this red."""
    allowed = {s.key for s in ALLOWLIST}
    hits = collect()
    extra = [h for h in hits if h.key not in allowed]
    assert not extra, (
        "Positional INSERT(s) not on the allowlist.\n\n"
        "DuckDB binds INSERT ... SELECT/VALUES by POSITION, so these writes "
        "break silently the first time their target table is ALTERed. Name the "
        "columns on BOTH sides:\n\n"
        "    INSERT INTO schema.table (a, b, c) SELECT a, b, c FROM ...\n\n"
        f"{len(extra)} offending statement(s):\n{_render(extra)}")


def test_allowlist_has_no_dead_entries():
    """FIXING a site without deleting its entry also turns this red.

    Without this the allowlist rots into a lie: it would keep permitting a
    (path, table, shape) long after the bug there was fixed, and silently
    re-permit the SAME bug if it were ever reintroduced.
    """
    live = {h.key: h for h in collect()}
    dead = [s for s in ALLOWLIST if s.key not in live]
    assert not dead, (
        f"{len(dead)} allowlist entry/entries no longer match any positional "
        "INSERT. If the site was fixed, DELETE its entry -- an allowlist that "
        "outlives its exception stops being a record and starts being a "
        "loophole.\n"
        + "\n".join(f"  {s.path}  [{s.table} | {s.verb} {s.kind} {s.detail}]\n"
                    f"      was: {s.reason}" for s in dead))


def test_scanner_recognises_the_shapes_it_must():
    """The scanner itself, against hand-written positives and negatives.

    A lint that silently matches nothing is worse than no lint, so its
    discrimination is asserted rather than assumed.
    """
    bad = [
        ('con.execute("INSERT INTO chains.brand_location SELECT * FROM _t")',
         "SELECT", "star"),
        ('con.execute("INSERT OR REPLACE INTO s.t VALUES (?, ?, ?)")',
         "VALUES", "3?"),
        ('con.execute("INSERT INTO s.t SELECT a, b FROM _t")', "SELECT", "cols"),
        # the width-only-in-Python idiom: nothing in the SQL records the
        # column count at all, so the tuple's order IS the schema
        ('con.executemany("INSERT INTO s.t VALUES (" + ",".join(["?"] * 20) + ")", rows)',
         "VALUES", "20?"),
    ]
    for src, kind, detail in bad:
        got = scan(src, "x.py")
        assert len(got) == 1, f"missed: {src}"
        assert (got[0].kind, got[0].detail) == (kind, detail), src

    good = [
        'con.execute("INSERT INTO s.t (a, b) SELECT a, b FROM _t")',
        # the split-literal case the raw pass exists for
        'con.execute("INSERT INTO s.t "\n            "(a, b) "\n            "SELECT a, b FROM _t")',
        # the f-string case
        'con.execute(f"INSERT INTO s.t ({cols}) SELECT {cols} FROM _t")',
        # BY NAME binds by column name, not ordinal
        'con.execute("INSERT INTO s.t BY NAME SELECT * FROM _t")',
        # an un-qualified scratch table no migration can reach
        'mem.executemany("INSERT INTO _acs_geoid VALUES (?)", rows)',
    ]
    # ...but a SCHEMA-QUALIFIED target is never exempt, whatever it is named
    assert len(scan('con.execute("INSERT INTO staging._tmp SELECT * FROM x")',
                    "x.py")) == 1
    for src in good:
        assert scan(src, "x.py") == [], f"false positive: {src}"


def test_the_four_repaired_writes_stay_named():
    """Regression guard on the four sites Phase A repaired.

    These are the writes that were positional against tables the migrations
    reach: chains.brand_location (twice), analysis.hex_poi_distance,
    analysis.hex_access and analysis.poi_dedup.  Naming a table here asserts
    that NOTHING in that file is positional any more -- stronger than checking
    the five files are merely absent from the hit list.
    """
    repaired = {
        "src/loci/chains/detect.py",
        "src/loci/model/poi_key_migration.py",
        "src/loci/score/access.py",
        "src/loci/score/dedup.py",
    }
    regressed = [h for h in collect() if h.path in repaired]
    assert not regressed, (
        "A repaired file went positional again:\n" + _render(regressed))
