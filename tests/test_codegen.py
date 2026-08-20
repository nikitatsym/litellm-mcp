"""Codegen determinism + the six adversarial gate checks (Step 4).

Every adversarial test attacks the step's guarantee (sync/validation) and
proves the failure is caught loudly. None mutate the committed tree: they work
on temp copies, monkeypatched module globals, or pure functions with injected
data.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest
from pydantic import ValidationError

from codegen import check, generate
from codegen.inventory import OP_BY_NAME, OPS, Op
from codegen.overrides import OVERRIDES
from codegen.path_body import PATH_BODY_FIELD_DISPOSITIONS
from litellm_mcp import server
from litellm_mcp.registry import _UNSET

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


class _RecordedSSE:
    def __enter__(self):
        return ()

    def __exit__(self, *_args):
        return False


class _BodyRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*_args, **kwargs):
            self.calls.append((name, _args, kwargs))
            return _RecordedSSE() if name == "post_sse" else None

        return call


def _sample_for_annotation(annotation):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return args[0]
    if origin is list:
        return []
    if origin is dict:
        return {}
    if args:
        return _sample_for_annotation(
            next(arg for arg in args if arg is not type(None))
        )
    if annotation is bool:
        return True
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    return "value"


def _resolve_openapi_ref(value):
    while "$ref" in value:
        ref = value["$ref"]
        value = SPEC
        for part in ref.removeprefix("#/").split("/"):
            value = value[part]
    return value

def _resolve_openapi_body(value):
    schema = _resolve_openapi_ref(value)
    if "anyOf" in schema:
        non_null = [member for member in schema["anyOf"] if member.get("type") != "null"]
        if len(non_null) == 1:
            return _resolve_openapi_ref(non_null[0])
    return schema


def _path_body_field_collisions():
    collisions = set()
    for op in OPS:
        spec_op = SPEC["paths"][op.path][op.method.lower()]
        if "requestBody" not in spec_op:
            continue
        request_body = _resolve_openapi_ref(spec_op["requestBody"])
        schema = _resolve_openapi_body(
            request_body["content"]["application/json"]["schema"]
        )
        path_fields = set(re.findall(r"{([^}]+)}", op.path))
        for name in schema.get("properties", {}):
            if name in path_fields:
                collisions.add((op.name, name))
    return collisions


def test_path_body_field_dispositions_match_openapi():
    """Every path/body name collision has one current, explicit disposition."""
    assert set(PATH_BODY_FIELD_DISPOSITIONS) == _path_body_field_collisions()
    for key, entry in PATH_BODY_FIELD_DISPOSITIONS.items():
        assert set(entry) == {"action", "reason"}, key
        assert entry["action"] in {"serialize", "exempt"}, key
        assert entry["reason"].strip(), key


def _required_openapi_body_cases():
    for op in OPS:
        spec_op = SPEC["paths"][op.path][op.method.lower()]
        if "requestBody" not in spec_op:
            continue
        request_body = _resolve_openapi_ref(spec_op["requestBody"])
        if not request_body.get("required"):
            continue
        schema = _resolve_openapi_body(
            request_body["content"]["application/json"]["schema"]
        )
        dispositions = {
            name: entry["action"]
            for (op_name, name), entry in PATH_BODY_FIELD_DISPOSITIONS.items()
            if op_name == op.name
        }
        fields = [
            name
            for name in schema.get("required", [])
            if name in schema.get("properties", {})
            and dispositions.get(name) != "exempt"
        ]
        if fields:
            yield op, "fields", fields
        elif "properties" in schema:
            yield op, "empty", []
        else:
            yield op, "opaque", ["body"]


def _has_error_for_field(error, field_name):
    return any(item["loc"] and item["loc"][0] == field_name for item in error.errors())


def test_required_openapi_bodies_are_required_or_serialized(monkeypatch):
    """Snapshot-required bodies cannot be silently omitted by registered tools."""
    recorder = _BodyRecorder()
    covered_overrides = set()
    required_body_overrides = {
        "apply_guardrail",
        "update_prompt",
        "test_prompt",
    }
    failures = []

    for op, shape, fields in _required_openapi_body_cases():
        op_name = server._to_pascal(op.name)
        group_name = server._all_grouped[op_name]
        fn = server._group_ops[group_name][op_name]
        if op.name in OVERRIDES:
            covered_overrides.add(op.name)
        model = fn._mcp_params_model
        complete = {
            name: _sample_for_annotation(field.annotation)
            for name, field in model.model_fields.items()
            if field.is_required()
        }
        validated = model.model_validate(complete).model_dump(exclude_unset=True)

        if shape == "fields" or shape == "opaque":
            schema_required = model.model_json_schema().get("required", [])
            for field_name in fields:
                if field_name not in schema_required:
                    failures.append(f"{op.name}.{field_name} is not schema-required")
                    continue

                missing = dict(validated)
                missing.pop(field_name)
                with pytest.raises(ValidationError) as caught:
                    model.model_validate(missing)
                if not _has_error_for_field(caught.value, field_name):
                    failures.append(
                        f"{op.name}.{field_name} omission failed for another field"
                    )

                for omitted_value in (None, _UNSET):
                    invalid = {**validated, field_name: omitted_value}
                    with pytest.raises(ValidationError) as caught:
                        model.model_validate(invalid)
                    if not _has_error_for_field(caught.value, field_name):
                        failures.append(
                            f"{op.name}.{field_name} rejects {omitted_value!r} elsewhere"
                        )

        recorder.calls.clear()
        monkeypatch.setitem(fn.__globals__, "_get_client", lambda: recorder)
        fn(**validated)
        if not recorder.calls:
            failures.append(f"{op.name} did not make an HTTP call")
            continue
        sent = recorder.calls[-1][2].get("json")
        if shape == "empty":
            if sent != {}:
                failures.append(f"{op.name} sent {sent!r} instead of an empty body")
        elif shape == "opaque":
            if sent != validated["body"]:
                failures.append(f"{op.name} did not serialize its required body")
        else:
            if not isinstance(sent, dict):
                failures.append(f"{op.name} sent a non-object body {sent!r}")
                continue
            for field_name in fields:
                if field_name not in sent:
                    failures.append(f"{op.name}.{field_name} was omitted at wire")
                elif sent[field_name] != validated[field_name]:
                    failures.append(
                        f"{op.name}.{field_name} serialized {sent[field_name]!r} "
                        f"instead of {validated[field_name]!r}"
                    )

    assert required_body_overrides <= covered_overrides, (
        "Required JSON-body overrides escaped the registered-operation guard: "
        f"{sorted(required_body_overrides - covered_overrides)}"
    )
    assert not failures, "; ".join(failures)


def test_update_credential_serializes_path_body_field_once(monkeypatch):
    """The one MCP path argument is also sent exactly once in its required JSON body."""
    op_name = "UpdateCredential"
    fn = server._group_ops[server._all_grouped[op_name]][op_name]
    assert tuple(fn._mcp_params_model.model_fields) == (
        "credential_name",
        "credential_info",
        "credential_values",
    )

    recorder = _BodyRecorder()
    monkeypatch.setitem(fn.__globals__, "_get_client", lambda: recorder)
    fn(
        credential_name="credential-a",
        credential_info={"label": "primary"},
        credential_values={"api_key": "secret"},
    )

    assert recorder.calls == [
        (
            "patch",
            ("/credentials/credential-a",),
            {
                "json": {
                    "credential_name": "credential-a",
                    "credential_info": {"label": "primary"},
                    "credential_values": {"api_key": "secret"},
                }
            },
        )
    ]


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
