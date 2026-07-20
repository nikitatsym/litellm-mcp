"""Per-op annotation data (authored in Steps 5-8; EMPTY in Step 4).

Each entry is keyed by op name; an unknown key is a generation-time error.
Supported per-op fields (all optional), consumed by `generate.py`:

    ANNOTATIONS[op_name] = {
        "doc":    "docstring head override (else the spec summary)",
        "body":   "extra docstring body lines (rendered under the signature)",
        "params": {param_name: "Field(description=...) text"},
        "types":  {param_name: "type expression that NARROWS the generated type"},
    }

The Step-4 type mapping is total with EMPTY annotations, so `types` only ever
narrows or documents; it is never required for generation to succeed.
"""

from __future__ import annotations

from typing import Any

ANNOTATIONS: dict[str, dict[str, Any]] = {}
