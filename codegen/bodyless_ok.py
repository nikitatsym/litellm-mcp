"""Closed allowlist of POST/PUT/PATCH ops whose empty body is genuine.

EXACTLY six on this surface. A body-mutating verb with no requestBody that is
NOT listed here (or in `overrides.py`) is a generation-time error; symmetrically
an entry here naming an op that HAS a requestBody is also a generation-time
error. NOT `reset_key_spend` (required `reset_to`) and NOT `test_cache_connection`
(required `cache_settings`): both have bodies and emit normally.
"""

from __future__ import annotations

BODYLESS_OK: dict[str, str] = {
    "disable_team_logging": "toggle endpoint; team_id is in the path, no body fields",
    "cache_flushall": "wipes the entire cache; takes no parameters",
    "reset_email_event_settings": "resets email event settings to defaults; no parameters",
    "global_spend_reset": "resets all spend counters; takes no parameters",
    "cancel_eval": "cancels the eval; eval_id is in the path, no body fields",
    "cancel_eval_run": "cancels the run; eval_id and run_id are in the path, no body fields",
}
