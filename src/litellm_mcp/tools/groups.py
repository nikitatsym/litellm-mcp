from ..registry import Group

litellm_read = Group(
    "litellm_read",
    "Query LiteLLM proxy data (safe, read-only): lists, infos, spend/usage, "
    "health, settings reads, token/cost utils, MCP gateway registry reads.\n\n"
    "Call with operation=\"$help\" to list all available read operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: litellm_read(operation=\"$ListKeys\")",
)

litellm_write = Group(
    "litellm_write",
    "Create or update LiteLLM resources (non-destructive): keys, teams, users, "
    "orgs, customers, budgets, models, credentials, tags, guardrails, fallbacks, "
    "MCP servers/toolsets, access groups.\n\n"
    "Call with operation=\"$help\" to list all available write operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: litellm_write(operation=\"$GenerateKey\", params={\"team_id\": \"...\"})",
)

litellm_execute = Group(
    "litellm_execute",
    "Execute reversible actions on LiteLLM resources: block/unblock toggles, key "
    "regenerate/reset, connection tests, targeted cache delete.\n\n"
    "Call with operation=\"$help\" to list all available execute operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: litellm_execute(operation=\"$BlockKey\", params={\"key\": \"sk-...\"})",
)

litellm_delete = Group(
    "litellm_delete",
    "Delete LiteLLM resources (destructive, irreversible), including cache "
    "flushall.\n\n"
    "Call with operation=\"$help\" to list all available delete operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: litellm_delete(operation=\"$DeleteKeys\", params={\"keys\": [\"sk-...\"]})",
)

litellm_admin = Group(
    "litellm_admin",
    "Proxy-global LiteLLM administration (high risk): proxy-global settings, "
    "allowed IPs, global spend reset, bulk user update.\n\n"
    "Call with operation=\"$help\" to list all available admin operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: litellm_admin(operation=\"$AddAllowedIp\", params={\"ip\": \"1.2.3.4\"})",
)
