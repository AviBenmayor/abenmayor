"""AC-19: `loci.report.cache`. `tmp_path` + monkeypatch of `CACHE_DIR` so
these tests never touch the real `data/interim/report_cache`."""
from __future__ import annotations

import datetime as dt

from loci.report import cache


def test_put_then_get_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.put("addr1", "hash1", markdown="# hi", path="docs/recommendations/x.md",
             total_usd=0.42, run_id="r1")
    got = cache.get("addr1", "hash1")
    assert got is not None
    assert got.markdown == "# hi"
    assert got.total_usd == 0.42
    assert got.run_id == "r1"


def test_get_is_none_on_a_pure_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    assert cache.get("nope", "nohash") is None


def test_different_evidence_hash_is_a_different_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache.put("addr1", "hashA", markdown="A", path="a.md", total_usd=0.1, run_id="r1")
    assert cache.get("addr1", "hashB") is None
    assert cache.get("addr1", "hashA").markdown == "A"


def test_entry_older_than_ttl_is_a_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    old = dt.datetime.now() - dt.timedelta(days=31)
    cache.put("addr1", "hash1", markdown="stale", path="a.md", total_usd=0.1,
             run_id="r1", now=old)
    assert cache.get("addr1", "hash1") is None
    # ...but is still fresh under a longer TTL
    assert cache.get("addr1", "hash1", ttl_days=60) is not None


def test_a_corrupt_cache_file_is_a_safe_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    p = tmp_path / f"{cache.key('addr1', 'hash1')}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert cache.get("addr1", "hash1") is None
