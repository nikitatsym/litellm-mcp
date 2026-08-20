"""Deterministic emitter: (spec, inventory, judgment data) -> generated tools.

Pure function of its inputs (Decision 14): sorted iteration, no timestamps,
byte-stable output. For every inventory op not listed in `overrides.py` it
emits the full v2.5 op into `tools/_generated_<module>.py`. Data files drive
descriptions, slims, and verify hooks; with the Step-4 (empty) data the type
mapping is total and the emitted tree is mechanically correct but undescribed.

A shape outside the mapping rules, a stale data key, an unresolved inventory
row, or a body-mutating verb with no requestBody (and not in bodyless_ok or
overrides) is a `GenError` naming the op - loud, at generation time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .annotations import ANNOTATIONS
from .bodyless_ok import BODYLESS_OK
from .inventory import GROUP_VARS, MODULES, OPS, Op
from .overrides import OVERRIDES
from .path_body import PATH_BODY_FIELD_DISPOSITIONS
from .slims import SLIMS
from .verify import ROOT_SKIP, VERIFY

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATH = _REPO_ROOT / "codegen" / "openapi-v1.93.0.json"
_TOOLS_DIR = _REPO_ROOT / "src" / "litellm_mcp" / "tools"

_VERB = {"GET": "get", "POST": "post", "PUT": "put", "PATCH": "patch", "DELETE": "delete"}
_BODY_VERBS = {"POST", "PUT", "PATCH"}
_LIMIT_DESC = "Max rows kept after client-side slimming of the returned page (0 = no cap)."


class GenError(Exception):
    """A generation-time failure; the message names the offending op."""


# --- spec access -----------------------------------------------------------

def load_spec() -> dict[str, Any]:
    with _SPEC_PATH.open(encoding="utf-8") as fh:
        spec: dict[str, Any] = json.load(fh)
    return spec


def _resolve_ref(comps: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        return comps[schema["$ref"].split("/")[-1]]
    return schema


def _resolve_body(comps: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Unwrap `anyOf[Object, null]` / a bare `$ref` to the underlying object."""
    s = _resolve_ref(comps, schema)
    if "anyOf" in s:
        non_null = [m for m in s["anyOf"] if m.get("type") != "null"]
        if len(non_null) == 1:
            return _resolve_ref(comps, non_null[0])
    return s


# --- type mapping (total over the surface; else GenError) ------------------

def _union(parts: list[str]) -> str:
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    # `Any` (the sanctioned external-JSON boundary) absorbs the union.
    if "Any" in seen:
        return "Any"
    non_none = [p for p in seen if p != "None"]
    if "None" in seen:
        non_none.append("None")
    return " | ".join(non_none)


def map_type(schema: dict[str, Any]) -> str:
    """Map one JSON-Schema node to a Python type expression."""
    if "$ref" in schema:
        return "dict[str, Any]"
    if "enum" in schema:
        return "Literal[" + ", ".join(repr(v) for v in schema["enum"]) + "]"
    if "anyOf" in schema:
        return _union([map_type(m) for m in schema["anyOf"]])
    t = schema.get("type")
    if t == "array":
        return f"list[{map_type(schema.get('items', {}))}]"
    if t == "object":
        return "dict[str, Any]"
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "null":
        return "None"
    if t is None and not any(k in schema for k in ("allOf", "oneOf")):
        return "Any"  # untyped `{}` node - opaque JSON
    raise GenError(f"unmapped schema shape: {json.dumps(schema)[:120]}")


# --- per-op parameter collection -------------------------------------------

class Param:
    __slots__ = ("kind", "name", "required", "type_str")

    def __init__(self, name: str, kind: str, type_str: str, required: bool) -> None:
        self.name = name
        self.kind = kind  # path | path_body | query | body | opaque
        self.required = required
        self.type_str = type_str


def _collect_params(comps: dict[str, Any], op: Op, spec_op: dict[str, Any]) -> list[Param]:
    """Collect path, body, and query params with dispositioned path/body collisions."""
    path_names = re.findall(r"\{([^}]+)\}", op.path)
    declared_path = {
        p["name"]: p for p in spec_op.get("parameters", []) if p.get("in") == "path"
    }
    params: list[Param] = []
    path_params: dict[str, Param] = {}
    taken: set[str] = set()

    for pn in path_names:
        decl = declared_path.get(pn)
        type_str = map_type(decl["schema"]) if decl else "str"
        path_param = Param(pn, "path", type_str, required=True)
        params.append(path_param)
        path_params[pn] = path_param
        taken.add(pn)

    if "requestBody" in spec_op:
        body = _resolve_body(comps, spec_op["requestBody"]["content"]["application/json"]["schema"])
        if body.get("type") != "object":
            raise GenError(f"{op.name}: requestBody does not resolve to an object")
        if "properties" in body:
            required_fields = set(body.get("required", []))
            for fn, fs in body["properties"].items():
                if fn in taken:
                    if fn in path_params:
                        disposition = PATH_BODY_FIELD_DISPOSITIONS.get((op.name, fn))
                        if disposition is None:
                            raise GenError(
                                f"{op.name}.{fn}: path/body collision has no exact disposition"
                            )
                        action = disposition["action"]
                        if action == "serialize":
                            path_params[fn].kind = "path_body"
                        elif action != "exempt":
                            raise GenError(
                                f"{op.name}.{fn}: unknown path/body disposition {action!r}"
                            )
                    continue
                params.append(Param(fn, "body", map_type(fs), fn in required_fields))
                taken.add(fn)
        else:
            # Free-form map body (no named properties): one opaque param.
            required = bool(spec_op["requestBody"].get("required"))
            params.append(Param("body", "opaque", "dict[str, Any]", required))
            taken.add("body")

    for prm in spec_op.get("parameters", []):
        if prm.get("in") != "query":
            continue
        qn = prm["name"]
        if qn in taken:  # body wins over query (Decision 9: no key material in query)
            continue
        params.append(Param(qn, "query", map_type(prm["schema"]), bool(prm.get("required"))))
        taken.add(qn)

    return params


# --- emission --------------------------------------------------------------

def _apply_type_override(op_name: str, param: Param, ann: dict[str, Any]) -> str:
    override = ann.get("types", {}).get(param.name)
    return override if override else param.type_str


def _docstring(op: Op, spec_op: dict[str, Any], ann: dict[str, Any]) -> tuple[str, str]:
    head = ann.get("doc") or spec_op.get("summary") or op.name
    return head, ann.get("body", "")


def emit_op_source(spec: dict[str, Any], op: Op) -> tuple[str, set[str]]:
    """Emit one op's source. Returns (source, symbols-used) for imports."""
    comps = spec["components"]["schemas"]
    paths = spec["paths"]
    if op.path not in paths or op.method.lower() not in paths[op.path]:
        raise GenError(f"{op.name}: {op.method} {op.path!r} not found in the snapshot")
    spec_op = paths[op.path][op.method.lower()]

    has_body = "requestBody" in spec_op
    if op.method in _BODY_VERBS and not has_body and op.name not in BODYLESS_OK:
        raise GenError(
            f"{op.name}: {op.method} {op.path} has no requestBody and is not in "
            "bodyless_ok.py or overrides.py"
        )

    params = _collect_params(comps, op, spec_op)
    ann = ANNOTATIONS.get(op.name, {})
    param_descs = ann.get("params", {})
    slim = SLIMS.get(op.name)
    ver = VERIFY.get(op.name)
    _validate_hook(op.name, slim, ver)
    slim_active = bool(slim) and "no_slim" not in slim
    ver_active = bool(ver) and "no_verify" not in ver
    used: set[str] = {"Any", "_op", "_get_client", GROUP_VARS[op.group]}

    # signature: required params first, then optional (_UNSET default).
    def render(p: Param) -> str:
        ts = _apply_type_override(op.name, p, ann)
        if "Literal[" in ts:
            used.add("Literal")
        return ts

    def annotate(name: str, ts: str) -> str:
        """Wrap the type in Annotated[..., Field(description=...)] when the op
        carries a description for this param; the caller sees it in help and
        schema, the runtime default stays `_UNSET`."""
        desc = param_descs.get(name)
        if not desc:
            return ts
        used.update({"Annotated", "Field"})
        return f"Annotated[{ts}, Field(description={desc!r})]"

    ordered = [p for p in params if p.required] + [p for p in params if not p.required]
    sig_lines: list[str] = []
    for p in ordered:
        ts = render(p)
        ann_ts = annotate(p.name, ts)
        if p.required:
            sig_lines.append(f"    {p.name}: {ann_ts},")
        else:
            used.update({"cast", "_UNSET"})
            sig_lines.append(f"    {p.name}: {ann_ts} = cast({ts}, _UNSET),")

    # Slimmed list ops get a caller-facing `limit` (default 20) that caps the
    # returned page client-side, on top of any spec pagination params.
    if slim_active:
        if any(p.name == "limit" for p in params):
            raise GenError(f"{op.name}: slimmed op already declares a spec 'limit' param")
        used.update({"Annotated", "Field"})
        sig_lines.append(
            f"    limit: Annotated[int, Field(description={_LIMIT_DESC!r})] = {slim.get('limit', 20)},"
        )

    lines: list[str] = [f"@_op({GROUP_VARS[op.group]})"]
    if sig_lines:
        lines.append(f"def {op.name}(")
        lines.extend(sig_lines)
        lines.append(") -> Any:")
    else:
        lines.append(f"def {op.name}() -> Any:")

    head, body_doc = _docstring(op, spec_op, ann)
    if body_doc:
        lines.append(f'    """{head}')
        lines.append("")
        for bl in body_doc.splitlines():
            lines.append(f"    {bl}" if bl else "")
        lines.append('    """')
    else:
        lines.append(f'    """{head}"""')

    body_params = [p for p in params if p.kind == "body" or p.kind == "path_body"]
    query_params = [p for p in params if p.kind == "query"]
    opaque = next((p for p in params if p.kind == "opaque"), None)

    # `skip`/`subset` verify emit `_verify_response(body, ...)`, so those forms
    # require a named request body; a bodyless (or opaque-body) op carrying one is
    # a data error. `no_verify` emits nothing and `present` checks response keys
    # only (no body local), so both are allowed on bodyless ops - the Step-7
    # status-envelope and block/unblock cases need exactly that.
    references_body = ver_active and ("skip" in ver or "subset" in ver)
    if references_body and not body_params:
        raise GenError(
            f"{op.name}: has a body-referencing verify entry (skip/subset) but "
            "emits no request body (the _verify_response call would reference an "
            "absent body local)"
        )
    if ver_active and "subset" in ver:
        body_names = {p.name for p in body_params}
        unknown = sorted(f for f in ver["subset"] if f not in body_names)
        if unknown:
            raise GenError(f"{op.name}: verify subset names non-body field(s) {unknown}")

    body_stmts: list[str] = []
    if body_params:
        body_stmts.append("    body: dict[str, Any] = {}")
        for p in body_params:
            body_stmts.append(f"    if {p.name} is not _UNSET:")
            body_stmts.append(f'        body["{p.name}"] = {p.name}')

    url = f'f"{op.path}"' if "{" in op.path else f'"{op.path}"'
    call_args: list[str] = []
    if query_params:
        used.add("_qp")
        kw = ", ".join(f"{p.name}={p.name}" for p in query_params)
        call_args.append(f"params=_qp({kw})")
    if body_params or opaque is not None:
        call_args.append("json=body")

    verb = _VERB[op.method]
    call = f"_get_client().{verb}({url}"
    if call_args:
        call += ", " + ", ".join(call_args)
    call += ")"

    lines.extend(body_stmts)

    if not slim_active and not ver_active:
        lines.append(f"    return {call}")
    else:
        lines.append(f"    result = {call}")
        if ver_active:
            if "subset" in ver:
                # Whitelist form: check only the sent keys that the typed row
                # echoes. Root skip is irrelevant (the subset already excludes
                # transport fields).
                keys = ", ".join(repr(f) for f in ver["subset"])
                lines.append(
                    f"    _verify_response({{k: body[k] for k in ({keys},) if k in body}}, result)"
                )
            elif "present" in ver:
                # Presence form: assert the typed response echoes these keys
                # regardless of what was sent (block/unblock rows echo `blocked`
                # or a result field, not the addressing key we posted).
                keys = ", ".join(repr(f) for f in ver["present"])
                lines.append(
                    f"    _verify_response({{k: None for k in ({keys},)}}, result)"
                )
            else:
                skip = sorted(set(ROOT_SKIP) | set(ver.get("skip", [])))
                skip_lit = (
                    "frozenset({" + ", ".join(repr(s) for s in skip) + "})" if skip else "frozenset()"
                )
                lines.append(f"    _verify_response(body, result, {skip_lit})")
            used.add("_verify_response")
        if slim_active:
            fields = ", ".join(repr(f) for f in slim["fields"])
            container = slim.get("container")
            tail = f", {container!r}" if container else ""
            lines.append(f"    return _slim_list(result, {{{fields}}}, limit{tail})")
            used.add("_slim_list")
        else:
            lines.append("    return result")

    return "\n".join(lines), used


_SLIM_KEYS = {"fields", "limit", "container", "no_slim"}
_ANN_KEYS = {"doc", "body", "params", "types", "bare"}


def _validate_hook(name: str, slim: dict[str, Any] | None, ver: dict[str, Any] | None) -> None:
    if slim is not None:
        unknown = set(slim) - _SLIM_KEYS
        if unknown:
            raise GenError(f"{name}: unknown slims key(s) {sorted(unknown)}")
        if "no_slim" not in slim and "fields" not in slim:
            raise GenError(f"{name}: malformed slims entry {slim!r}")
    if ver is not None:
        if not ({"no_verify", "skip", "subset", "present"} & set(ver)):
            raise GenError(f"{name}: malformed verify entry {ver!r}")
        if "subset" in ver and not (isinstance(ver["subset"], list) and ver["subset"]):
            raise GenError(f"{name}: verify subset must be a non-empty list")
        if "present" in ver and not (isinstance(ver["present"], list) and ver["present"]):
            raise GenError(f"{name}: verify present must be a non-empty list")



def _path_body_field_collisions(spec: dict[str, Any]) -> set[tuple[str, str]]:
    """Return every request-body property that shares an operation's path name."""
    collisions: set[tuple[str, str]] = set()
    comps = spec["components"]["schemas"]
    paths = spec["paths"]
    for op in OPS:
        if op.path not in paths or op.method.lower() not in paths[op.path]:
            continue
        spec_op = paths[op.path][op.method.lower()]
        request_body = spec_op.get("requestBody")
        if request_body is None:
            continue
        body = _resolve_body(comps, request_body["content"]["application/json"]["schema"])
        path_fields = set(re.findall(r"\{([^}]+)}", op.path))
        for name in body.get("properties", {}):
            if name in path_fields:
                collisions.add((op.name, name))
    return collisions


def _validate_path_body_field_dispositions(spec: dict[str, Any]) -> None:
    """Every path/body collision has one exact, current, explained disposition."""
    actual = _path_body_field_collisions(spec)
    declared = set(PATH_BODY_FIELD_DISPOSITIONS)
    missing = sorted(actual - declared)
    stale = sorted(declared - actual)
    if missing or stale:
        details = []
        if missing:
            details.append(f"missing dispositions for {missing}")
        if stale:
            details.append(f"stale dispositions for {stale}")
        raise GenError("path_body.py: " + "; ".join(details))
    for key, entry in PATH_BODY_FIELD_DISPOSITIONS.items():
        if not isinstance(entry, dict):
            raise GenError(f"path_body.py: {key} has a malformed disposition")
        if set(entry) != {"action", "reason"}:
            raise GenError(f"path_body.py: {key} must contain only action and reason")
        if entry["action"] not in {"serialize", "exempt"}:
            raise GenError(f"path_body.py: {key} has unknown action {entry['action']!r}")
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise GenError(f"path_body.py: {key} needs a non-empty reason")

def _validate_keys() -> None:
    """Every data key must name a known op (stale keys are loud)."""
    known = {op.name for op in OPS}
    for label, data in (
        ("annotations", ANNOTATIONS),
        ("slims", SLIMS),
        ("verify", VERIFY),
        ("overrides", OVERRIDES),
        ("bodyless_ok", BODYLESS_OK),
    ):
        for key in data:
            if key not in known:
                raise GenError(f"unknown op {key!r} in {label}.py (stale data key)")
    for op_name, entry in ANNOTATIONS.items():
        unknown = set(entry) - _ANN_KEYS
        if unknown:
            raise GenError(f"{op_name}: unknown annotations key(s) {sorted(unknown)}")
    # bodyless_ok must not name an op that HAS a requestBody (both directions).
    spec = load_spec()
    for name in BODYLESS_OK:
        op = next(o for o in OPS if o.name == name)
        spec_op = spec["paths"][op.path][op.method.lower()]
        if "requestBody" in spec_op:
            raise GenError(f"{name}: listed in bodyless_ok.py but the endpoint HAS a requestBody")

    _validate_path_body_field_dispositions(spec)


def _module_header(module: str, ops_used: set[str]) -> str:
    typing_syms = [s for s in ("Annotated", "Any", "Literal", "cast") if s in ops_used]
    groups = sorted(s for s in ops_used if s.startswith("litellm_"))
    helpers = [s for s in ("_get_client", "_qp", "_slim_list", "_verify_response")
               if s in ops_used]
    registry = [s for s in ("_UNSET", "_op") if s in ops_used]

    out = [
        "# Generated by codegen/generate.py from openapi-v1.93.0.json. Do not edit.",
        f'"""{module} tools (generated). Edits are overwritten; change codegen/ instead."""',
        "",
        "from __future__ import annotations",
        "",
        f"from typing import {', '.join(typing_syms)}",
        "",
    ]
    if "Field" in ops_used:
        out += ["from pydantic import Field", ""]
    out += [
        f"from ..registry import {', '.join(registry)}",
        f"from .groups import {', '.join(groups)}",
        f"from .helpers import {', '.join(helpers)}",
    ]
    return "\n".join(out)


def emit_tree(spec: dict[str, Any]) -> dict[str, str]:
    """Return {filename: source} for every generated module. Deterministic."""
    _validate_keys()
    by_module: dict[str, list[tuple[str, str]]] = {m: [] for m in MODULES}
    used_by_module: dict[str, set[str]] = {m: set() for m in MODULES}

    for op in sorted(OPS, key=lambda o: o.name):
        if op.name in OVERRIDES:
            continue
        src, used = emit_op_source(spec, op)
        by_module[op.module].append((op.name, src))
        used_by_module[op.module].update(used)

    files: dict[str, str] = {}
    for module in MODULES:
        ops_src = [src for _, src in sorted(by_module[module], key=lambda t: t[0])]
        header = _module_header(module, used_by_module[module])
        body = "\n\n\n".join(ops_src)
        files[f"_generated_{module}.py"] = header + "\n\n\n" + body + "\n"
    return files


def write_tree(files: dict[str, str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, source in files.items():
        # A locale-default encoding truncates the module mid-write on Windows;
        # newline pins the emitted bytes identical across platforms.
        (out_dir / filename).write_text(source, encoding="utf-8", newline="\n")


def main() -> None:
    spec = load_spec()
    files = emit_tree(spec)
    write_tree(files, _TOOLS_DIR)
    total = sum(len(f.split("\n@_op(")) - 1 for f in files.values())
    print(f"generated {len(files)} modules, {total} ops -> {_TOOLS_DIR}")
    for filename in sorted(files):
        count = len(files[filename].split("\n@_op(")) - 1
        print(f"  {filename}: {count} ops")
    print(f"overrides not emitted (hand-written in tools/overrides.py): {sorted(OVERRIDES)}")


if __name__ == "__main__":
    main()
