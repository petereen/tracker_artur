"""Contract lifecycle contract tests that do not require a live database.

The integration suite exercises persistence in the deployment environment; these
checks keep the public state machine and route surface from drifting locally.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _router_source() -> str:
    return (ROOT / "app" / "routers" / "contracts.py").read_text()


def test_contract_state_machine_and_public_routes_are_declared():
    source = _router_source()
    tree = ast.parse(source)
    routes = {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in {"get", "post", "patch", "delete"}
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
    }
    assert "/contracts" in routes
    assert "/contracts/{public_id}/submit" in routes
    assert "/contracts/{public_id}/resubmit" in routes
    assert "/contracts/{public_id}/recall" in routes
    assert "/contracts/{public_id}/approve" in routes
    assert "/contracts/{public_id}/request-changes" in routes
    assert "/contracts/{public_id}/reject" in routes
    assert "/contracts/{public_id}/confirm-final" in routes
    for state in ("DRAFT", "PENDING_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SIGNED_AND_STAMPED"):
        assert state in source


def test_contract_migration_has_tenant_and_round_constraints():
    source = (ROOT / "alembic" / "versions" / "h1i2j3k4l5m6_contract_lifecycle.py").read_text()
    assert "contract_documents" in source
    assert "organization_id" in source
    assert "uq_contract_reviews_round_reviewer" in source
    assert "ck_contract_documents_effective_range" in source
    assert "ck_contract_files_purpose" in source
