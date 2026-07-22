"""Help rendering for platform ops across the four groups (Step 8).

Signatures, Field bullets, the narrowed version_status Literal, and the two loud
docstring bodies the plan mandates (create_eval_run inference cost,
cloudzero_export external-SaaS push).
"""

from __future__ import annotations

from litellm_mcp import server


def _help(group: str, search: str | None = None) -> str:
    return server._build_help(group, search=search)


# --- read -------------------------------------------------------------------

def test_read_platform_signatures_and_bullets():
    h = _help("litellm_read")
    assert "ListPolicies(" in h
    assert "Filter by version status: draft, published, or production." in h
    assert "ListAgents(" in h
    assert "CloudzeroDryRun(" in h
    assert "Read-only" in h  # dry-run previews the export, sends nothing
    assert "ResolvePolicies(" in h


def test_read_cloudzero_operation_values_documented():
    h = _help("litellm_read")
    assert "replace_hourly" in h  # operation values surfaced to the caller


# --- write ------------------------------------------------------------------

def test_write_platform_signatures():
    h = _help("litellm_write")
    assert "CreatePolicy(" in h
    assert "CreatePolicyAttachment(" in h
    assert "CreateAgent(" in h
    assert "CreateWorkflowRun(" in h


def test_version_status_literal_in_write_help():
    h = _help("litellm_write")
    assert "UpdatePolicyVersionStatus(" in h
    assert "Literal['published', 'production']" in h  # narrowed enum is visible


def test_eval_overrides_render_in_write_help():
    """The three hand-written eval overrides render like generated write ops."""
    h = _help("litellm_write")
    assert "CreateEval(" in h
    assert "UpdateEval(" in h
    assert "CreateEvalRun(" in h
    assert "CONSUMES MODEL INFERENCE" in h  # loud cost body (mandated)


# --- execute ----------------------------------------------------------------

def test_execute_platform_and_cloudzero_export_push_body():
    h = _help("litellm_execute")
    assert "TestPolicyPipeline(" in h
    assert "CancelEval(" in h
    assert "CloudzeroExport(" in h
    assert "external SaaS" in h  # loud external-push body (mandated)
    assert "leaves your infrastructure" in h


# --- delete -----------------------------------------------------------------

def test_delete_platform_irreversible_heads():
    h = _help("litellm_delete")
    assert "DeletePolicy(" in h
    assert "irreversible" in h
    assert "DeleteEval(" in h
    assert "DeleteCloudzeroSettings()" in h


# --- search + sentinel hygiene ----------------------------------------------

def test_search_matches_within_platform():
    h = _help("litellm_write", search="cloudzero")
    assert "InitCloudzero(" in h
    assert "CreatePolicy(" not in h


def test_unset_never_leaks_into_platform_help():
    for group in ("litellm_read", "litellm_write", "litellm_execute", "litellm_delete"):
        h = _help(group)
        assert "_Unset" not in h
        assert "_UNSET" not in h
