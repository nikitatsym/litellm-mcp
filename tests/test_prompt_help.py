"""Help rendering for the prompt ops + agent_daily_activity (Step 2).

Signatures, Field bullets, the two loud docstring bodies (get_prompt sensitivity,
update_prompt PUT-creates-a-new-version), and search hits over the docstrings.
"""

from __future__ import annotations

from litellm_mcp import server


def _help(group: str, search: str | None = None) -> str:
    return server._build_help(group, search=search)


# --- read -------------------------------------------------------------------

def test_read_prompt_signatures_and_bullets():
    h = _help("litellm_read")
    assert "ListPrompts(" in h
    assert "GetPrompt(" in h
    assert "ListPromptVersions(" in h
    # environment query bullet is surfaced to the caller
    assert "Environment to scope to" in h
    # get_prompt names its response as secret-bearing (mandated loud body)
    assert "sensitive" in h


def test_agent_daily_activity_in_read_help():
    h = _help("litellm_read")
    assert "AgentDailyActivity(" in h
    assert "Comma-separated agent IDs to exclude." in h


# --- write ------------------------------------------------------------------

def test_write_prompt_signatures():
    h = _help("litellm_write")
    assert "CreatePrompt(" in h
    assert "UpdatePrompt(" in h
    assert "PatchPrompt(" in h
    # create_prompt documents the inline-vs-external registry split
    assert "EXTERNAL" in h
    # litellm_params bullet reaches the caller
    assert "dotprompt_content" in h


def test_update_prompt_version_semantics_in_help():
    """The update_prompt override pins PUT-creates-a-new-version, not in-place."""
    h = _help("litellm_write")
    assert "UpdatePrompt(" in h
    assert "NEW version" in h


# --- delete -----------------------------------------------------------------

def test_delete_prompt_head():
    h = _help("litellm_delete")
    assert "DeletePrompt(" in h
    assert "irreversible" in h


# --- search + sentinel hygiene ----------------------------------------------

def test_search_matches_prompt_ops():
    h = _help("litellm_write", search="prompt")
    assert "CreatePrompt(" in h
    assert "GenerateKey(" not in h


def test_unset_never_leaks_into_prompt_help():
    for group in ("litellm_read", "litellm_write", "litellm_delete"):
        h = _help(group)
        assert "_Unset" not in h
        assert "_UNSET" not in h
