"""Codegen sync gate + data validation, wired into `dev.py lint`.

Permanent, strongest-possible sync check (Decision 14): regenerate in memory
and byte-compare with the committed `_generated_*` tree; ANY diff fails. Plus
data validation (stale keys, bad shapes, bodyless rule - raised by the emitter)
and override dedupe in BOTH directions. The per-module completeness allowlist
(`GATED_MODULES`) is EMPTY in Step 4 and grows as Steps 5-8 land.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from litellm_mcp.registry import ROOT
from litellm_mcp.tools import overrides as overrides_module

from .annotations import ANNOTATIONS
from .generate import GenError, emit_tree, load_spec
from .inventory import OP_BY_NAME, OPS, Op
from .overrides import OVERRIDES
from .slims import SLIMS
from .verify import VERIFY
from .waivers import WAIVED_UNCOVERED

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _REPO_ROOT / "src" / "litellm_mcp" / "tools"

# Modules whose per-op completeness (annotations + slims coverage, verify
# coverage on write-shaped ops, and "an override entry must be implemented in
# tools/overrides.py") is enforced. Grows as Steps 5-8 land.
GATED_MODULES: frozenset[str] = frozenset(
    {"read_core", "read_infra", "write", "execute", "delete", "admin", "platform", "prompts"}
)

# Ops that return a homogeneous collection but whose 200 schema is `{}` in the
# snapshot, so shape detection cannot see the array. Curated so the slims gate
# still demands a decision for them.
_UNTYPED_LIST_OPS: frozenset[str] = frozenset({"model_info", "spend_logs"})

_COVERAGE_VERBS: tuple[str, ...] = ("get", "post", "put", "patch", "delete")
# Covered outside OPS: litellm_version -> GET /health/readiness.
_ROOT_COVERED: frozenset[tuple[str, str]] = frozenset({("/health/readiness", "GET")})


def _is_list_op(op: Op, spec: dict[str, Any]) -> bool:
    """A list op is one whose response is a collection worth a slim decision:
    a `list_*` op, a curated untyped-list op, or a bare-array response."""
    if op.name.startswith("list_") or op.name in _UNTYPED_LIST_OPS:
        return True
    # Every inventory row resolves against the snapshot (enforced by the
    # emitter); a missing path here would be a real bug, so index directly.
    spec_op = spec["paths"][op.path][op.method.lower()]
    schema = (
        spec_op.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return bool(schema.get("type") == "array")


def check_completeness(gated_modules: frozenset[str], spec: dict[str, Any]) -> list[str]:
    """Every emitted op in a gated module is explicitly decided in annotations;
    every emitted list op is decided in slims; every emitted write-shaped op is
    decided in verify. Overrides carry their own docstrings/fields/verify by
    hand, so they are exempt.

    Write-shaped = risk group is not `read`. POST-but-read ops (budget_info,
    tag_info, cloudzero_dry_run, ...) stay in the read group, so read modules
    and platform read ops never need a verify decision."""
    problems: list[str] = []
    for op in OPS:
        if op.module not in gated_modules or op.name in OVERRIDES:
            continue
        if op.name not in ANNOTATIONS:
            problems.append(
                f"{op.name} (module {op.module}) has no annotations decision "
                "(add an entry or a bare marker in codegen/annotations.py)"
            )
        if _is_list_op(op, spec) and op.name not in SLIMS:
            problems.append(
                f"{op.name} (module {op.module}) is a list op with no slims decision "
                "(add an entry or no_slim in codegen/slims.py)"
            )
        if op.group != "read" and op.name not in VERIFY:
            problems.append(
                f"{op.name} (module {op.module}) is a write-shaped op with no verify "
                "decision (add a skip/subset entry or NO_VERIFY in codegen/verify.py)"
            )
    return problems


def check_spec_coverage(spec: dict[str, Any]) -> list[str]:
    """Every spec endpoint (path + CRUD verb) is wrapped by an OPS row, a ROOT
    op, or explicitly waived. Catches verbs dropped during transcription."""
    covered = {(op.path, op.method.upper()) for op in OPS} | _ROOT_COVERED
    problems: list[str] = []
    for path, item in spec["paths"].items():
        for verb in _COVERAGE_VERBS:
            pair = (path, verb.upper())
            if verb in item and pair not in covered and pair not in WAIVED_UNCOVERED:
                problems.append(f"uncovered spec endpoint: {verb.upper()} {path}")
    return sorted(problems)


def check_sync(compare_dir: Path, emitted: dict[str, str]) -> list[str]:
    """Byte-compare emitted sources against the tree in `compare_dir`."""
    problems: list[str] = []
    on_disk = {p.name for p in compare_dir.glob("_generated_*.py")}
    for name in sorted(set(emitted) | on_disk):
        want = emitted.get(name)
        path = compare_dir / name
        if want is None:
            problems.append(f"{name}: present on disk but not emitted (stale generated file)")
            continue
        if not path.exists():
            problems.append(f"{name}: emitted but missing on disk (run codegen)")
            continue
        if path.read_text(encoding="utf-8") != want:
            problems.append(f"{name}: committed tree differs from freshly generated output")
    return problems


def overrides_impl_names(module: ModuleType, root: Any) -> set[str]:
    """Names of non-ROOT @_op functions defined in tools/overrides.py."""
    names: set[str] = set()
    for fn_name, fn in inspect.getmembers(module, inspect.isfunction):
        group = getattr(fn, "_mcp_group", None)
        if group is not None and group is not root:
            names.add(fn_name)
    return names


def check_override_dedupe(
    overrides: dict[str, dict[str, Any]],
    op_by_name: dict[str, Any],
    gated_modules: frozenset[str],
    impl_names: set[str],
) -> list[str]:
    """Both directions of the no-runtime-duplicate invariant."""
    problems: list[str] = []
    # Forward: a gated-module override must be implemented in tools/overrides.py.
    for name in sorted(overrides):
        op = op_by_name.get(name)
        if op is None:
            problems.append(f"override {name!r} is not a known op")
            continue
        if op.module in gated_modules and name not in impl_names:
            problems.append(
                f"override {name!r} (module {op.module}) is gated but not implemented "
                "in tools/overrides.py"
            )
    # Reverse: every non-ROOT @_op in tools/overrides.py must be listed.
    for name in sorted(impl_names):
        if name not in overrides:
            problems.append(
                f"@_op {name!r} in tools/overrides.py is not listed in codegen/overrides.py "
                "(the generator would emit a duplicate)"
            )
    return problems


def main() -> int:
    try:
        spec = load_spec()
        emitted = emit_tree(spec)
    except GenError as exc:
        print(f"codegen: generation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    impl_names = overrides_impl_names(overrides_module, ROOT)
    problems = check_sync(_TOOLS_DIR, emitted)
    problems += check_override_dedupe(OVERRIDES, OP_BY_NAME, GATED_MODULES, impl_names)
    problems += check_completeness(GATED_MODULES, spec)
    problems += check_spec_coverage(spec)

    if problems:
        print("codegen sync gate FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Run `python -m codegen.generate` and commit the result.", file=sys.stderr)
        return 1
    print(f"codegen sync gate OK: {len(emitted)} generated modules byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
