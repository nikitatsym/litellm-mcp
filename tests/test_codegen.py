"""Codegen determinism + the six adversarial gate checks (Step 4).

Every adversarial test attacks the step's guarantee (sync/validation) and
proves the failure is caught loudly. None mutate the committed tree: they work
on temp copies, monkeypatched module globals, or pure functions with injected
data.
"""

from __future__ import annotations

import pytest

from codegen import check, generate
from codegen.inventory import OP_BY_NAME, OPS, Op
from codegen.overrides import OVERRIDES

SPEC = generate.load_spec()


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
    }


def test_emitted_op_count_is_192():
    emitted = generate.emit_tree(SPEC)
    total = sum(src.count("\n@_op(") for src in emitted.values())
    assert total == 192  # 198 inventory ops minus the 6 pending overrides


# --- (a) hand-mutate a generated file -> sync gate fails --------------------

def test_a_hand_mutated_file_fails_sync(tmp_path):
    emitted = generate.emit_tree(SPEC)
    for name, src in emitted.items():
        (tmp_path / name).write_text(src)
    victim = tmp_path / "_generated_read_core.py"
    victim.write_text(victim.read_text().replace("def budget_info(", "def budget_INFO(", 1))

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


# --- data-driven hooks: dormant with empty data, proven via injection -------

def test_slim_hook_emits_truncate(monkeypatch):
    """A slims.py entry makes the list op wrap its result (Step 5 activates this)."""
    monkeypatch.setattr(generate, "SLIMS", {"list_keys": {"fields": ["token", "spend"], "limit": 5}})
    src = generate.emit_tree(SPEC)["_generated_read_core.py"]
    assert "result = _get_client().get" in src
    assert "_truncate([_slim(row, {'token', 'spend'}) for row in result], 5)" in src


def test_verify_hook_emits_verify_call(monkeypatch):
    """A verify.py entry makes the write op verify the echoed row (Step 6 activates this)."""
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"skip": ["team_id"]}})
    src = generate.emit_tree(SPEC)["_generated_write.py"]
    assert "_verify_response(body, result, frozenset({'team_id'}))" in src


def test_step4_tree_has_no_slim_or_verify_calls():
    """With empty data the emitted tree references no slim/verify helpers."""
    for src in generate.emit_tree(SPEC).values():
        assert "_verify_response" not in src
        assert "_slim(" not in src
        assert "result =" not in src
