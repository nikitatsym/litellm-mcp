"""Hand-written ops, outside the generated inventory.

Step 3 seeds only the ROOT `litellm_version`; the read/write/execute/eval
overrides listed in `codegen/overrides.py` land in Steps 5-8.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

from ..registry import ROOT, _op
from .helpers import _get_client


@_op(ROOT)
def litellm_version() -> dict[str, Any]:
    """Get the MCP server version and the LiteLLM service readiness.

    `mcp` is this package's version. `service` is GET /health/readiness,
    which carries the running LiteLLM version and database status.
    """
    return {
        "mcp": importlib.metadata.version("litellm-mcp"),
        "service": _get_client().get("/health/readiness"),
    }
