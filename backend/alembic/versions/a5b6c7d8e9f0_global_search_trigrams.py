"""add command search trigram indexes

Revision ID: a5b6c7d8e9f0
Revises: z4a5b6c7d8e9
"""

from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "z4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_title_trgm ON tasks USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_company_library_items_name_trgm ON company_library_items USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_employees_name_trgm ON employees USING gin (name gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_employees_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_company_library_items_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tasks_title_trgm")
