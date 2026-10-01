"""least-privilege database role for the OYUNS AI agent

Creates (or refreshes) the ``oyuns_ai`` role used through ``AI_DATABASE_URL``:
NOSUPERUSER NOBYPASSRLS, so row-level security physically confines every agent
query to the asking tenant (``ops/sql/oyuns_ai_role.sql`` is the manual
equivalent). The login password comes from the ``AI_DB_PASSWORD`` environment
variable and is never stored in the repository.

Never fatal: without the variable, without the CREATEROLE privilege, or when a
grant fails, the migration logs a notice and still advances — the agent then
falls back to ``DATABASE_URL`` exactly as before.

Revision ID: a9b8c7d6e5f4
Revises: e1f2a3b4c5d6
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "oyuns_ai"

GRANTS = """
DO $$
DECLARE owner_role text DEFAULT current_user;
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO oyuns_ai', current_database());
  GRANT USAGE ON SCHEMA public TO oyuns_ai;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO oyuns_ai;
  GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO oyuns_ai;
  GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO oyuns_ai;
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO oyuns_ai', owner_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO oyuns_ai', owner_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO oyuns_ai', owner_role);
END
$$;
"""


def _notice(message: str) -> None:
    print(f"[oyuns_ai role] {message}")


def upgrade() -> None:
    bind = op.get_bind()
    password = os.environ.get("AI_DB_PASSWORD", "")
    can_manage_roles = bind.execute(
        sa.text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
    ).scalar()
    exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}).scalar()

    if not exists and not password:
        _notice("AI_DB_PASSWORD is not set; skipped (agent keeps using DATABASE_URL).")
        return
    if not exists and not can_manage_roles:
        _notice("migration user cannot create roles; run ops/sql/oyuns_ai_role.sql as an admin.")
        return

    try:
        with bind.begin_nested():
            if not exists:
                bind.execute(sa.text(f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"))
            if can_manage_roles:
                if password:
                    literal = bind.execute(sa.text("SELECT quote_literal(:p)"), {"p": password}).scalar()
                    bind.execute(sa.text(f"ALTER ROLE {ROLE} WITH PASSWORD {literal}"))
                bind.execute(sa.text(f"ALTER ROLE {ROLE} NOSUPERUSER NOBYPASSRLS"))
                bind.execute(sa.text(f"ALTER ROLE {ROLE} SET app.rls_strict = 'on'"))
            bind.execute(sa.text(GRANTS))
    except Exception as exc:  # noqa: BLE001 - a role problem must not block the schema
        _notice(f"could not configure the role ({exc.__class__.__name__}); run ops/sql/oyuns_ai_role.sql manually.")


def downgrade() -> None:
    # The role may be in use by AI_DATABASE_URL; leave it in place.
    pass
