"""Codegen determinism + the six adversarial gate checks (Step 4).

Every adversarial test attacks the step's guarantee (sync/validation) and
proves the failure is caught loudly. None mutate the committed tree: they work
on temp copies, monkeypatched module globals, or pure functions with injected
data.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codegen import check, generate
from codegen.inventory import OP_BY_NAME, OPS, Op
from codegen.overrides import OVERRIDES

SPEC = generate.load_spec()
_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_two_runs_byte_identical():
    """Determinism: two consecutive generator runs produce identical bytes."""
    first = generate.emit_tree(SPEC)
    second = generate.emit_tree(SPEC)
    assert first == second
    assert set(first) == {
        "_generated_read_core.py",
        "_generated_read_infra.py",
        "_generated_write.py",
        "_generated_execute.py",
        "_generated_delete.py",
        "_generated_admin.py",
        "_generated_platform.py",
        "_generated_prompts.py",
    }


def _emit_digest(seed: int) -> str:
    """Digest of the full emitted tree from a fresh process at `PYTHONHASHSEED`."""
    code = (
        "import hashlib;"
        "from codegen.generate import emit_tree, load_spec;"
        "f = emit_tree(load_spec());"
        "b = ''.join(f'{k}\\n{v}' for k, v in sorted(f.items()));"
        "print(hashlib.sha256(b.encode()).hexdigest())"
    )
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_cross_process_determinism():
    """The emitter is byte-stable across processes with different hash seeds -
    set iteration must never leak into emitted source (only sorted lists do)."""
    digests = {_emit_digest(seed) for seed in (0, 1, 42)}
    assert len(digests) == 1, digests
    # And it matches the in-process emission (same interpreter build).
    blob = "".join(f"{k}\n{v}" for k, v in sorted(generate.emit_tree(SPEC).items()))
    assert hashlib.sha256(blob.encode()).hexdigest() in digests


def test_emitted_op_count():
    emitted = generate.emit_tree(SPEC)
    total = sum(src.count("\n@_op(") for src in emitted.values())
    # overrides are hand-written in tools/overrides.py, not emitted
    assert total == len(OPS) - len(OVERRIDES)


# --- (a) hand-mutate a generated file -> sync gate fails --------------------

def test_a_hand_mutated_file_fails_sync(tmp_path):
    emitted = generate.emit_tree(SPEC)
    for name, src in emitted.items():
        (tmp_path / name).write_text(src, encoding="utf-8", newline="\n")
    victim = tmp_path / "_generated_read_core.py"
    victim.write_text(
        victim.read_text(encoding="utf-8").replace("def budget_info(", "def budget_INFO(", 1),
        encoding="utf-8",
        newline="\n",
    )

    problems = check.check_sync(tmp_path, emitted)
    assert any("_generated_read_core.py" in p for p in problems), problems


# --- (b) stale annotation key -> generation fails naming it -----------------

def test_b_stale_annotation_key_fails(monkeypatch):
    monkeypatch.setattr(generate, "ANNOTATIONS", {"no_such_op": {"doc": "x"}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "no_such_op" in str(exc.value)


# --- (c) inventory row at a path absent from the snapshot -> fails ----------

def test_c_bad_inventory_path_fails(monkeypatch):
    mutated = tuple(
        Op(o.name, o.group, o.module, o.method, "/does/not/exist") if o.name == "list_keys" else o
        for o in OPS
    )
    monkeypatch.setattr(generate, "OPS", mutated)
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    msg = str(exc.value)
    assert "list_keys" in msg and "not found" in msg


# --- (d) gated override not implemented -> dedupe fails ---------------------

def test_d_gated_override_not_implemented_fails():
    problems = check.check_override_dedupe(
        OVERRIDES, OP_BY_NAME, gated_modules=frozenset({"write"}), impl_names=set()
    )
    assert any("update_organization" in p and "gated" in p for p in problems), problems


# --- (e) unlisted @_op in tools/overrides.py -> reverse dedupe fails --------

def test_e_unlisted_override_impl_fails():
    problems = check.check_override_dedupe(
        OVERRIDES, OP_BY_NAME, gated_modules=frozenset(), impl_names={"sneaky_op"}
    )
    assert any("sneaky_op" in p for p in problems), problems


# --- (f) remove a spec-gap op from overrides -> bodyless rule fails ---------

def test_f_removing_spec_gap_override_fails_bodyless(monkeypatch):
    without = {k: v for k, v in OVERRIDES.items() if k != "create_eval"}
    monkeypatch.setattr(generate, "OVERRIDES", without)
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    msg = str(exc.value)
    assert "create_eval" in msg and "requestBody" in msg


def test_committed_tree_is_in_sync():
    """The real sync gate: committed tree byte-matches fresh generation."""
    emitted = generate.emit_tree(SPEC)
    problems = check.check_sync(check._TOOLS_DIR, emitted)
    assert problems == []


# --- slim emission (active in Step 5) / verify emission (dormant until Step 6) -

def test_slim_hook_emits_slim_list(monkeypatch):
    """A bare slims entry wraps the list op in _slim_list and injects `limit`."""
    monkeypatch.setattr(generate, "SLIMS", {"list_keys": {"fields": ["token", "spend"], "limit": 5}})
    src = generate.emit_tree(SPEC)["_generated_read_core.py"]
    assert "result = _get_client().get" in src
    assert "return _slim_list(result, {'token', 'spend'}, limit)" in src
    assert "] = 5," in src  # injected limit param default from the entry


def test_slim_hook_emits_container(monkeypatch):
    """An entry with a container passes the envelope key to _slim_list."""
    monkeypatch.setattr(
        generate, "SLIMS", {"list_keys": {"fields": ["token"], "limit": 5, "container": "keys"}}
    )
    src = generate.emit_tree(SPEC)["_generated_read_core.py"]
    assert "return _slim_list(result, {'token'}, limit, 'keys')" in src


def test_verify_hook_emits_verify_call(monkeypatch):
    """A skip-form verify.py entry makes the write op check the echoed row."""
    monkeypatch.setattr(generate, "ROOT_SKIP", frozenset())
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"skip": ["team_id"]}})
    src = generate.emit_tree(SPEC)["_generated_write.py"]
    assert "_verify_response(body, result, frozenset({'team_id'}))" in src


def test_verify_hook_emits_subset_call(monkeypatch):
    """A subset entry filters the sent body to the whitelisted keys."""
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"subset": ["team_id", "tpm_limit"]}})
    src = generate.emit_tree(SPEC)["_generated_write.py"]
    assert (
        "_verify_response({k: body[k] for k in ('team_id', 'tpm_limit',) if k in body}, result)"
        in src
    )


def test_verify_no_verify_emits_nothing(monkeypatch):
    """A no_verify entry emits no _verify_response call for that op."""
    monkeypatch.setattr(generate, "VERIFY", {"add_model": {"no_verify": "envelope"}})
    src = generate.emit_tree(SPEC)["_generated_write.py"]
    # add_model is the only VERIFY entry here, so nothing verifies.
    assert "_verify_response" not in src


def test_verify_entry_on_bodyless_op_fails(monkeypatch):
    """A body-referencing verify entry (skip/subset) on a bodyless op is a GenError."""
    monkeypatch.setattr(generate, "VERIFY", {"global_spend_reset": {"skip": []}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "global_spend_reset" in str(exc.value)


def test_verify_present_emits_response_key_check(monkeypatch):
    """A present entry checks response keys regardless of what was sent (Step 7)."""
    monkeypatch.setattr(generate, "VERIFY", {"block_key": {"present": ["blocked"]}})
    src = generate.emit_tree(SPEC)["_generated_execute.py"]
    assert "_verify_response({k: None for k in ('blocked',)}, result)" in src


def test_verify_no_verify_allowed_on_bodyless(monkeypatch):
    """no_verify on a bodyless op is allowed - it emits nothing, no GenError."""
    monkeypatch.setattr(generate, "VERIFY", {"global_spend_reset": {"no_verify": "envelope"}})
    src = generate.emit_tree(SPEC)["_generated_admin.py"]
    assert "def global_spend_reset() -> Any:" in src
    assert "_verify_response" not in src  # the only VERIFY entry, and it verifies nothing


def test_verify_present_allowed_on_bodyless(monkeypatch):
    """present references response keys only, so it is legal even with no body."""
    monkeypatch.setattr(generate, "VERIFY", {"global_spend_reset": {"present": ["status"]}})
    src = generate.emit_tree(SPEC)["_generated_admin.py"]
    assert "_verify_response({k: None for k in ('status',)}, result)" in src


def test_verify_present_non_list_fails(monkeypatch):
    """present must be a non-empty list."""
    monkeypatch.setattr(generate, "VERIFY", {"block_key": {"present": []}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "block_key" in str(exc.value)


def test_verify_subset_non_body_field_fails(monkeypatch):
    """A subset naming a field that isn't a body param is a GenError."""
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"subset": ["not_a_field"]}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "not_a_field" in str(exc.value)


def test_write_module_verifies_reads_do_not():
    """The write module emits _verify_response; read modules never do."""
    emitted = generate.emit_tree(SPEC)
    assert "_slim_list(" in emitted["_generated_read_core.py"]
    assert "_slim_list(" in emitted["_generated_read_infra.py"]
    assert "_verify_response(" in emitted["_generated_write.py"]
    assert "_verify_response" not in emitted["_generated_read_core.py"]
    assert "_verify_response" not in emitted["_generated_read_infra.py"]


def test_missing_verify_decision_fails(monkeypatch):
    """The write completeness gate demands a verify decision per write-shaped op."""
    without = {k: v for k, v in check.VERIFY.items() if k != "new_team"}
    monkeypatch.setattr(check, "VERIFY", without)
    problems = check.check_completeness(frozenset({"write"}), SPEC)
    assert any("new_team" in p and "verify" in p for p in problems), problems


# --- (g/h) completeness gate bites when a gated op loses its decision --------

def test_g_missing_annotation_decision_fails(monkeypatch):
    without = {k: v for k, v in check.ANNOTATIONS.items() if k != "list_budgets"}
    monkeypatch.setattr(check, "ANNOTATIONS", without)
    problems = check.check_completeness(frozenset({"read_core"}), SPEC)
    assert any("list_budgets" in p and "annotations" in p for p in problems), problems


def test_h_missing_slim_decision_fails(monkeypatch):
    without = {k: v for k, v in check.SLIMS.items() if k != "list_keys"}
    monkeypatch.setattr(check, "SLIMS", without)
    problems = check.check_completeness(frozenset({"read_core"}), SPEC)
    assert any("list_keys" in p and "slims" in p for p in problems), problems


def test_unknown_annotation_inner_key_fails(monkeypatch):
    monkeypatch.setattr(generate, "ANNOTATIONS", {"list_budgets": {"typo": "x"}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "list_budgets" in str(exc.value)
