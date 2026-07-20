"""Help rendering for the read groups (Step 5).

Signatures, Field-description bullets, pagination params, POST-but-read ops,
and docstring-body search all render through `_build_help('litellm_read')`.
"""

from __future__ import annotations

from litellm_mcp import server


def _help(search: str | None = None) -> str:
    return server._build_help("litellm_read", search=search)


def test_representative_signatures_present():
    h = _help()
    assert "ListKeys(" in h
    assert "KeyInfo(key?: str | None" in h
    assert "ModelInfo(" in h
    assert "ListMcpServers(team_id?: str | None" in h


def test_field_description_bullets_render():
    h = _help()
    assert "start_date: Start of the window, YYYY-MM-DD." in h
    assert "return_full_object: true returns full key objects" in h
    # injected client-side truncation control shows on slimmed list ops
    assert "limit: Max rows kept after client-side slimming" in h


def test_pagination_params_visible():
    """Spec pagination passes through untouched next to the injected limit."""
    h = _help()
    assert "page?: int" in h
    assert "page_size?: int" in h
    assert "limit: int = 20" in h


def test_post_but_read_ops_present():
    h = _help()
    for name in (
        "KeyHealth(",
        "BudgetInfo(",
        "TagInfo(",
        "CalculateSpend(",
        "CostEstimate(",
        "TokenCounter(",
    ):
        assert name in h, name


def test_override_health_timeout_bullet():
    h = _help()
    assert "Health(" in h
    assert "timeout: float = 120.0" in h
    assert "timeout: Per-call HTTP timeout in seconds" in h


def test_search_matches_docstring_body_not_just_name():
    # 'bearer' appears only in the KeyHealth docstring body, no op name.
    h = _help(search="bearer")
    assert "KeyHealth(" in h
    assert "ListKeys(" not in h


def test_camelcase_spec_params_kept():
    """model_info exposes upstream camelCase pagination/sort params verbatim."""
    h = _help()
    assert "modelId?: str | None" in h
    assert "sortOrder?: str | None" in h
