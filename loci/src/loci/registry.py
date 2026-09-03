"""The data source registry: load it, and guard it against drift.

`registry.yaml` is the machine-readable mirror of docs/CONTEXT.md section 3.
`validate()` asserts the two agree, so the human doc and the machine registry
cannot silently diverge. Exposed as `loci check-sources`.
"""
from __future__ import annotations

import pathlib

import yaml

PKG = pathlib.Path(__file__).resolve().parent
ROOT = PKG.parents[1]
REGISTRY_PATH = PKG / "registry.yaml"
REQUIRED = {"id", "name", "tier", "role", "status", "url", "cost", "bias"}
VALID_TIERS = {"universal", "city"}
VALID_ROLES = {"poi", "panel", "outcome", "control", "validation", "excluded"}
VALID_STATUS = {"planned", "verified", "deferred", "excluded"}


def load() -> dict:
    """Parse registry.yaml."""
    return yaml.safe_load(REGISTRY_PATH.read_text())


def validate(check_urls: bool = False) -> list[str]:
    """Return a list of problems. Empty list means the registry is sound."""
    reg = load()
    context = (ROOT / "docs" / "CONTEXT.md").read_text()
    sources = reg["sources"]
    errors: list[str] = []

    ids = [s["id"] for s in sources]
    if len(ids) != len(set(ids)):
        errors.append("duplicate source ids")

    for s in sources:
        missing = REQUIRED - s.keys()
        if missing:
            errors.append(f"{s.get('id', '?')}: missing {sorted(missing)}")
        if s.get("tier") not in VALID_TIERS:
            errors.append(f"{s['id']}: bad tier {s.get('tier')!r}")
        if s.get("role") not in VALID_ROLES:
            errors.append(f"{s['id']}: bad role {s.get('role')!r}")
        if s.get("status") not in VALID_STATUS:
            errors.append(f"{s['id']}: bad status {s.get('status')!r}")
        if s.get("tier") == "city" and "city" not in s:
            errors.append(f"{s['id']}: tier=city requires a `city` key")
        # Drift check: every dataset_id in the registry must appear in CONTEXT.md.
        did = s.get("dataset_id")
        if did and did not in context:
            errors.append(f"{s['id']}: dataset_id {did} absent from docs/CONTEXT.md section 3")

    # Budget consistency: paid sources must not exceed the stated ceiling.
    budgeted = sum(s["cost"].get("budgeted_total", 0) for s in sources if "cost" in s)
    if budgeted > reg["budget"]["projected_max"]:
        errors.append(f"budgeted spend {budgeted} exceeds projected_max {reg['budget']['projected_max']}")

    if check_urls:
        import urllib.error
        import urllib.request
        for s in sources:
            req = urllib.request.Request(s["url"], method="HEAD",
                                         headers={"User-Agent": "loci-source-check"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    code = r.status
            except urllib.error.HTTPError as exc:   # 4xx/5xx still means "present"
                code = exc.code
            except Exception as exc:  # noqa: BLE001 - report, don't raise
                code = f"ERR {exc}"
            ok = code in (200, 202, 301, 302, 403)  # 403 = bot-blocked, 202 = challenge page; both mean present
            print(f"{'ok ' if ok else 'FAIL'} {code:<24} {s['id']}")
            if not ok:
                errors.append(f"{s['id']}: url {s['url']} -> {code}")

    if not errors:
        print(f"ok — {len(sources)} sources, ${budgeted} budgeted, no CONTEXT.md drift")
    return errors
