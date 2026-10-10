"""Codegen determinism + the six adversarial gate checks (Step 4).

Every adversarial test attacks the step's guarantee (sync/validation) and
proves the failure is caught loudly. None mutate the committed tree: they work
on temp copies, monkeypatched module globals, or pure functions with injected
data.
"""

from __future__ import annotations

import ast
import hashlib
import json
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
from litellm_mcp.registry import UNSET

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


def test_emitted_operations_match_inventory():
    emitted = generate.emit_tree(SPEC)
    names = [
        node.name
        for source in emitted.values()
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.decorator_list
    ]
    assert len(names) == len(set(names))
    assert set(names) == {operation.name for operation in OPS} - set(OVERRIDES)


@pytest.mark.parametrize(
    "name", ["get_client", "query_params", "slim_list", "verify_response", "UNSET", "cast", "body", "result"]
)
def test_emitted_parameters_cannot_shadow_symbols(monkeypatch, name):
    operation = OP_BY_NAME["new_team"]
    original = generate._collect_params(SPEC["components"]["schemas"], operation,
                                        SPEC["paths"][operation.path]["post"])
    params = original + [generate.Param(name, "query", "str", False)]
    monkeypatch.setattr(generate, "_collect_params", lambda *_args: params)
    monkeypatch.setattr(generate, "SLIMS", {"new_team": {"fields": ["team_id"]}})
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"skip": []}})
    with pytest.raises(generate.GenError, match=name) as caught:
        generate.emit_op_source(SPEC, operation)
    assert operation.name in str(caught.value)


def test_opaque_body_parameter_is_not_a_symbol_collision(
    monkeypatch, regenerated_op, client_env, respx_mock
):
    operation = OP_BY_NAME["add_model"]
    monkeypatch.setattr(generate, "_collect_params", lambda *_args: [
        generate.Param("body", "opaque", "dict[str, Any]", True)
    ])
    monkeypatch.setattr(generate, "VERIFY", {"add_model": {"no_verify": "opaque body"}})
    source, used = generate.emit_op_source(SPEC, operation)
    module = generate._module_header("write", used) + "\n\n" + source
    fn = regenerated_op(module, "add_model")
    route = respx_mock.post("/model/new").respond(200, json={"status": "created"})
    assert fn(body={"model_name": "m"}) == {"status": "created"}
    assert json.loads(route.calls.last.request.content) == {"model_name": "m"}


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


# --- (e) unlisted @op in tools/overrides.py -> reverse dedupe fails --------

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

                for omitted_value in (None, UNSET):
                    invalid = {**validated, field_name: omitted_value}
                    with pytest.raises(ValidationError) as caught:
                        model.model_validate(invalid)
                    if not _has_error_for_field(caught.value, field_name):
                        failures.append(
                            f"{op.name}.{field_name} rejects {omitted_value!r} elsewhere"
                        )

        recorder.calls.clear()
        monkeypatch.setitem(fn.__globals__, "get_client", lambda: recorder)
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


def test_update_credential_serializes_path_body_field_once(client_env, respx_mock):
    """The one MCP path argument is also sent exactly once in its required JSON body."""
    name = "UpdateCredential"
    fn = server._group_ops[server._all_grouped[name]][name]
    fields = fn._mcp_params_model.model_fields
    assert set(fields) == {"credential_name", "credential_info", "credential_values"}
    assert fields["credential_name"].is_required()
    route = respx_mock.patch("/credentials/credential-a").respond(200, json={})
    fn(
        credential_name="credential-a",
        credential_info={"label": "primary"},
        credential_values={"api_key": "secret"},
    )
    assert route.call_count == 1
    request = route.calls.last.request
    assert request.method == "PATCH"
    assert request.url.path == "/credentials/credential-a"
    assert json.loads(request.content) == {
        "credential_name": "credential-a",
        "credential_info": {"label": "primary"},
        "credential_values": {"api_key": "secret"},
    }


def test_slim_hook_projects_rows_and_applies_default_limit(
    monkeypatch, regenerated_op, client_env, respx_mock
):
    monkeypatch.setattr(generate, "SLIMS", {"list_keys": {"fields": ["token", "spend"], "limit": 5}})
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_read_core.py"], "list_keys")
    rows = [{"token": str(index), "spend": index, "secret": "hidden"} for index in range(7)]
    respx_mock.get("/key/list").respond(200, json=rows)
    assert fn() == {
        "data": [{"token": str(index), "spend": index} for index in range(5)],
        "total": 7,
        "returned": 5,
        "truncated": True,
    }
    assert fn(limit=0)["data"] == [{"token": str(index), "spend": index} for index in range(7)]


def test_slim_hook_preserves_envelope(monkeypatch, regenerated_op, client_env, respx_mock):
    monkeypatch.setattr(
        generate, "SLIMS", {"list_keys": {"fields": ["token"], "limit": 1, "container": "keys"}}
    )
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_read_core.py"], "list_keys")
    respx_mock.get("/key/list").respond(
        200, json={"keys": [{"token": "first", "secret": "hidden"}, {"token": "second"}], "page": 3}
    )
    assert fn() == {
        "data": [{"token": "first"}], "total": 2, "returned": 1,
        "truncated": True, "page_info": {"page": 3},
    }


def test_verify_skip_checks_other_fields(monkeypatch, regenerated_op, client_env, respx_mock):
    monkeypatch.setattr(generate, "ROOT_SKIP", frozenset())
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"skip": ["team_id"]}})
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_write.py"], "new_team")
    route = respx_mock.post("/team/new").respond(200, json={"team_alias": "t"})
    assert fn(team_id="id", team_alias="t") == {"team_alias": "t"}
    route.respond(200, json={})
    with pytest.raises(ValueError, match="team_alias"):
        fn(team_id="id", team_alias="t")


def test_verify_subset_checks_only_sent_subset(
    monkeypatch, regenerated_op, client_env, respx_mock
):
    monkeypatch.setattr(generate, "VERIFY", {"new_team": {"subset": ["team_id", "tpm_limit"]}})
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_write.py"], "new_team")
    route = respx_mock.post("/team/new").respond(200, json={"team_id": "id"})
    assert fn(team_id="id", team_alias="t") == {"team_id": "id"}
    with pytest.raises(ValueError, match="tpm_limit"):
        fn(team_id="id", team_alias="t", tpm_limit=5)
    route.respond(200, json={"team_id": "id", "tpm_limit": 5})
    assert fn(team_id="id", tpm_limit=5)["tpm_limit"] == 5


def test_no_verify_accepts_non_echo_response(
    monkeypatch, regenerated_op, client_env, respx_mock
):
    monkeypatch.setattr(generate, "VERIFY", {"add_model": {"no_verify": "envelope"}})
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_write.py"], "add_model")
    respx_mock.post("/model/new").respond(200, json={"status": "created"})
    assert fn(model_name="m", litellm_params={}, model_info={}) == {"status": "created"}


def test_verify_entry_on_bodyless_op_fails(monkeypatch):
    """A body-referencing verify entry (skip/subset) on a bodyless op is a GenError."""
    monkeypatch.setattr(generate, "VERIFY", {"global_spend_reset": {"skip": []}})
    with pytest.raises(generate.GenError) as exc:
        generate.emit_tree(SPEC)
    assert "global_spend_reset" in str(exc.value)


@pytest.mark.parametrize(
    "name,module,path,params,field",
    [
        ("block_key", "execute", "/key/block", {"key": "sk-test"}, "blocked"),
        ("global_spend_reset", "admin", "/global/spend/reset", {}, "status"),
    ],
)
def test_verify_present_requires_response_key(
    monkeypatch, regenerated_op, client_env, respx_mock, name, module, path, params, field
):
    monkeypatch.setattr(generate, "VERIFY", {name: {"present": [field]}})
    fn = regenerated_op(generate.emit_tree(SPEC)[f"_generated_{module}.py"], name)
    route = respx_mock.post(path).respond(200, json={})
    with pytest.raises(ValueError, match=field):
        fn(**params)
    route.respond(200, json={field: False})
    assert fn(**params) == {field: False}


def test_no_verify_allowed_on_bodyless(monkeypatch, regenerated_op, client_env, respx_mock):
    monkeypatch.setattr(generate, "VERIFY", {"global_spend_reset": {"no_verify": "envelope"}})
    fn = regenerated_op(generate.emit_tree(SPEC)["_generated_admin.py"], "global_spend_reset")
    respx_mock.post("/global/spend/reset").respond(200, json={"unrelated": "value"})
    assert fn() == {"unrelated": "value"}


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
