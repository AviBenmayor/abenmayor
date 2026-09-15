"""THE SPEND CAP (D100, AC-18, AC-20) -- `analysis.spend_ledger`
(sql/033_poi_closure_evidence.sql), SHARED with `loci verify-closures`
(design-closure-evidence.md, RECONCILED 2026-09-14): one table, one
enforcement code path, so a report's $1.00 cap and a verify-closures
`--budget` run can never disagree about what "spent" means.

THE PATTERN, precedented by `validation.google_places.GooglePlacesClient`
(`_charge()` runs BEFORE the request, never after): `Budget.charge()` writes
the ledger row and raises `CapExceeded` BEFORE the caller makes the paid call,
never after. A call that fails after a successful `charge()` still shows as
spent -- that is the conservative failure mode (undercounting spend would let
a report exceed its cap; overcounting on a rare API failure costs at most one
call's worth of headroom).

Cost model, $1.00 default cap (design section 3, 2026-09-14 pricing):
  Places Text Search   $0.032   (businessStatus is a Pro field; D90's run
                                 priced 5,985 calls at ~$190, i.e. ~$0.0317)
  Tavily basic search   $0.008
  Claude prose         ~$0.45   (~14k input tokens x $10/M + ~6k output
                                 tokens x $50/M = $0.14 + $0.30)
Budget split at the $1.00 default: reserve $0.50 for prose, 3 Tavily searches
(rents/leases/news, `enrich.py`) = $0.024, leaving $0.476 for on-demand
closure checks -> 14 Places-only checks (0.476 / 0.032), fewer once web
follow-ups are needed. A `--cap 2.00` run affords ~45.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Per-provider unit price in USD. `anthropic_in_per_tok`/`out_per_tok` are
#: PER TOKEN (not per 1K/1M) so `estimate_anthropic` is a plain multiply.
PRICES: dict[str, float] = {
    "places": 0.032,
    "tavily": 0.008,
    "anthropic_in_per_tok": 10e-6,   # $10 / M input tokens
    "anthropic_out_per_tok": 50e-6,  # $50 / M output tokens
}

#: Reserved for the one prose call, out of the default $1.00 cap (section 3).
#: APPLIES ONLY to the metered `AnthropicProse` client -- `run.generate()`
#: reserves this unconditionally before `enrich()` runs (so closure checks
#: can never eat the whole cap) and releases it right after, before prose
#: is charged, so a plan-billed call (`clients.ClaudeCliProse`, GTM-172,
#: billed to the owner's Claude subscription rather than this ledger's cap)
#: never actually draws on the reservation: `prose.write_prose` charges it
#: $0.00 instead of estimating a per-token dollar cost that was never
#: incurred.
#:
#: PROVIDER VALUE FOR A PLAN-BILLED CALL: ideally a distinct `"claude_cli"`
#: provider, but `analysis.spend_ledger` (sql/033_poi_closure_evidence.sql)
#: has `provider VARCHAR NOT NULL CHECK (provider IN ('places', 'tavily',
#: 'anthropic'))` -- a DB-level constraint this build does not own and must
#: not edit. `write_prose` therefore charges a plan-billed call under
#: provider `"anthropic"` with `usd=0.0` and a `detail` string that says
#: "plan-billed" plus the estimated token count, so the row stays
#: distinguishable by `detail` even though `provider` cannot yet name it.
#: A follow-up migration widening that CHECK to include `"claude_cli"` would
#: let this switch to the cleaner value.
PROSE_RESERVE_USD = 0.50

VALID_PROVIDERS = ("places", "tavily", "anthropic")
VALID_KINDS = ("report", "verify")


class CapExceeded(RuntimeError):
    """Raised by `Budget.charge()` BEFORE the call that would exceed the cap.
    The message names the amounts so a CLI/log line needs no extra context."""


@dataclass
class PlannedCall:
    """One row of a `--dry-run` plan: what WOULD have been charged."""
    provider: str
    usd: float
    detail: str | None = None


@dataclass
class Budget:
    """The spend guard for one run (a report or a `verify-closures` sweep).

    `con` is a live DuckDB connection -- `charge()` both reads (`spent()`)
    and writes `analysis.spend_ledger` through it, so the cap is enforced
    against the SAME table every caller shares, not a private counter that
    could drift from what actually got written.

    `reserved_usd` is capacity set aside for a call not yet made (the prose
    call, charged only after `enrich.py` has spent on closure checks) --
    `can_afford`/`charge` count it against the cap exactly like spent money,
    so a report cannot spend its whole cap on closure checks and then find
    there is nothing left to reserve for prose.
    """
    run_id: str
    cap_usd: float
    con: object
    kind: str = "report"
    dry_run: bool = False
    reserved_usd: float = 0.0
    plan: list[PlannedCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Budget.kind must be one of {VALID_KINDS}, got {self.kind!r}")
        if self.cap_usd <= 0:
            raise ValueError(f"cap_usd must be positive, got {self.cap_usd!r}")

    def spent(self) -> float:
        """Sum of `usd` already written for this `run_id` (0.0 for a fresh run,
        including every `dry_run` run -- dry-run never writes a row)."""
        row = self.con.execute(
            "SELECT COALESCE(sum(usd), 0) FROM analysis.spend_ledger WHERE run_id = ?",
            [self.run_id]).fetchone()
        return float(row[0] or 0.0)

    def can_afford(self, usd: float) -> bool:
        return (self.spent() + self.reserved_usd + usd) <= self.cap_usd + 1e-9

    def reserve(self, usd: float) -> None:
        """Set aside `usd` of headroom for a call not yet made (prose). Does
        NOT write a ledger row -- only `charge()` does that, at the moment
        the call is actually about to happen."""
        self.reserved_usd += usd

    def release_reserve(self, usd: float) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - usd)

    def charge(self, provider: str, usd: float, *, detail: str | None = None,
              poi_id: str | None = None) -> None:
        """Charge `usd` against the cap for one paid call.

        `dry_run=True`: never touches the ledger table, never raises -- it
        only appends to `self.plan` so `--dry-run` can print what WOULD have
        been spent (AC-20: "prints the planned calls ... makes no paid
        calls").

        Real run: raises `CapExceeded` and logs the abort BEFORE writing
        anything, if `spent() + reserved_usd + usd` would exceed `cap_usd`.
        Otherwise writes the ledger row FIRST (charge-before-call, see module
        docstring) and returns -- the caller makes the actual API call only
        after this returns normally.
        """
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"provider must be one of {VALID_PROVIDERS}, got {provider!r}")
        if self.dry_run:
            self.plan.append(PlannedCall(provider=provider, usd=usd, detail=detail))
            return
        if not self.can_afford(usd):
            logger.warning(
                "budget_hit run_id=%s provider=%s usd=%.4f spent=%.4f "
                "reserved=%.4f cap=%.4f detail=%s",
                self.run_id, provider, usd, self.spent(), self.reserved_usd,
                self.cap_usd, detail)
            raise CapExceeded(
                f"charging ${usd:.4f} to {provider!r} would exceed the "
                f"${self.cap_usd:.2f} cap (spent ${self.spent():.4f}, "
                f"reserved ${self.reserved_usd:.4f}) -- run_id={self.run_id}")
        self.con.execute(
            "INSERT INTO analysis.spend_ledger "
            "(run_id, kind, provider, usd, ts, poi_id, detail) VALUES (?,?,?,?,?,?,?)",
            [self.run_id, self.kind, provider, usd, dt.datetime.now(), poi_id, detail])

    def true_up(self, provider: str, detail: str, new_usd: float) -> None:
        """UPDATE the row this run/provider/detail already charged to the
        REAL cost now known (`prose.write_prose`'s estimate-before/true-up-
        after: AC-21 wants exactly ONE `analysis.spend_ledger` row for the
        one Claude call, so the true-up corrects that row in place rather
        than inserting a second one). A no-op under `dry_run` (nothing was
        written to correct). Does not raise even if the true cost would
        exceed the cap -- the call already happened; a record can be
        corrected, a fact of spend cannot be undone."""
        if self.dry_run:
            return
        self.con.execute(
            "UPDATE analysis.spend_ledger SET usd = ? "
            "WHERE run_id = ? AND provider = ? AND detail = ?",
            [new_usd, self.run_id, provider, detail])
        if not self.can_afford(0.0):
            logger.warning(
                "prose true-up pushed run_id=%s over cap: spent=%.4f cap=%.4f",
                self.run_id, self.spent(), self.cap_usd)

    def estimate_anthropic(self, in_tokens: int, out_tokens: int) -> float:
        return (in_tokens * PRICES["anthropic_in_per_tok"]
                + out_tokens * PRICES["anthropic_out_per_tok"])

    def plan_total(self) -> float:
        """Sum of `self.plan` -- what `--dry-run` prints as the estimated
        total cost."""
        return sum(p.usd for p in self.plan)
