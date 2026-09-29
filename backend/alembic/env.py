import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.MIGRATION_DATABASE_URL or settings.SYNC_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tenant keys added by migration b3c4d5e6f7a8 to legacy tables. They are
# maintained by the ``tenant_fill_organization_id`` trigger and enforced by
# row-level security, not mapped in the ORM — autogenerate must not drop them.
DB_MANAGED_TENANT_COLUMN_TABLES = frozenset({
    "work_reports", "work_time_entries", "work_report_revisions", "work_report_prompts", "report_comments",
    "survey_sessions", "answers", "schedules", "shift_schedules", "streaks", "employee_questions",
    "resource_allocations", "questions", "manager_settings", "unknown_assistant_requests", "assistant_context_examples",
})


def include_object(obj, name, type_, reflected, compare_to):
    table = getattr(obj, "table", None)
    table_name = getattr(table, "name", None)
    if table_name in DB_MANAGED_TENANT_COLUMN_TABLES and reflected and compare_to is None:
        if type_ == "column" and name == "organization_id":
            return False
        if type_ in {"index", "foreign_key_constraint"} and name and "organization" in name:
            return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            # Migrations are the system context: with ``app.rls_strict = on``
            # row-level security would otherwise hide every tenant row.
            connection.exec_driver_sql("SELECT set_config('app.system_context', 'on', true)")
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
