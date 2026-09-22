from __future__ import annotations

import yaml

from loci import research


def _write_status(rq_dir, **stages):
    (rq_dir / "STATUS.yaml").write_text(yaml.safe_dump(stages))


def test_next_number_starts_at_one_on_empty_tree(tmp_path):
    assert research.next_number(tmp_path) == 1


def test_next_number_is_max_plus_one(tmp_path):
    (tmp_path / "RQ-001-first").mkdir()
    (tmp_path / "RQ-003-third").mkdir()
    assert research.next_number(tmp_path) == 4


def test_scaffold_creates_next_free_number_and_full_file_set(tmp_path):
    out = research.scaffold("regime-durability", title="Regime durability", research_dir=tmp_path)
    assert out.name == "RQ-001-regime-durability"
    for fname in research.STAGE_FILES + ["STATUS.yaml"]:
        assert (out / fname).exists(), fname

    # A second RQ picks up the next number.
    out2 = research.scaffold("second-question", research_dir=tmp_path)
    assert out2.name == "RQ-002-second-question"


def test_scaffold_rejects_bad_slug(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        research.scaffold("Not A Slug", research_dir=tmp_path)


def test_scaffold_rejects_duplicate_slug(tmp_path):
    import pytest

    research.scaffold("dupe", research_dir=tmp_path)
    with pytest.raises(ValueError):
        research.scaffold("dupe", research_dir=tmp_path)


def test_check_passes_on_freshly_scaffolded_rq(tmp_path):
    research.scaffold("regime-durability", research_dir=tmp_path)
    result = research.check_all(tmp_path, ticket_ids=set())
    assert result.ok, result.errors


def test_check_fails_on_missing_answer_with_status_done(tmp_path):
    rq_dir = tmp_path / "RQ-001-regime-durability"
    rq_dir.mkdir(parents=True)
    (rq_dir / "SEED.yaml").write_text("goal: x\n")
    (rq_dir / "QUESTION.md").write_text("# question\n")
    (rq_dir / "DATA-AUDIT.md").write_text("| Pillar |\n")
    (rq_dir / "notebook.ipynb").write_text("{}")
    # ANSWER.md deliberately not created.
    _write_status(
        rq_dir,
        seed={"status": "done"},
        question={"status": "done"},
        data_audit={"status": "done"},
        notebook={"status": "done"},
        answer={"status": "done"},
    )

    result = research.check_all(tmp_path, ticket_ids=set())
    assert not result.ok
    assert any("ANSWER.md" in e and "missing" in e for e in result.errors)


def test_check_passes_with_pending_status_for_missing_files(tmp_path):
    rq_dir = tmp_path / "RQ-001-regime-durability"
    rq_dir.mkdir(parents=True)
    (rq_dir / "SEED.yaml").write_text("goal: x\n")
    # question / data_audit / notebook / answer all absent, all marked pending.
    _write_status(
        rq_dir,
        seed={"status": "done"},
        question={"status": "pending", "reason": "not started"},
        data_audit={"status": "pending", "reason": "being written by another agent"},
        notebook={"status": "pending", "reason": "not started"},
        answer={"status": "pending", "reason": "not started"},
    )

    result = research.check_all(tmp_path, ticket_ids=set())
    assert result.ok, result.errors


def test_check_pending_without_reason_fails(tmp_path):
    rq_dir = tmp_path / "RQ-001-x"
    rq_dir.mkdir(parents=True)
    (rq_dir / "SEED.yaml").write_text("goal: x\n")
    _write_status(
        rq_dir,
        seed={"status": "done"},
        question={"status": "pending"},  # no reason
        data_audit={"status": "pending", "reason": "r"},
        notebook={"status": "pending", "reason": "r"},
        answer={"status": "pending", "reason": "r"},
    )
    result = research.check_all(tmp_path, ticket_ids=set())
    assert not result.ok
    assert any("no reason" in e for e in result.errors)


def test_check_fails_on_dangling_ticket_id(tmp_path):
    rq_dir = tmp_path / "RQ-001-x"
    rq_dir.mkdir(parents=True)
    (rq_dir / "SEED.yaml").write_text("goal: x\n")
    (rq_dir / "QUESTION.md").write_text("cites GTM-999 which does not exist\n")
    (rq_dir / "DATA-AUDIT.md").write_text("| Pillar |\n")
    (rq_dir / "notebook.ipynb").write_text("{}")
    (rq_dir / "ANSWER.md").write_text("answer\n")
    _write_status(
        rq_dir,
        seed={"status": "done"},
        question={"status": "done"},
        data_audit={"status": "done"},
        notebook={"status": "done"},
        answer={"status": "done"},
    )

    result = research.check_all(tmp_path, ticket_ids={"GTM-1"})
    assert not result.ok
    assert any("GTM-999" in e for e in result.errors)


def test_check_passes_when_ticket_id_resolves(tmp_path):
    rq_dir = tmp_path / "RQ-001-x"
    rq_dir.mkdir(parents=True)
    (rq_dir / "SEED.yaml").write_text("goal: x\n")
    (rq_dir / "QUESTION.md").write_text("cites GTM-1 which does exist\n")
    (rq_dir / "DATA-AUDIT.md").write_text("| Pillar |\n")
    (rq_dir / "notebook.ipynb").write_text("{}")
    (rq_dir / "ANSWER.md").write_text("answer\n")
    _write_status(
        rq_dir,
        seed={"status": "done"},
        question={"status": "done"},
        data_audit={"status": "done"},
        notebook={"status": "done"},
        answer={"status": "done"},
    )

    result = research.check_all(tmp_path, ticket_ids={"GTM-1"})
    assert result.ok, result.errors


def test_resolve_rq_accepts_loose_ids(tmp_path):
    research.scaffold("regime-durability", research_dir=tmp_path)
    for loose in ("RQ-001", "RQ-1", "1", "RQ-001-regime-durability"):
        rq = research.resolve_rq(loose, research_dir=tmp_path)
        assert rq.name == "RQ-001-regime-durability"


def test_valid_ticket_ids_scans_tickets_module():
    # Real tickets.py has GTM ids stamped into description text; smoke-test the
    # scanner finds at least one without asserting on the exact (large, changing) set.
    ids = research.valid_ticket_ids()
    assert any(i.startswith("GTM-") for i in ids)
