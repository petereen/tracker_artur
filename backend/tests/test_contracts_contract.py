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
    assert "/contract-archive" in routes
    assert "/contract-archive/review-queue" in routes
    assert "/contract-archive/entries" in routes
    assert "/contract-archive/entries/{entry_id}/download" in routes
    assert "/contract-archive/entries/{entry_id}/print" in routes
    assert "/contract-archive/entries/{entry_id}/review" in routes
    for state in ("DRAFT", "PENDING_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED", "SIGNED_AND_STAMPED"):
        assert state in source
    assert "ARCHIVE_MANAGER_ROLES = (\"admin\", \"legal_counsel\")" in source


def test_contract_archive_models_and_role_key_are_declared():
    models = (ROOT / "app" / "models" / "contracts.py").read_text()
    roles = (ROOT / "app" / "core" / "roles.py").read_text()
    migration = (ROOT / "alembic" / "versions" / "n1o2p3q4r5s6_contract_archive.py").read_text()
    for table in ("contract_archive_folders", "contract_archive_entries", "contract_archive_access"):
        assert table in models
        assert table in migration
    assert "legal_counsel" in roles
    assert "uq_contract_archive_entries_active_contract" in migration
    assert "ck_contract_archive_entries_storage_source" in migration
    assert "fk_contract_archive_folders_parent_org" in migration
    assert "uq_contract_archive_entries_active_folder_name" in migration
    assert "DELETE FROM role_assignments WHERE role = 'legal_counsel'" in migration
    assert "_archive_ensure_entry_name" in (ROOT / "app" / "routers" / "contracts.py").read_text()
    assert "manifest_path" in models or "manifest_path" in (ROOT / "app" / "routers" / "contracts.py").read_text()


def test_contract_migration_has_tenant_and_round_constraints():
    source = (ROOT / "alembic" / "versions" / "h1i2j3k4l5m6_contract_lifecycle.py").read_text()
    assert "contract_documents" in source
    assert "organization_id" in source
    assert "uq_contract_reviews_round_reviewer" in source
    assert "ck_contract_documents_effective_range" in source
    assert "ck_contract_files_purpose" in source
