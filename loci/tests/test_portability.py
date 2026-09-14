"""The portability audit: field validation, generator determinism, drift check.

Three things are pinned here, and the third is the one that would otherwise rot:

1. Every non-wishlist registry entry carries a valid `portability` block, and
   `registry.validate()` actually REJECTS a bad one. A validator that is never
   shown to fail is a validator nobody has tested.
2. `portability.render()` is deterministic and derived — the same registry
   renders the same bytes, and the minimum-input-set arithmetic follows
   `recommend_grades.yaml` rather than a hardcoded answer.
3. docs/PORTABILITY.md is a byte-identical render of the current registry.
"""
from __future__ import annotations

import copy
import pathlib

import pytest
import yaml

from loci import portability as pt
from loci import registry

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- fields

def non_wishlist() -> list[dict]:
    return [s for s in registry.load()["sources"] if s.get("status") != "wishlist"]


def test_every_non_wishlist_source_is_classed():
    """The audit is only worth anything if it covers the whole pipeline."""
    missing = [s["id"] for s in non_wishlist() if "portability" not in s]
    assert not missing, f"unclassed sources: {missing}"


def test_wishlist_entries_are_not_classed():
    """A wishlist entry is a thing we would BUY, not a pipeline input.

    Classing it would put paid sources into the minimum-input-set arithmetic,
    which is exactly the confusion the wishlist/registry split exists to avoid.
    """
    classed = [s["id"] for s in registry.load()["sources"]
               if s.get("status") == "wishlist" and "portability" in s]
    assert not classed, f"wishlist entries carry portability: {classed}"


@pytest.mark.parametrize("src", non_wishlist(), ids=lambda s: s["id"])
def test_portability_block_is_well_formed(src):
    p = src["portability"]
    assert p["class"] in registry.VALID_PORTABILITY_CLASS
    assert p["feeds"] and all(f in registry.PIPELINE_STAGES for f in p["feeds"])
    assert len(set(p["feeds"])) == len(p["feeds"])
    # degrades_to must be a sentence, not a shrug.
    assert len(p["degrades_to"].split()) >= 8
    if p.get("confidence") in {"low", "med"}:
        assert p.get("note"), f"{src['id']}: an uncertain class must say why"


def test_the_registry_as_it_stands_is_valid():
    assert registry.validate() == []


# --------------------------------------------------------------------------- the
# validator has to actually reject things. Each case mutates a COPY of the
# registry and asserts the specific error surfaces.

@pytest.mark.parametrize("mutate,fragment", [
    (lambda s: s.pop("portability"), "requires a `portability` block"),
    (lambda s: s["portability"].update(**{"class": "kind_of_universal"}),
     "bad portability class"),
    (lambda s: s["portability"].update(feeds=["univers"]), "unknown pipeline stage"),
    (lambda s: s["portability"].update(feeds=[]), "non-empty list of stages"),
    (lambda s: s["portability"].update(feeds=["demand", "demand"]), "duplicate stage"),
    (lambda s: s["portability"].update(degrades_to="less data"), "must be a sentence"),
    (lambda s: s["portability"].update(confidence="probably"),
     "bad portability confidence"),
    (lambda s: s["portability"].update(confidence="low", note=None),
     "requires a `note`"),
    (lambda s: s["portability"].update(whatever="hi"), "unknown portability keys"),
])
def test_validator_rejects_a_broken_block(mutate, fragment):
    src = copy.deepcopy(next(s for s in non_wishlist() if s["status"] == "verified"))
    mutate(src)
    errors = registry._validate_portability(src)
    assert any(fragment in e for e in errors), (fragment, errors)


def test_a_deferred_or_excluded_source_may_omit_the_block_but_not_break_it():
    """Required for verified/planned only -- but still enum-checked when present."""
    src = {"id": "x", "status": "excluded"}
    assert registry._validate_portability(src) == []
    src["portability"] = {"class": "nonsense", "feeds": ["demand"],
                          "degrades_to": "one two three four five six seven eight"}
    assert any("bad portability class" in e for e in registry._validate_portability(src))


# --------------------------------------------------------------------- generator

def test_render_is_deterministic():
    assert pt.render() == pt.render()


def test_render_names_every_classed_source():
    text = pt.render()
    for s in pt.pipeline_sources():
        assert s["name"] in text, s["id"]


def test_every_stage_has_at_least_one_source():
    """A stage nothing feeds is either a dead stage or a missing `feeds` entry."""
    empty = [st for st, rows in pt.by_stage().items() if not rows]
    assert not empty, f"stages with no source: {empty}"


def test_minimum_input_set_follows_the_grade_config_not_a_hardcoded_answer():
    """The verdict is the MINIMUM over the load-bearing sections. Pin that."""
    grades = yaml.safe_load(pt.GRADES_PATH.read_text())
    for target in ("B", "C", "D"):
        req = pt.minimum_input_set(target)
        assert req["verdict"] == grades["verdict"]["by_grade"][target]
        assert set(req["per_section"]) == set(grades["load_bearing"])
        for section, tier in req["per_section"].items():
            if tier is None:
                assert section in req["blocked_by"]
                continue
            assert pt._at_least(tier["grade"], target), (section, tier["grade"], target)
            assert set(tier["sources"]) <= set(req["sources"])


def test_minimum_sets_are_nested_and_shrink_as_the_bar_drops():
    """A weaker verdict can never need MORE inputs than a stronger one."""
    b = set(pt.minimum_input_set("B")["sources"])
    c = set(pt.minimum_input_set("C")["sources"])
    d = set(pt.minimum_input_set("D")["sources"])
    assert d <= c <= b
    assert len(d) < len(b)


def test_act_is_not_reachable_on_open_data():
    """D74's ruling, read through the portability lens.

    `economics` cannot reach B without cash-flow comps, which no city
    publishes. If this test ever fails it means a free economics rung was
    added -- a real change worth a decision-log entry, not a test to relax.
    """
    req = pt.minimum_input_set("B")
    assert req["paid_sections"] == ["economics"] or req["blocked_by"]


def test_section_inputs_reference_real_registry_ids():
    known = set(pt.sources_by_id())
    for section, tiers in pt.SECTION_INPUTS.items():
        for tier in tiers:
            unknown = set(tier["sources"]) - known
            assert not unknown, f"{section}: {sorted(unknown)}"
            assert tier["grade"] in pt.GRADE_ORDER
        # best grade first, so minimum_input_set can take the last qualifying tier
        order = [pt.GRADE_ORDER.index(t["grade"]) for t in tiers]
        assert order == sorted(order), f"{section}: tiers must be best-grade-first"


def test_section_inputs_covers_every_graded_section():
    grades = yaml.safe_load(pt.GRADES_PATH.read_text())
    for section in grades["load_bearing"] + grades["context"]:
        assert section in pt.SECTION_INPUTS, section


def test_requirements_reference_real_registry_ids():
    known = set(pt.sources_by_id())
    for r in pt.REQUIREMENTS:
        unknown = set(r["nyc"]) - known
        assert not unknown, f"{r['generic']}: {sorted(unknown)}"
        assert r["tier"] in pt.REQ_TIER_LABEL


def test_every_minimum_input_appears_in_the_new_city_table():
    """What a new city must publish has to cover what the screen actually needs."""
    covered = {sid for r in pt.REQUIREMENTS for sid in r["nyc"]}
    missing = set(pt.minimum_input_set("C")["sources"]) - covered
    assert not missing, f"minimum inputs absent from the requirements table: {missing}"


def test_city_probe_is_well_formed():
    for c in pt.CITY_PROBE:
        assert set(c["inputs"]) == set(pt.PROBE_INPUTS), c["city"]
        assert c["grade_today"] in pt.GRADE_ORDER
        assert c["grade_ceiling"] in pt.GRADE_ORDER
        # A city cannot be better on day one than its own ceiling.
        assert pt._at_least(c["grade_ceiling"], c["grade_today"]), c["city"]
        for inp, row in c["inputs"].items():
            assert row["status"] in pt.STATUS_MARK, (c["city"], inp)
            assert row["note"].strip(), (c["city"], inp)


# -------------------------------------------------------------------- drift check

def test_doc_is_a_byte_identical_render():
    doc = ROOT / "docs" / "PORTABILITY.md"
    assert doc.exists(), "run `loci gen-portability`"
    assert doc.read_text() == pt.render(), (
        "docs/PORTABILITY.md is GENERATED and has drifted — run `loci gen-portability`")


def test_check_sources_catches_doc_drift(tmp_path, monkeypatch):
    """Prove the drift check FAILS on a hand-edit, not just that it passes today."""
    fake = tmp_path / "docs"
    fake.mkdir()
    (fake / "PORTABILITY.md").write_text(pt.render() + "\n\nand also everything is fine")
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    errors = registry._validate_portability_doc(non_wishlist())
    assert any("differs from a fresh render" in e for e in errors), errors


def test_check_sources_catches_a_missing_doc(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    errors = registry._validate_portability_doc(non_wishlist())
    assert any("missing" in e for e in errors), errors
