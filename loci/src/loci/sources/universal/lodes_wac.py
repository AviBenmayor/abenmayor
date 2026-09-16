"""LEHD LODES8 Workplace Area Characteristics (WAC) -- the fetcher for the
whole annual series (registry.yaml `lodes_wac`).

WHAT THIS REPLACES
---------------------------------------------------------------------------
Nothing in this repo downloaded LODES. Three vintages sat in `data/raw/lodes/`
-- 2002, 2013, 2023 -- put there by hand, and `registry.yaml` recorded that as
the source's temporal coverage: "loaded vintages are 2002, 2013, 2023 only
(not annual series)". That was never a property of LODES. LODES8 publishes
EVERY year 2002-2023 for New York, free, at a couple of megabytes each. The
three-vintage series was our cap, and the owner's standing rule (2026-09-16)
is that free sources are pulled in full.

`model/panel.py` and `model/address_character.py` read these files straight
off disk with DuckDB's `read_csv`; this module only puts them there and
records what it put. It is a fetcher, not a loader, so it can run while the
warehouse is held open by another process.

THE CAVEAT THAT MUST TRAVEL WITH EVERY YEAR (CONTEXT.md 7.4b)
---------------------------------------------------------------------------
LODES8 reports EVERY vintage, 2002 through 2023, on **2020 census blocks**.
Only 2020 and later were observed on those blocks. Everything from 2002 to
2019 was collected on the 2000 or 2010 block geography and then
AREA-RETRO-ALLOCATED onto 2020 blocks by the LEHD.

That allocation is a **BIAS, not noise**. It is not a random error that
averages out across blocks or across years:

  * Where a 2010 block was split into several 2020 blocks, its jobs were
    divided by LAND AREA share. A block containing one office tower and one
    park has its employment smeared across both pieces in proportion to
    acreage, which is exactly the wrong proportion.
  * The direction of the error is a function of where the block boundaries
    moved, and block boundaries move where POPULATION moved -- so the error
    is correlated with growth, which is the very quantity a panel built on
    these files is usually trying to measure.
  * It does not shrink with more years. Every pre-2020 year carries it, and
    a 2002-2019 trend computed from these files is a trend in
    (jobs x allocation), not a trend in jobs.

Consequence for anything built on the series: a within-block change that
straddles 2019/2020 is partly a change in the allocation and not in
employment. `model/address_character.py` already uses 2023 and nothing older
for the present-day measure for this reason. Any use of the full series must
say which side of 2020 it sits on.

PROBE (2026-09-16, live)
---------------------------------------------------------------------------
* `https://lehd.ces.census.gov/data/lodes/LODES8/ny/wac/` lists
  `ny_wac_S000_JT00_<year>.csv.gz` for every year 2002..2023 inclusive --
  22 files, no gaps. HEAD on a sample (2002, 2010, 2019, 2020, 2023) returns
  200 with Content-Length 1.5-2.8 MB each; the whole series is ~55 MB
  compressed.
* The block crosswalk `ny_xwalk.csv.gz` is 5.2 MB and is NOT per-year: one
  file keys every vintage, which is the same fact as "LODES8 is 2020 blocks
  throughout" seen from the other side.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.request

SOURCE_ID = "lodes_wac"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
LODES_DIR = REPO_ROOT / "data" / "raw" / "lodes"
MANIFEST = LODES_DIR / "manifest.json"

BASE = "https://lehd.ces.census.gov/data/lodes/LODES8"

#: New York. The adapter is state-parameterised because LODES is national and
#: the project is not NYC-only by design (portability.py), but nothing outside
#: NY is fetched unless a caller asks.
DEFAULT_STATE = "ny"

#: WAC segment and job type. S000 = all workers, JT00 = all jobs. These are the
#: files `model/panel.py` and `model/address_character.py` already read; the
#: other segments (age, earnings, industry-of-worker) are a different question
#: and would be a different table, not a wider version of this one.
SEGMENT = "S000"
JOBTYPE = "JT00"

#: The full published annual series for NY, verified against the live
#: directory listing on 2026-09-16: 2002..2023, 22 files, no gaps.
#: UPSTREAM limits at both ends -- LODES begins in 2002 (2001 and earlier were
#: never published for NY) and 2023 is the latest reference year in LODES8.
FIRST_VINTAGE = 2002
LAST_VINTAGE = 2023
VINTAGES: tuple[int, ...] = tuple(range(FIRST_VINTAGE, LAST_VINTAGE + 1))

#: Every vintage in this list is on 2020 census blocks. The ones at or after
#: this year were OBSERVED there; the ones before were retro-allocated onto
#: them by land area. See the module docstring -- this is the bias line.
FIRST_OBSERVED_ON_2020_BLOCKS = 2020

MAX_RETRIES = 4
BACKOFF_S = 4.0
USER_AGENT = "loci/lodes (contact: repository owner)"


class LodesFetchError(RuntimeError):
    """A LODES file could not be fetched. Raised rather than skipped: a vintage
    silently missing from data/raw/lodes reads downstream as a year in which
    nobody worked in New York, and `model/panel.py` would happily build a panel
    with a hole in it."""


def wac_url(year: int, state: str = DEFAULT_STATE) -> str:
    return f"{BASE}/{state}/wac/{wac_filename(year, state)}"


def wac_filename(year: int, state: str = DEFAULT_STATE) -> str:
    """The name `model/panel.py` and `model/address_character.py` already
    expect on disk. Kept in one place so the fetcher and the readers cannot
    drift apart."""
    return f"{state}_wac_{SEGMENT}_{JOBTYPE}_{year}.csv.gz"


def xwalk_url(state: str = DEFAULT_STATE) -> str:
    return f"{BASE}/{state}/{xwalk_filename(state)}"


def xwalk_filename(state: str = DEFAULT_STATE) -> str:
    return f"{state}_xwalk.csv.gz"


def vintages(years=None) -> tuple[int, ...]:
    """The vintages to fetch. Default is EVERY published year, 2002-2023."""
    if years is None:
        return VINTAGES
    out = tuple(int(y) for y in years)
    unknown = [y for y in out if y not in VINTAGES]
    if unknown:
        raise LodesFetchError(
            f"LODES8 publishes {FIRST_VINTAGE}-{LAST_VINTAGE} for a state; "
            f"asked for {unknown} which is outside that (UPSTREAM limit).")
    return out


def block_vintage_note(year: int) -> str:
    """One line, per year, saying whether that year's blocks were observed or
    allocated. Returned with every download so the bias is attached to the
    artifact and not only to a docstring."""
    if year >= FIRST_OBSERVED_ON_2020_BLOCKS:
        return "2020 census blocks, OBSERVED"
    return ("2020 census blocks, AREA-RETRO-ALLOCATED from the "
            f"{'2010' if year >= 2010 else '2000'} block geography -- a BIAS "
            "correlated with where block boundaries moved, not noise "
            "(CONTEXT.md 7.4b)")


def _fetch(url: str, timeout: int = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # A 404 on a vintage the listing advertises is a real change
            # upstream, not a flake. Do not burn four retries on it.
            if exc.code == 404:
                raise LodesFetchError(f"{url} -> HTTP 404") from exc
            last = exc
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised below
            last = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF_S * (attempt + 1))
    raise LodesFetchError(f"{url} failed after {MAX_RETRIES} tries: {last}")


def _write(dest: pathlib.Path, blob: bytes) -> dict:
    if not blob:
        raise LodesFetchError(
            f"{dest.name}: the server returned an empty body with no error. "
            f"Writing a zero-byte gzip would make every job count in that "
            f"vintage read as zero; refusing.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}


def plan(years=None, state: str = DEFAULT_STATE,
         lodes_dir: pathlib.Path = LODES_DIR) -> list[dict]:
    """What `--dry-run` prints: one row per file, with whether it is already on
    disk. No network access."""
    rows = [{
        "kind": "xwalk", "year": None, "url": xwalk_url(state),
        "path": str(lodes_dir / xwalk_filename(state)),
        "on_disk": (lodes_dir / xwalk_filename(state)).exists(),
        "blocks": "2020 census blocks; ONE crosswalk keys every vintage",
    }]
    for y in vintages(years):
        p = lodes_dir / wac_filename(y, state)
        rows.append({"kind": "wac", "year": y, "url": wac_url(y, state),
                     "path": str(p), "on_disk": p.exists(),
                     "blocks": block_vintage_note(y)})
    return rows


def download(years=None, state: str = DEFAULT_STATE,
             lodes_dir: pathlib.Path = LODES_DIR, *,
             refresh: bool = False, dry_run: bool = False,
             fetch=_fetch, progress=None) -> dict:
    """Fetch every requested WAC vintage plus the block crosswalk.

    Failure contract, and the reason this is a loop and not a script:

    * ONE year failing does NOT leave that year as zero rows. It raises, and
      the run stops, because `model/panel.py` reads whatever is on disk and a
      missing file there becomes a missing year in a panel with no marker.
    * A year already on disk is skipped unless `refresh`, and the skip is
      REPORTED, so "22 files present" and "22 files fetched" never look alike.
    * Every fetched file is recorded in `data/raw/lodes/manifest.json` with its
      URL, byte count, sha256 and the block-vintage note for that year, so the
      bias line above travels with the artifact.

    `fetch` is injectable so the loop can be tested without the network.
    """
    years = vintages(years)
    if dry_run:
        return {"dry_run": True, "state": state, "years": list(years),
                "plan": plan(years, state, lodes_dir)}

    manifest: dict = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text())
        except Exception:  # noqa: BLE001 - a corrupt manifest is not fatal
            manifest = {}

    fetched: list[dict] = []
    skipped: list[dict] = []

    xpath = lodes_dir / xwalk_filename(state)
    if xpath.exists() and not refresh:
        skipped.append({"kind": "xwalk", "path": str(xpath),
                        "reason": "already on disk (pass refresh=True to re-fetch)"})
    else:
        rec = _write(xpath, fetch(xwalk_url(state)))
        rec.update(kind="xwalk", url=xwalk_url(state), path=str(xpath),
                   blocks="2020 census blocks; ONE crosswalk keys every vintage")
        manifest[xwalk_filename(state)] = rec
        fetched.append(rec)
        if progress is not None:
            progress("xwalk", rec)

    for y in years:
        path = lodes_dir / wac_filename(y, state)
        if path.exists() and not refresh:
            skipped.append({"kind": "wac", "year": y, "path": str(path),
                            "reason": "already on disk (pass refresh=True to re-fetch)",
                            "blocks": block_vintage_note(y)})
            if progress is not None:
                progress(y, None)
            continue
        rec = _write(path, fetch(wac_url(y, state)))
        rec.update(kind="wac", year=y, url=wac_url(y, state), path=str(path),
                   blocks=block_vintage_note(y))
        manifest[wac_filename(y, state)] = rec
        fetched.append(rec)
        if progress is not None:
            progress(y, rec)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    on_disk = sorted(y for y in years if (lodes_dir / wac_filename(y, state)).exists())
    missing = sorted(set(years) - set(on_disk))
    if missing:
        raise LodesFetchError(
            f"after the run, vintages {missing} are still absent from "
            f"{lodes_dir}. Refusing to report success on a series with a hole "
            f"in it.")

    return {
        "state": state,
        "years_requested": list(years),
        "years_on_disk": on_disk,
        "fetched": fetched,
        "skipped": skipped,
        "bytes_fetched": sum(r["bytes"] for r in fetched),
        "manifest": str(MANIFEST),
        "block_geography": (
            "LODES8 puts EVERY vintage on 2020 census blocks. "
            f"{FIRST_OBSERVED_ON_2020_BLOCKS}-{LAST_VINTAGE} were observed there; "
            f"{FIRST_VINTAGE}-{FIRST_OBSERVED_ON_2020_BLOCKS - 1} were "
            "area-retro-allocated onto them, which is a BIAS correlated with "
            "where block boundaries moved, not noise (CONTEXT.md 7.4b)."),
    }
