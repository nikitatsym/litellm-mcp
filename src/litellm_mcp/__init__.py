"""LiteLLM MCP server package.

Importable surface for a host that serves several LiteLLM instances in one
process: the `mcp` server, `Settings`, `LiteLLMClient`, and `client_var`
(the per-request client binding every tool resolves through).
"""

from __future__ import annotations

from .client import LiteLLMClient
from .config import Settings
from .server import main, mcp
from .tools.helpers import client_var

__all__ = ["LiteLLMClient", "Settings", "client_var", "main", "mcp"]
