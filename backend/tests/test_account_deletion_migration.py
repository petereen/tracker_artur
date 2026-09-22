from pathlib import Path


def test_account_deletion_migration_preserves_contract_review_history():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "k6l7m8n9o0_allow_managed_account_deletion.py"
    source = migration.read_text()

    assert 'op.alter_column("contract_reviews", "reviewer_account_id", nullable=True)' in source
    assert 'ondelete="SET NULL"' in source
    assert 'ondelete="RESTRICT"' in source
