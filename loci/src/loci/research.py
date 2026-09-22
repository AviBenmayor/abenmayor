"""The research-question framework: `docs/research/RQ-NNN-<slug>/` scaffolding and
its drift gate.

Every Loci research question (RQ-001 regime durability, and every one after it) follows
the same fixed sequence — interview, seed, data audit, notebook, answer, review, tickets,
checkpoint (see `docs/research/README.md`) — and lands in the same five-file folder.
This module is that framework's machinery:

  `loci research new <slug>`    scaffold a new RQ-NNN folder from src/loci/research_template
  `loci research check`         the drift gate: every RQ has its required stage files
                                 (or an honest STATUS.yaml explaining why not), and every
                                 ticket id (`GTM-\\d+`) cited in its prose resolves in
                                 `loci.tickets.T`
  `loci research run <rq-id>`   execute the RQ's notebook.ipynb in place

`check` is the pure function `check_all()`; the CLI command is a thin wrapper that prints
and sets the exit code, the same split `registry.validate()` / `check-sources` and
`questions.validate()` / `check-questions` use. `run` reuses `loci.tickets.T` read-only —
it never writes tickets; that stays gen-tickets/tickets.py's job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

PKG = Path(__file__).resolve().parent
ROOT = PKG.parents[1]
TEMPLATE_DIR = PKG / "research_template"
RESEARCH_DIR = ROOT / "docs" / "research"

#: (stage key in STATUS.yaml, required filename). Order matches the fixed sequence.
STAGES: list[tuple[str, str]] = [
    ("seed", "SEED.yaml"),
    ("question", "QUESTION.md"),
    ("data_audit", "DATA-AUDIT.md"),
    ("notebook", "notebook.ipynb"),
    ("answer", "ANSWER.md"),
]
STAGE_FILES = [f for _, f in STAGES]

#: Files whose prose is scanned for ticket citations.
CITING_FILES = ("QUESTION.md", "DATA-AUDIT.md", "ANSWER.md")

_RQ_DIR_RE = re.compile(r"^RQ-(\d{3})-(.+)$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_TICKET_ID_RE = re.compile(r"\bGTM-\d+\b")
_VALID_STAGE_STATUS = {"done", "pending", "blocked"}


@dataclass
class RQFolder:
    path: Path
    number: int
    slug: str

    @property
    def rq_id(self) -> str:
        return f"RQ-{self.number:03d}"

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- discovery

def list_rq_folders(research_dir: Path = RESEARCH_DIR) -> list[RQFolder]:
    """Every `RQ-NNN-<slug>/` folder under `research_dir`, sorted by number."""
    out: list[RQFolder] = []
    if not research_dir.exists():
        return out
    for p in sorted(research_dir.iterdir()):
        if not p.is_dir():
            continue
        m = _RQ_DIR_RE.match(p.name)
        if not m:
            continue
        out.append(RQFolder(path=p, number=int(m.group(1)), slug=m.group(2)))
    return out


def next_number(research_dir: Path = RESEARCH_DIR) -> int:
    """The next free RQ number (1 if none exist yet)."""
    nums = [f.number for f in list_rq_folders(research_dir)]
    return max(nums, default=0) + 1


# ----------------------------------------------------------------------------- scaffold

def _render(text: str, *, rq_id: str, title: str, slug: str, today: str) -> str:
    return (
        text.replace("__RQ_ID__", rq_id)
        .replace("__TITLE__", title)
        .replace("__SLUG__", slug)
        .replace("__DATE__", today)
    )


def scaffold(slug: str, title: str | None = None, research_dir: Path = RESEARCH_DIR) -> Path:
    """Create `docs/research/RQ-NNN-<slug>/` from the template, with the next free NNN.

    Raises ValueError on a malformed slug or a slug already in use (any number).
    """
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"slug {slug!r} must be lowercase kebab-case (e.g. 'regime-durability')"
        )
    for existing in list_rq_folders(research_dir):
        if existing.slug == slug:
            raise ValueError(f"slug {slug!r} already used by {existing.name}")

    n = next_number(research_dir)
    rq_id = f"RQ-{n:03d}"
    dir_name = f"{rq_id}-{slug}"
    out_dir = research_dir / dir_name
    out_dir.mkdir(parents=True, exist_ok=False)

    today = date.today().isoformat()
    display_title = title or slug.replace("-", " ")
    for src in sorted(TEMPLATE_DIR.iterdir()):
        if not src.is_file():
            continue
        text = src.read_text()
        rendered = _render(text, rq_id=rq_id, title=display_title, slug=slug, today=today)
        (out_dir / src.name).write_text(rendered)

    return out_dir


# -------------------------------------------------------------------------------- check

def _load_status(rq_dir: Path) -> dict:
    """Parse STATUS.yaml if present; `{}` (every stage defaults to required) if not."""
    p = rq_dir / "STATUS.yaml"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{p} must be a mapping of stage -> {{status, reason}}")
    return data


def valid_ticket_ids() -> set[str]:
    """Every `GTM-\\d+` id mentioned anywhere in `loci.tickets.T` (titles + descriptions).

    Ticket definitions carry no explicit id field (see tickets.py) — the Linear id is
    stamped into the description text once pushed (house style: "Pushed to Linear ...
    as GTM-NNN"). Scanning the whole definition list, not just that phrase, also admits
    a ticket a description merely *mentions* as a prerequisite — deliberately permissive,
    since the failure mode this check guards against is a typo'd or invented id, not a
    id that is real but not yet "the" ticket for this row.
    """
    from loci.tickets import T

    ids: set[str] = set()
    for row in T:
        for field_ in row:
            if isinstance(field_, str):
                ids.update(_TICKET_ID_RE.findall(field_))
    return ids


def check_rq(rq: RQFolder, ticket_ids: set[str]) -> list[str]:
    """Errors for one RQ folder: missing required stage files, malformed STATUS.yaml,
    and ticket ids cited in its prose that don't resolve in tickets.py."""
    errors: list[str] = []

    try:
        status = _load_status(rq.path)
    except ValueError as exc:
        return [f"{rq.name}: {exc}"]

    for stage_key, filename in STAGES:
        stage = status.get(stage_key, {}) or {}
        stage_status = stage.get("status", "done")
        if stage_status not in _VALID_STAGE_STATUS:
            errors.append(
                f"{rq.name}: STATUS.yaml stage {stage_key!r} has invalid status "
                f"{stage_status!r} (expected one of {sorted(_VALID_STAGE_STATUS)})"
            )
            continue
        if stage_status in ("pending", "blocked") and not stage.get("reason"):
            errors.append(
                f"{rq.name}: STATUS.yaml stage {stage_key!r} is {stage_status!r} but "
                "carries no reason"
            )
        exists = (rq.path / filename).exists()
        if not exists and stage_status == "done":
            errors.append(
                f"{rq.name}: {filename} is missing but STATUS.yaml marks {stage_key!r} "
                "as done"
            )

    for filename in CITING_FILES:
        p = rq.path / filename
        if not p.exists():
            continue
        cited = set(_TICKET_ID_RE.findall(p.read_text()))
        for tid in sorted(cited - ticket_ids):
            errors.append(
                f"{rq.name}/{filename}: cites {tid}, which is not defined in "
                "src/loci/tickets.py"
            )

    return errors


def check_all(research_dir: Path = RESEARCH_DIR, ticket_ids: set[str] | None = None) -> CheckResult:
    """Run `check_rq` over every RQ folder. `ticket_ids` overrides the tickets.py scan
    (tests pass a fixed set instead of importing the real, large ticket list)."""
    ids = valid_ticket_ids() if ticket_ids is None else ticket_ids
    errors: list[str] = []
    for rq in list_rq_folders(research_dir):
        errors.extend(check_rq(rq, ids))
    return CheckResult(errors=errors)


# ---------------------------------------------------------------------------------- run

def resolve_rq(rq_id: str, research_dir: Path = RESEARCH_DIR) -> RQFolder:
    """Resolve a loose id ('RQ-001', 'RQ-1', '1', or the full folder name) to its folder."""
    m = re.match(r"^(?:RQ-)?(\d+)", rq_id)
    if not m:
        raise ValueError(f"can't parse an RQ number out of {rq_id!r}")
    n = int(m.group(1))
    for f in list_rq_folders(research_dir):
        if f.number == n:
            return f
    raise ValueError(f"no RQ-{n:03d}-* folder under {research_dir}")


def run_notebook(rq: RQFolder) -> None:
    """Execute `notebook.ipynb` in place from the repo root. Raises ImportError with a
    clear message if nbformat/nbclient aren't installed (they're not in pyproject.toml
    today — `uv add nbformat nbclient` before this command works)."""
    try:
        import nbformat
        from nbclient import NotebookClient
    except ImportError as exc:
        raise ImportError(
            "loci research run needs `nbformat` and `nbclient` "
            "(not currently in pyproject.toml — `uv add nbformat nbclient`)"
        ) from exc

    nb_path = rq.path / "notebook.ipynb"
    if not nb_path.exists():
        raise FileNotFoundError(f"{nb_path} does not exist")
    nb = nbformat.read(nb_path, as_version=4)
    client = NotebookClient(nb, resources={"metadata": {"path": str(ROOT)}})
    client.execute()
    nbformat.write(nb, nb_path)


# ------------------------------------------------------------------------------- typer

research_app = typer.Typer(add_completion=False, help=__doc__)
console = Console()


@research_app.command(name="new")
def cmd_new(
    slug: str = typer.Argument(..., help="kebab-case slug, e.g. 'regime-durability'."),
    title: str = typer.Option(None, "--title", help="Display title; defaults to the slug."),
) -> None:
    """Scaffold docs/research/RQ-NNN-<slug>/ from the template, at the next free NNN."""
    try:
        out_dir = scaffold(slug, title=title)
    except (ValueError, FileExistsError) as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]ok[/] scaffolded {out_dir.relative_to(ROOT)}")


@research_app.command(name="check")
def cmd_check() -> None:
    """Fail if any RQ folder is missing a required stage file (per its STATUS.yaml) or
    cites a ticket id that isn't defined in src/loci/tickets.py."""
    result = check_all()
    for e in result.errors:
        console.print(f"[red]FAIL[/] {e}")
    n = len(list_rq_folders())
    if result.ok:
        console.print(f"[green]ok[/] {n} research question(s) checked")
    raise typer.Exit(1 if not result.ok else 0)


@research_app.command(name="run")
def cmd_run(rq_id: str = typer.Argument(..., help="'RQ-001', '1', or the full folder name.")) -> None:
    """Execute an RQ's notebook.ipynb in place with nbclient."""
    try:
        rq = resolve_rq(rq_id)
    except ValueError as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc
    try:
        run_notebook(rq)
    except (ImportError, FileNotFoundError) as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]ok[/] executed {rq.name}/notebook.ipynb")


def _rq_status_table() -> Table:
    table = Table(title="Research questions")
    for col in ("RQ", "slug", "ticket issues"):
        table.add_column(col)
    ids = valid_ticket_ids()
    for rq in list_rq_folders():
        n_errors = len(check_rq(rq, ids))
        table.add_row(rq.rq_id, rq.slug, str(n_errors) if n_errors else "-")
    return table
