"""LiteLLM tool package.

`server.py` walks this package with `pkgutil.walk_packages`, so every
submodule that defines `@_op` functions registers at discovery time.
Importing them here too keeps decorator registration eager and gives the
generated modules (Steps 4-8) a single place to be listed.
"""

from .groups import (  # noqa: F401
    litellm_admin,
    litellm_delete,
    litellm_execute,
    litellm_read,
    litellm_write,
)
from .helpers import _get_client, _qp, _truncate  # noqa: F401

# Tool modules (importing registers their @_op functions).
from . import (  # noqa: F401
    _generated_admin,
    _generated_delete,
    _generated_execute,
    _generated_platform,
    _generated_prompts,
    _generated_read_core,
    _generated_read_infra,
    _generated_write,
    overrides,
)
