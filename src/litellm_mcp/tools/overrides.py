"""Hand-written ops, outside the generated inventory.

ROOT `litellm_version` plus the ops listed in `codegen/overrides.py` that need
bespoke logic the emitter cannot express. Every non-ROOT op here MUST be listed
in `codegen/overrides.py` (else the generator would also emit it - the reverse
dedupe gate catches that). Overrides follow the same rules generated ops get:
`_UNSET` semantics, `Annotated[..., Field(description=...)]`, slims where they
apply. The write/execute/eval overrides land in Steps 6-8.
"""

from __future__ import annotations

import importlib.metadata
import json
import uuid
from typing import Annotated, Any, cast

from pydantic import Field

from ..registry import ROOT, _UNSET, _op
from .groups import litellm_execute, litellm_read, litellm_write
from .helpers import _get_client, _qp, _verify_response

# Shared execute-output caps: accumulated SSE text (test_prompt) / any single
# string in a bounded A2A result (invoke_agent); kept A2A Task history entries;
# and the whole-result serialization backstop.
_EXEC_TEXT_CAP = 20_000
_EXEC_HISTORY_KEEP = 5
_EXEC_RESULT_CAP = 100_000


@_op(ROOT)
def litellm_version() -> dict[str, Any]:
    """Get the MCP server version and the LiteLLM service readiness.

    `mcp` is this package's version (importlib metadata). `service` is
    GET /health/readiness, reporting the proxy's status and database
    connectivity - on LiteLLM v1.93.0 that payload is {status, db}, with no
    LiteLLM version field.
    """
    return {
        "mcp": importlib.metadata.version("litellm-mcp"),
        "service": _get_client().get("/health/readiness"),
    }


@_op(litellm_read)
def key_health(
    key: Annotated[
        str, Field(description="Virtual key to probe; sent as the bearer for this one call.")
    ],
) -> Any:
    """Check a virtual key's health by using it as the bearer for this call.

    Upstream POST /key/health probes the CALLING key and takes no body, so the
    given key is sent as the Authorization bearer for this one call only; every
    other call still uses the server-configured admin key.
    """
    return _get_client().post("/key/health", auth=key)


@_op(litellm_read)
def health(
    model: Annotated[
        str | None, Field(description="Probe only this public model name; omit to probe all.")
    ] = cast(str | None, _UNSET),
    model_id: Annotated[
        str | None, Field(description="Probe only this deployment ID.")
    ] = cast(str | None, _UNSET),
    timeout: Annotated[
        float,
        Field(description="Per-call HTTP timeout in seconds; the probe reaches every deployment and can be slow."),
    ] = 120.0,
) -> Any:
    """Probe configured model deployments and report each healthy or unhealthy.

    This is the one slow management call (it reaches out to every deployment),
    so `timeout` defaults to 120s and is routed to httpx for this call only.
    """
    return _get_client().get(
        "/health", params=_qp(model=model, model_id=model_id), timeout=timeout
    )


@_op(litellm_read)
def model_cost_map(
    filter: Annotated[
        str | None,
        Field(description="Case-insensitive substring; keep only model names containing it."),
    ] = cast(str | None, _UNSET),
    limit: Annotated[
        int, Field(description="Max models returned after filtering.")
    ] = 20,
) -> Any:
    """Look up per-model pricing and context limits from the LiteLLM cost map.

    The upstream map covers thousands of models; this returns a filtered,
    truncated slice keyed by model name, with counts so the caller cannot miss
    that data was cut. Pass `filter` to narrow by model-name substring.
    """
    cost_map = _get_client().get("/public/litellm_model_cost_map")
    if filter:
        needle = filter.lower()
        cost_map = {k: v for k, v in cost_map.items() if needle in k.lower()}
    total = len(cost_map)
    kept = dict(list(cost_map.items())[:limit]) if limit > 0 else cost_map
    return {
        "data": kept,
        "total": total,
        "returned": len(kept),
        "truncated": total > len(kept),
    }


@_op(litellm_write)
def update_organization(
    organization_id: Annotated[
        str, Field(description="ID of the organization to update (addressing field).")
    ],
    organization_alias: Annotated[
        str | None, Field(description="Human-readable organization name.")
    ] = cast(str | None, _UNSET),
    budget_id: Annotated[
        str | None, Field(description="ID of the budget object governing this org.")
    ] = cast(str | None, _UNSET),
    metadata: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
    models: Annotated[
        list[str] | None, Field(description="Model names this org may access.")
    ] = cast(list[str] | None, _UNSET),
    max_budget: Annotated[
        float | None, Field(description="Hard USD budget cap for the org.")
    ] = cast(float | None, _UNSET),
    soft_budget: Annotated[
        float | None, Field(description="USD spend that triggers an alert (no block).")
    ] = cast(float | None, _UNSET),
    tpm_limit: Annotated[
        int | None, Field(description="Org-wide tokens-per-minute cap.")
    ] = cast(int | None, _UNSET),
    rpm_limit: Annotated[
        int | None, Field(description="Org-wide requests-per-minute cap.")
    ] = cast(int | None, _UNSET),
    max_parallel_requests: int | None = cast(int | None, _UNSET),
    budget_duration: Annotated[
        str | None, Field(description="Budget reset window, e.g. '30d', '1mo'.")
    ] = cast(str | None, _UNSET),
    model_max_budget: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
    updated_by: str | None = cast(str | None, _UNSET),
) -> Any:
    """Update an existing organization's settings.

    Spec-gap override: PATCH /organization/update carries no requestBody in the
    snapshot, so the fields here follow the LiteLLM organization-update model.
    Only the fields you pass are changed; `organization_id` addresses the org
    and is required. Field names verified live in Step 9.
    """
    body: dict[str, Any] = {}
    if organization_id is not _UNSET:
        body["organization_id"] = organization_id
    if organization_alias is not _UNSET:
        body["organization_alias"] = organization_alias
    if budget_id is not _UNSET:
        body["budget_id"] = budget_id
    if metadata is not _UNSET:
        body["metadata"] = metadata
    if models is not _UNSET:
        body["models"] = models
    if max_budget is not _UNSET:
        body["max_budget"] = max_budget
    if soft_budget is not _UNSET:
        body["soft_budget"] = soft_budget
    if tpm_limit is not _UNSET:
        body["tpm_limit"] = tpm_limit
    if rpm_limit is not _UNSET:
        body["rpm_limit"] = rpm_limit
    if max_parallel_requests is not _UNSET:
        body["max_parallel_requests"] = max_parallel_requests
    if budget_duration is not _UNSET:
        body["budget_duration"] = budget_duration
    if model_max_budget is not _UNSET:
        body["model_max_budget"] = model_max_budget
    if updated_by is not _UNSET:
        body["updated_by"] = updated_by
    result = _get_client().patch("/organization/update", json=body)
    # LiteLLM_OrganizationTableWithMembers echoes these row fields; budget/limit
    # knobs land in the budget table, so verify only the org-row scalars/list.
    _verify_response(
        {k: body[k] for k in ("organization_id", "organization_alias", "models") if k in body},
        result,
    )
    return result


@_op(litellm_execute)
def cache_delete(
    keys: Annotated[
        list[str],
        Field(
            description="Cache keys to delete; must be non-empty. Removes only "
            "these keys - cache_flushall (delete group) wipes the whole cache."
        ),
    ],
) -> Any:
    """Delete specific keys from the proxy cache.

    Spec-gap override: POST /cache/delete carries no requestBody in the snapshot,
    so `keys` is defined here. It is required and must be non-empty; the empty-list
    rejection fires BEFORE any HTTP call. This deletes only the named keys -
    cache_flushall (delete group) is the separate wipe-everything op. The 200 is a
    status envelope, so there is no write echo to verify.
    """
    if not keys:
        raise ValueError("cache_delete requires a non-empty 'keys' list")
    return _get_client().post("/cache/delete", json={"keys": keys})


# --- eval writes (spec-gap: endpoints carry no requestBody in the snapshot) ---
# Bodies follow the OpenAI Evals API that LiteLLM implements. The response echoes
# the eval/run object; `name` is the one scalar we reliably send-and-echo, so it
# is the verify anchor. data_source_config / testing_criteria / data_source are
# normalized server-side, so they are not deep-checked. Field sets confirmed live
# in Step 9 (same as update_organization). The shared POST+verify tail lives in
# `_post_eval` (extracting it keeps the three bodies DUP-free).

def _post_eval(path: str, body: dict[str, Any]) -> Any:
    result = _get_client().post(path, json=body)
    _verify_response({k: body[k] for k in ("name",) if k in body}, result)
    return result


@_op(litellm_write)
def create_eval(
    data_source_config: Annotated[
        dict[str, Any],
        Field(description="Schema of the data the eval runs against (OpenAI data_source_config)."),
    ],
    testing_criteria: Annotated[
        list[dict[str, Any]],
        Field(description="Graders that score each sample (OpenAI testing_criteria)."),
    ],
    name: Annotated[str | None, Field(description="Human-readable eval name.")] = cast(
        str | None, _UNSET
    ),
    metadata: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
) -> Any:
    """Create an eval (OpenAI-Evals-compatible).

    Spec-gap override: POST /v1/evals carries no requestBody in the snapshot, so
    the body here follows the OpenAI Evals create shape LiteLLM implements:
    `data_source_config` (what data to score) and `testing_criteria` (how to
    grade) are required; `name` and `metadata` are optional. Creating an eval is
    just a definition - it consumes no inference until you start a run.
    """
    body: dict[str, Any] = {}
    if data_source_config is not _UNSET:
        body["data_source_config"] = data_source_config
    if testing_criteria is not _UNSET:
        body["testing_criteria"] = testing_criteria
    if name is not _UNSET:
        body["name"] = name
    if metadata is not _UNSET:
        body["metadata"] = metadata
    return _post_eval("/v1/evals", body)


@_op(litellm_write)
def update_eval(
    eval_id: Annotated[str, Field(description="ID of the eval to update.")],
    name: Annotated[str | None, Field(description="New eval name.")] = cast(str | None, _UNSET),
    metadata: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
) -> Any:
    """Update an eval's name or metadata (partial update).

    Spec-gap override: POST /v1/evals/{eval_id} carries no requestBody in the
    snapshot. The OpenAI Evals update path only changes `name` and `metadata`;
    the data source and grading criteria are fixed at creation. Only the fields
    you pass are changed.
    """
    body: dict[str, Any] = {}
    if name is not _UNSET:
        body["name"] = name
    if metadata is not _UNSET:
        body["metadata"] = metadata
    return _post_eval(f"/v1/evals/{eval_id}", body)


@_op(litellm_write)
def create_eval_run(
    eval_id: Annotated[str, Field(description="ID of the eval to run.")],
    data_source: Annotated[
        dict[str, Any],
        Field(description="Where the run pulls samples from (OpenAI data_source)."),
    ],
    name: Annotated[str | None, Field(description="Human-readable run name.")] = cast(
        str | None, _UNSET
    ),
    metadata: dict[str, Any] | None = cast(dict[str, Any] | None, _UNSET),
) -> Any:
    """Start an eval run - THIS CONSUMES MODEL INFERENCE (real cost).

    Spec-gap override: POST /v1/evals/{eval_id}/runs carries no requestBody in the
    snapshot, so the body follows the OpenAI Evals create-run shape: `data_source`
    is required; `name` and `metadata` are optional. A run executes the eval's
    testing criteria over the data source, calling the configured model for every
    sample - it bills real tokens and can be slow. Use get_eval_run to poll status.
    """
    body: dict[str, Any] = {}
    if data_source is not _UNSET:
        body["data_source"] = data_source
    if name is not _UNSET:
        body["name"] = name
    if metadata is not _UNSET:
        body["metadata"] = metadata
    return _post_eval(f"/v1/evals/{eval_id}/runs", body)


@_op(litellm_write)
def update_prompt(
    prompt_id: Annotated[
        str,
        Field(
            description="Prompt to update (path id). PUT creates a NEW version keyed "
            "by this id; the body id is forced to match, never a rename."
        ),
    ],
    litellm_params: Annotated[
        dict[str, Any],
        Field(
            description="Prompt provider config (PromptLiteLLMParams) as a dict: "
            "prompt_integration (registry kind, required), dotprompt_content (inline "
            "template text), api_base/api_key for an external registry."
        ),
    ],
    prompt_info: Annotated[
        dict[str, Any] | None,
        Field(
            description="Prompt metadata (PromptInfo) as a dict; its 'environment' "
            "selects the new version's environment (default 'development')."
        ),
    ] = cast(dict[str, Any] | None, _UNSET),
) -> Any:
    """Update a prompt: PUT creates a NEW version (not an in-place edit).

    Generator quirk (Decision 11): the snapshot's Prompt body requires prompt_id
    in BOTH the path and the body, but the generator drops the body field that
    collides with a path param ("path wins"), so a generated op would 422.
    Upstream ignores the body id anyway - the new row is keyed by the PATH id
    (version suffix stripped), there is no rename. So this override exposes ONE
    prompt_id and duplicates it into the body wire-side.

    PUT does not edit in place: it appends a new version of the prompt, keyed by
    prompt_id, with the environment taken from prompt_info.environment (default
    'development'). This is the version arrow of the prompt loop.
    """
    body: dict[str, Any] = {"prompt_id": prompt_id, "litellm_params": litellm_params}
    if prompt_info is not _UNSET:
        body["prompt_info"] = prompt_info
    result = _get_client().put(f"/prompts/{prompt_id}", json=body)
    # live (Step 4): PUT echoes the new version's stored row with prompt_id at root
    # (suffixed with the version); presence-only, so the suffix is irrelevant.
    _verify_response({"prompt_id": prompt_id}, result)
    return result


@_op(litellm_execute)
def test_prompt(
    dotprompt_content: Annotated[
        str,
        Field(
            description="Dotprompt template WITH frontmatter. The frontmatter's "
            "'model:' selects which model runs (a 400 if it names none); the body is "
            "the prompt template, rendered with prompt_variables."
        ),
    ],
    prompt_variables: Annotated[
        dict[str, Any] | None,
        Field(description="Values substituted into the dotprompt template placeholders."),
    ] = cast(dict[str, Any] | None, _UNSET),
    conversation_history: Annotated[
        list[dict[str, str]] | None,
        Field(description="Prior chat turns (each a {role, content} dict) prepended before the rendered prompt."),
    ] = cast(list[dict[str, str]] | None, _UNSET),
) -> dict[str, Any]:
    """Render a dotprompt and RUN it through the model - THIS SPENDS INFERENCE.

    Upstream parses the dotprompt frontmatter (the 'model:' there picks the
    model - there is no model argument here), renders the template, then always
    streams an OpenAI-style chat completion (stream=True is forced upstream).
    This op collects that stream client-side into a fixed shape: {model, text,
    finish_reason, usage, truncated}. Accumulated text is capped at 20000 chars
    (truncated=true past the cap); a mid-stream error event raises, and a 2xx
    non-SSE response raises (both surface a broken upstream contract rather than
    a silent empty answer).
    """
    body: dict[str, Any] = {"dotprompt_content": dotprompt_content}
    if prompt_variables is not _UNSET:
        body["prompt_variables"] = prompt_variables
    if conversation_history is not _UNSET:
        body["conversation_history"] = conversation_history

    model: str | None = None
    text_parts: list[str] = []
    text_len = 0
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    truncated = False

    with _get_client().post_sse("/prompts/test", json=body) as events:
        for event in events:
            if "error" in event:
                raise ValueError(
                    f"test_prompt: upstream returned a streaming error event: {event['error']!r}"
                )
            if event.get("model"):
                model = event["model"]
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    text_parts.append(piece)
                    text_len += len(piece)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
            if text_len >= _EXEC_TEXT_CAP:
                truncated = True
                break  # cap-stop; the with-block closes the stream

    return {
        "model": model,
        "text": "".join(text_parts)[:_EXEC_TEXT_CAP],
        "finish_reason": finish_reason,
        "usage": usage,
        "truncated": truncated,
    }


def _bound_a2a(value: Any) -> tuple[Any, bool]:
    """Recursively bound an A2A result: (bounded_value, anything_cut).

    Generic walk over every dict/list/string (not a known-field allowlist): a
    dict's `bytes` (a FilePart/DataPart payload) is dropped for `bytes_omitted`
    (its byte count), other file fields kept; any string over _EXEC_TEXT_CAP is
    truncated; a `history` list is capped to the last _EXEC_HISTORY_KEEP entries
    with `history_omitted` recording the drop count.
    """
    if isinstance(value, dict):
        cut = False
        out: dict[str, Any] = {}
        if "bytes" in value:
            raw = value["bytes"]
            out["bytes_omitted"] = (
                len(raw) if isinstance(raw, (str, bytes, bytearray)) else len(json.dumps(raw))
            )
            cut = True
        for key, item in value.items():
            if key == "bytes":
                continue
            if key == "history" and isinstance(item, list):
                kept = item[-_EXEC_HISTORY_KEEP:]
                bounded_kept: list[Any] = []
                for entry in kept:
                    be, ecut = _bound_a2a(entry)
                    bounded_kept.append(be)
                    cut = cut or ecut
                out["history"] = bounded_kept
                dropped = len(item) - len(kept)
                if dropped > 0:
                    out["history_omitted"] = dropped
                    cut = True
                continue
            bi, icut = _bound_a2a(item)
            out[key] = bi
            cut = cut or icut
        return out, cut
    if isinstance(value, list):
        cut = False
        bounded_list: list[Any] = []
        for item in value:
            bi, icut = _bound_a2a(item)
            bounded_list.append(bi)
            cut = cut or icut
        return bounded_list, cut
    if isinstance(value, str) and len(value) > _EXEC_TEXT_CAP:
        return value[:_EXEC_TEXT_CAP], True
    return value, False


def _a2a_result_stub(result: Any) -> dict[str, Any]:
    """Structural summary for a result too big for the bounding rules to shrink."""
    kinds: set[str] = set()
    counts = {"parts": 0, "artifacts": 0, "history": 0}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("kind")
            if isinstance(kind, str):
                kinds.add(kind)
            for field_name in counts:
                seq = value.get(field_name)
                if isinstance(seq, list):
                    counts[field_name] += len(seq)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(result)
    return {
        "kinds": sorted(kinds),
        "parts_total": counts["parts"],
        "artifacts_total": counts["artifacts"],
        "history_len": counts["history"],
        "serialized_chars": len(json.dumps(result)),
    }


@_op(litellm_execute)
def invoke_agent(
    agent_id: Annotated[str, Field(description="Registered agent id to send the message to.")],
    text: Annotated[
        str | None,
        Field(description="Convenience: a plain user-text turn. Mutually exclusive with 'message'."),
    ] = cast(str | None, _UNSET),
    message: Annotated[
        dict[str, Any] | None,
        Field(
            description="Full A2A Message dict, forwarded verbatim (multi-part "
            "text/file/data, contextId/taskId for session continuity). Mutually "
            "exclusive with 'text'."
        ),
    ] = cast(dict[str, Any] | None, _UNSET),
    configuration: Annotated[
        dict[str, Any] | None,
        Field(description="A2A MessageSendConfiguration dict; blocking is forced true (see below)."),
    ] = cast(dict[str, Any] | None, _UNSET),
    metadata: Annotated[
        dict[str, Any] | None, Field(description="Arbitrary JSON-RPC params metadata, forwarded verbatim.")
    ] = cast(dict[str, Any] | None, _UNSET),
    guardrails: Annotated[
        list[str] | None,
        Field(
            description="Guardrail NAMES to run for this call, placed at the JSON-RPC "
            "params root and merged with the agent's own guardrails (test an agent with "
            "a guardrail in one call). A name matching no initialized guardrail is "
            "SILENTLY SKIPPED on this path (no error, unlike apply_guardrail's 404) - "
            "check a name with list_guardrails or apply_guardrail first."
        ),
    ] = cast(list[str] | None, _UNSET),
    message_id: Annotated[
        str | None,
        Field(
            description="messageId for the convenience 'text' form only (autofilled "
            "with a uuid4 if omitted). Rejected with 'message': put the messageId "
            "inside the message dict there."
        ),
    ] = cast(str | None, _UNSET),
    timeout: Annotated[
        float,
        Field(description="Per-call HTTP timeout in seconds; the agent behind the proxy may run its own LLM chain."),
    ] = 120.0,
) -> dict[str, Any]:
    """Invoke a registered A2A agent one-shot (message/send) - MAY SPEND INFERENCE.

    Spec-gap override: the endpoint's JSON-RPC body is invisible to the snapshot.
    The op owns the pinned JSON-RPC 2.0 envelope (method 'message/send', fresh
    uuid4 id) so the bounded non-streaming contract holds; a caller-supplied
    method could switch to message/stream or tasks/*. Pass exactly one of 'text'
    (convenience) or 'message' (full A2A Message). blocking is always forced true:
    a pending Task would strand this loop (tasks/* polling is out of scope). An
    upstream JSON-RPC error object raises even on HTTP 200. On success the agent
    may answer with a Message or a Task (its choice); the result is returned
    bounded ({result, truncated}): oversized file bytes, long strings, and long
    Task history are cut, with a structural stub as the backstop.

    Optional `guardrails` (names) run for this call, merged with the agent's own;
    a name matching no initialized guardrail is silently skipped here (unlike
    apply_guardrail, which 404s) - verify names with list_guardrails first.
    """
    has_text = text is not _UNSET
    has_message = message is not _UNSET
    if has_text == has_message:
        raise ValueError("invoke_agent requires exactly one of 'text' or 'message'")
    if has_message and message_id is not _UNSET:
        raise ValueError(
            "invoke_agent: message_id is text-form only; with the full 'message' form "
            "put the messageId inside the message dict"
        )

    config: dict[str, Any] = {}
    if configuration is not _UNSET and configuration is not None:
        config = dict(configuration)
    if config.get("blocking") is False:
        raise ValueError(
            "invoke_agent forces blocking=true (a pending Task with tasks/* polling out "
            "of scope would strand the loop); configuration.blocking=false is rejected"
        )
    config["blocking"] = True

    if has_text:
        mid = message_id if message_id is not _UNSET else str(uuid.uuid4())
        message_value: Any = {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": mid,
        }
    else:
        message_value = message

    params: dict[str, Any] = {"message": message_value, "configuration": config}
    if metadata is not _UNSET:
        params["metadata"] = metadata
    if guardrails is not _UNSET:
        params["guardrails"] = guardrails

    envelope = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }
    response = _get_client().post(
        f"/v1/a2a/{agent_id}/message/send", json=envelope, timeout=timeout
    )

    if isinstance(response, dict) and "error" in response:
        err = response["error"]
        code = err.get("code") if isinstance(err, dict) else None
        msg_text = err.get("message") if isinstance(err, dict) else err
        raise ValueError(f"invoke_agent: agent returned JSON-RPC error {code}: {msg_text}")
    if not isinstance(response, dict) or "result" not in response:
        raise ValueError(
            f"invoke_agent: JSON-RPC response has neither 'result' nor 'error': {response!r}"
        )

    result = response["result"]
    bounded, truncated = _bound_a2a(result)
    if len(json.dumps(bounded)) > _EXEC_RESULT_CAP:
        bounded = _a2a_result_stub(result)
        truncated = True
    return {"result": bounded, "truncated": truncated}


@_op(litellm_execute)
def apply_guardrail(
    guardrail_name: Annotated[
        str,
        Field(
            description="NAME of an initialized guardrail (as shown by list_guardrails), "
            "resolved against the callback registry - NOT a guardrail_id."
        ),
    ],
    text: Annotated[str, Field(description="Text to run the guardrail over.")],
    input_type: Annotated[
        str,
        Field(
            description="'request' (default) or 'response'; auto-upgraded to 'response' "
            "for post_call guardrails."
        ),
    ] = "request",
    messages: Annotated[
        list[dict[str, Any]] | None,
        Field(description="Optional chat context (role/content dicts) some guardrail types inspect."),
    ] = cast(list[dict[str, Any]] | None, _UNSET),
) -> Any:
    """Run a named guardrail over text and return the processed result - MAY SPEND MONEY.

    Provider-backed guardrail types (bedrock, lakera, presidio, llm_as_a_judge,
    ...) call their external service and spend money, and every call writes
    usage/spend traces; in-process types (litellm_content_filter) are free. The
    guardrail is resolved BY NAME against the initialized callback registry, so an
    unknown name 404s ("Guardrail '<name>' not found") - list_guardrails shows the
    valid names. `response_text` in the result is the processed text (the original
    text when the guardrail changes nothing). The v1.93.0 request schema also
    carries `language` and `entities`, but the handler never forwards them, so they
    are deliberately not exposed here.
    """
    body: dict[str, Any] = {
        "guardrail_name": guardrail_name,
        "text": text,
        "input_type": input_type,
    }
    if messages is not _UNSET:
        body["messages"] = messages
    return _get_client().post("/guardrails/apply_guardrail", json=body)
