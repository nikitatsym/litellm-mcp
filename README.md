# litellm-mcp

MCP server for the [LiteLLM](https://github.com/BerriAI/litellm) proxy. It
is a **development-and-operations** surface for LiteLLM resources - creating,
configuring, testing, invoking, observing, and cleaning up virtual keys,
teams, users, orgs, customers, budgets, models, credentials, tags,
guardrails, spend/usage, cache, health, proxy settings, the MCP gateway
registry (backend servers, toolsets, access groups), prompts, and the
platform areas (policies, evals, A2A agent registry, workflow runs,
CloudZero export) - as risk-graded meta-tools an agent can drive.

Bulk inference and the OpenAI-compatible surface (chat/completions,
embeddings, files, batches, assistants, vector stores, provider
pass-throughs) stay out of scope: agents already have model access through
their LLM client. What comes in is one-shot, dev-loop invocation that
closes a loop through the MCP alone - `test_prompt` renders and runs a
dotprompt, `invoke_agent` sends an A2A `message/send`. Both are graded as
`litellm_execute` (they spend inference) and return bounded output, never a
raw stream.

Built on the v2.5 MCP server family: five meta-tools dispatched by
`operation` + `params`, strict Pydantic validation, per-op `help` and JSON
`schema` introspection, list slimming with truncation metadata, and
write-response verification.

## Operations

**210 operations total**: 209 grouped across the five meta-tools, plus one
root `litellm_version` op. The count is machine-checked - it equals
`len(OPS)` in `codegen/inventory.py` (209) plus the hand-written root op,
and equals the summed `grep -c "^@_op" src/litellm_mcp/tools/*.py` (210).

| Meta-tool | Risk | Ops |
| --- | --- | ---: |
| `litellm_read` | safe | 94 |
| `litellm_write` | medium | 55 |
| `litellm_execute` | medium | 22 |
| `litellm_delete` | high | 26 |
| `litellm_admin` | high | 12 |

- **`litellm_read`** (safe): lists, infos, spend/usage, health, settings
  reads, token/cost utils, MCP gateway registry reads, prompt registry
  reads (list/get/versions), agent daily activity.
- **`litellm_write`** (medium): create/update for keys, teams, users,
  orgs, customers, budgets, models, credentials, tags, guardrails,
  fallbacks, MCP servers/toolsets, access groups, policies, evals, agents,
  workflows, and prompts (create/update/patch).
- **`litellm_execute`** (medium): block/unblock toggles, key
  regenerate/reset, connection tests, targeted cache delete, and one-shot
  dev-loop invocation (test a prompt, invoke an agent) with bounded output.
- **`litellm_delete`** (high): irreversible deletes and cache flushall.
- **`litellm_admin`** (high): proxy-global settings, allowed IPs, global
  spend reset, bulk user update.

Root: `litellm_version` returns `{"mcp": <package version>, "service": GET
/health/readiness}`. On LiteLLM v1.93.0 the readiness payload is
`{status, db}` (that image carries no LiteLLM version field).

## Install

```bash
uvx --refresh \
  --extra-index-url https://nikitatsym.github.io/litellm-mcp/simple \
  litellm-mcp
```

Add the following to your MCP client configuration (Claude Desktop, Cursor,
Claude Code, or any MCP-compatible client):

```json
{
  "mcpServers": {
    "litellm": {
      "command": "uvx",
      "args": [
        "--refresh",
        "--extra-index-url",
        "https://nikitatsym.github.io/litellm-mcp/simple",
        "litellm-mcp"
      ],
      "env": {
        "LITELLM_URL": "https://litellm.example.com",
        "LITELLM_API_KEY": "sk-your-admin-key"
      }
    }
  }
}
```

Or use the interactive
**[Setup Page](https://nikitatsym.github.io/litellm-mcp/)** to generate the
config.

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `LITELLM_URL` | Yes | Base URL of the LiteLLM proxy (no trailing slash) |
| `LITELLM_API_KEY` | Yes | Admin bearer key (master or admin virtual key) |

Both are read lazily: the server imports and lists ops without them, and
fails on the first call that reaches the proxy. `LITELLM_API_KEY` is sent
as `Authorization: Bearer`.

## Minting an admin key

This MCP drives the proxy administration surface, so it needs an
admin-scoped key, not a plain inference key. The master key works, but a
dedicated virtual key with the `proxy_admin` role is easier to rotate and
scope.

- **Admin UI**: Virtual Keys -> Create New Key, assign the `proxy_admin`
  role (or a role carrying admin permissions), and copy the key (shown
  once).
- **API**, calling with the master key:

```bash
curl -X POST "$LITELLM_URL/key/generate" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_role": "proxy_admin", "key_alias": "mcp-admin"}'
```

## Using the tools

Each meta-tool takes `operation` (a PascalCase op name, or `help` /
`schema`) plus `params` (a dict):

```text
litellm_read(operation="help")
litellm_read(operation="help", params={"search": "spend"})
litellm_read(operation="schema", params={"op": "ListKeys"})
litellm_read(operation="ListKeys", params={"team_id": "..."})

litellm_write(operation="GenerateKey", params={"team_id": "..."})
litellm_execute(operation="BlockKey", params={"key": "sk-..."})
litellm_delete(operation="DeleteKeys", params={"keys": ["sk-..."]})
```

`operation="help"` lists the group's ops; add `params={"search": "foo"}`
to filter by substring across names and docstrings (it also hints at
matches in other groups). `operation="schema"` returns one op's full JSON
Schema. Params are validated strictly via Pydantic: unknown keys, wrong
types, and missing required fields all surface as a `ValueError` with
field-level detail pointing at `operation='schema'`.

### v2.5 dispatch model

- **`operation='help'`** renders every op's signature with typed params and
  a description bullet per field; the `search` param filters the listing.
- **`operation='schema'`** returns the full JSON Schema for one op
  (`additionalProperties: false`, descriptions embedded).
- **Omitted-vs-null.** Optional body params default to an internal `_UNSET`
  sentinel. Omitting a param drops it from the request; passing an explicit
  `null` survives to the wire as JSON `null` - so a caller can clear a
  nullable field distinctly from leaving it untouched.
- **List slimming.** List ops return a slimmed row projection plus
  truncation metadata (`{"total", "returned", "truncated"}`), and
  secret-bearing fields (credentials, static headers, env vars) are dropped
  from list output. This keeps large responses within an agent's context
  budget.
- **Write verification.** Create/update ops presence-check that the fields
  they sent are echoed in the stored row the proxy returns; a silently
  dropped field raises with the full dotted path, so a partial write cannot
  pass unnoticed.

## Upstream feature gating

Some endpoints depend on the LiteLLM edition or on extra provider config.
Observed on the OSS `ghcr.io/berriai/litellm:v1.93.0` image; the MCP does
not special-case them - the upstream error propagates verbatim as an
`APIError` with the body intact.

Enterprise-licensed (fail on the OSS image without `LITELLM_LICENSE`):

- `GlobalSpendReport` (`GET /global/spend/report`) - 400, "You must be a
  LiteLLM Enterprise user".
- `RegenerateKey` (`POST /key/regenerate`) - 500, "Regenerating Virtual
  Keys is an Enterprise feature".

Present but needs external provider credentials:

- `evals` (`CreateEval` / `CreateEvalRun` and the run/get/delete family) -
  the create body is accepted, then the run fails 500 "OPENAI_API_KEY is
  required for Evals API". Unusable without a real provider key on the
  proxy.

Working end to end on OSS (exercised by the integration smokes): keys,
teams, users, budgets, models, tags, spend logs, the MCP gateway (servers,
health, access groups), policies (create/attach/resolve/delete), A2A
agents, workflow runs, and CloudZero settings.

## Development

Requires [uv](https://docs.astral.sh/uv/). Enable the pre-commit hook once
per clone (it runs the full gate on every commit):

```bash
git config core.hooksPath .githooks
```

`dev.py` is the task entry point:

```bash
uv run python dev.py check   # lint + mypy + codegen sync + tackbox + tests
uv run python dev.py lint    # ruff + mypy + codegen sync gate + tackbox
uv run python dev.py test    # unit tests only (no docker)
uv run python dev.py e2e     # integration smokes (needs the stack up)
```

Integration tests run against an ephemeral LiteLLM + Postgres stack. The
npm scripts wrap the compose lifecycle:

```bash
npm run litellm:up      # compose up -d --wait (first run pulls + migrates)
uv run python dev.py e2e
npm run litellm:down    # tear down + remove volumes
npm run litellm:logs    # follow container logs
```

### Codegen

The tool surface is generated, not hand-transcribed.
`codegen/inventory.py` fixes the operation list; the judgment layer (param
descriptions, docstring bodies, slim specs, verify skip sets, override
list) lives as plain data in `codegen/annotations.py`, `slims.py`,
`verify.py`, `overrides.py`, and `bodyless_ok.py`. `codegen/generate.py` is
a pure function of the committed OpenAPI snapshot
(`codegen/openapi-v1.93.0.json`) plus that data, emitting the
`src/litellm_mcp/tools/_generated_*.py` modules. Generated files are never
hand-edited; ops that need bespoke logic are listed in
`codegen/overrides.py` and implemented by hand in `tools/overrides.py`.

The sync gate (`uv run python -m codegen.check`, part of `dev.py lint`)
regenerates into a temp dir and fails unless the result is byte-identical
to the committed tree - so a hand-edit of a generated file, a stale data
key, or a drifted snapshot all fail the build. To change the surface: edit
the data (or the snapshot), regenerate, and commit the diff.

## License

MIT - see [LICENSE](LICENSE).
