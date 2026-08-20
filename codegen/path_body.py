"""Exact dispositions for body fields that share a URL path placeholder.

Each collision is either serialized from the sole path argument or explicitly
exempted by documented service behavior. The generator and conformance guard
both stale-check this table against the committed OpenAPI snapshot.
"""

from __future__ import annotations

PATH_BODY_FIELD_DISPOSITIONS: dict[tuple[str, str], dict[str, str]] = {
    ("update_credential", "credential_name"): {
        "action": "serialize",
        "reason": "CredentialItem requires credential_name in the JSON body as well as the URL.",
    },
    ("update_prompt", "prompt_id"): {
        "action": "serialize",
        "reason": "The update_prompt override already copies prompt_id into its required JSON body.",
    },
}
