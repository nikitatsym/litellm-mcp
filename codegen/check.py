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

from .generate import GenError, emit_tree, load_spec
from .inventory import OP_BY_NAME
from .overrides import OVERRIDES

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _REPO_ROOT / "src" / "litellm_mcp" / "tools"

# Modules whose per-op completeness (annotations/slims/verify coverage, and
# "an override entry must be implemented in tools/overrides.py") is enforced.
# Empty in Step 4; Steps 5-8 add modules as their data lands.
GATED_MODULES: frozenset[str] = frozenset()


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
        if path.read_text() != want:
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
        emitted = emit_tree(load_spec())
    except GenError as exc:
        print(f"codegen: generation error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    impl_names = overrides_impl_names(overrides_module, ROOT)
    problems = check_sync(_TOOLS_DIR, emitted)
    problems += check_override_dedupe(OVERRIDES, OP_BY_NAME, GATED_MODULES, impl_names)

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
