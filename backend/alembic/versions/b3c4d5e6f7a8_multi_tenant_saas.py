"""OYUNS ERP multi-tenant SaaS foundation

* ``organizations`` becomes the tenant table: slug, lifecycle status, primary
  flag, plan/billing cycle, seat limit, licensed features, license expiry,
  branding. The existing company becomes the primary tenant (all features,
  unlimited seats, no license required — grandfathered).
* New platform tables: ``subscription_plans`` (seeded Starter/Professional/
  Enterprise), ``platform_operators``, ``tenant_licenses``, ``tenant_domains``,
  ``platform_audit_logs``.
* Tenant key everywhere: NULL ``organization_id`` rows are backfilled, and
  legacy tables that had no tenant key get a DB-managed ``organization_id``
  (filled by the ``tenant_fill_organization_id`` trigger from the parent row,
  the request tenant or the primary tenant).
* Row-level security: every table with ``organization_id`` (and
  ``organizations`` by ``id``) gets ``ENABLE`` + ``FORCE ROW LEVEL SECURITY``
  and a ``tenant_isolation`` policy on ``tenant_row_visible()``. The app sets
  ``app.tenant_id`` per transaction; without it (system context) rows stay
  visible unless ``app.rls_strict = on``.
* ``enforce_tenant_seat_limit`` trigger on ``user_accounts``.

Revision ID: b3c4d5e6f7a8
Revises: a8b9c0d1e2f3
Create Date: 2026-09-29 23:30:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ALL_FEATURES = ["ai_assistant", "budget", "contracts", "crm", "legacy_workspace", "payroll"]

PLANS = (
    # code, name, seats, features, price (MNT), sort
    ("starter", "Starter", 10, ["contracts"], 290000, 10),
    ("professional", "Professional", 50, ["ai_assistant", "budget", "contracts", "crm"], 990000, 20),
    ("enterprise", "Enterprise", 500, ["ai_assistant", "budget", "contracts", "crm", "payroll"], 2490000, 30),
)

# Tables that already had a nullable tenant key: backfill, then NOT NULL.
# (table, parent column, parent table) — the parent feeds the fill trigger.
NULLABLE_TENANT_TABLES = (
    ("tasks", "assignee_id", "employees"),
    ("leave_requests", "employee_id", "employees"),
    ("company_knowledge", None, None),
)

# Legacy tables without a tenant key. The column is DB-managed (not mapped in
# the ORM): the trigger fills it, RLS filters on it. Order matters: parents
# are backfilled before their children.
LEGACY_TENANT_TABLES = (
    ("work_reports", "employee_id", "employees"),
    ("work_time_entries", "employee_id", "employees"),
    ("work_report_revisions", "report_id", "work_reports"),
    ("work_report_prompts", "report_id", "work_reports"),
    ("report_comments", "report_id", "work_reports"),
    ("survey_sessions", "employee_id", "employees"),
    ("answers", "session_id", "survey_sessions"),
    ("schedules", "employee_id", "employees"),
    ("shift_schedules", "employee_id", "employees"),
    ("streaks", "employee_id", "employees"),
    ("employee_questions", "employee_id", "employees"),
    ("resource_allocations", "employee_id", "employees"),
    ("questions", None, None),
    ("manager_settings", None, None),
    ("unknown_assistant_requests", None, None),
    ("assistant_context_examples", None, None),
)

TENANT_ROW_VISIBLE = """
CREATE OR REPLACE FUNCTION tenant_row_visible(row_tenant integer) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN coalesce(current_setting('app.tenant_id', true), '') <> ''
      THEN row_tenant = current_setting('app.tenant_id', true)::integer
    WHEN current_setting('app.rls_strict', true) = 'on'
      THEN current_setting('app.system_context', true) = 'on'
    ELSE true
  END
$$;
"""

FILL_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION tenant_fill_organization_id() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  request_tenant text := current_setting('app.tenant_id', true);
  parent_id integer;
BEGIN
  IF NEW.organization_id IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF TG_NARGS >= 2 THEN
    EXECUTE format('SELECT ($1).%I', TG_ARGV[0]) INTO parent_id USING NEW;
    IF parent_id IS NOT NULL THEN
      EXECUTE format('SELECT organization_id FROM %I WHERE id = $1', TG_ARGV[1]) INTO parent_id USING parent_id;
      NEW.organization_id := parent_id;
    END IF;
  END IF;
  IF NEW.organization_id IS NULL AND coalesce(request_tenant, '') <> '' THEN
    NEW.organization_id := request_tenant::integer;
  END IF;
  IF NEW.organization_id IS NULL THEN
    SELECT id INTO NEW.organization_id FROM organizations WHERE is_primary LIMIT 1;
  END IF;
  RETURN NEW;
END
$$;
"""

SEAT_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_tenant_seat_limit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  seat_cap integer;
  seats_used integer;
BEGIN
  IF NEW.status NOT IN ('active', 'invited', 'locked') OR coalesce(NEW.preferences->>'system_agent', '') <> '' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE'
     AND OLD.status IN ('active', 'invited', 'locked')
     AND coalesce(OLD.preferences->>'system_agent', '') = ''
     AND OLD.organization_id = NEW.organization_id THEN
    RETURN NEW;  -- already holds a seat
  END IF;
  SELECT seat_limit INTO seat_cap FROM organizations WHERE id = NEW.organization_id FOR UPDATE;
  IF seat_cap IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT count(*) INTO seats_used FROM user_accounts
   WHERE organization_id = NEW.organization_id
     AND status IN ('active', 'invited', 'locked')
     AND coalesce(preferences->>'system_agent', '') = ''
     AND id <> NEW.id;
  IF seats_used + 1 > seat_cap THEN
    RAISE EXCEPTION 'seat_limit_exceeded: tenant % uses % of % seats', NEW.organization_id, seats_used, seat_cap
      USING ERRCODE = 'OY001';
  END IF;
  RETURN NEW;
END
$$;
"""

IDENTITY_FUNCTION = """
CREATE OR REPLACE FUNCTION platform_identity_in_use(p_kind text, p_value text, p_exclude integer DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE
SET app.tenant_id = ''
SET app.system_context = 'on'
AS $$
  SELECT CASE p_kind
    WHEN 'account_email' THEN EXISTS (
      SELECT 1 FROM user_accounts WHERE lower(email) = lower(p_value) AND id IS DISTINCT FROM p_exclude)
    WHEN 'employee_email' THEN EXISTS (
      SELECT 1 FROM employees WHERE lower(email) = lower(p_value) AND id IS DISTINCT FROM p_exclude)
    WHEN 'employee_telegram' THEN EXISTS (
      SELECT 1 FROM employees WHERE telegram_id = p_value AND id IS DISTINCT FROM p_exclude)
    ELSE false
  END
$$;
"""


def _tenant_tables(bind) -> list[str]:
    rows = bind.execute(sa.text(
        """
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = current_schema() AND c.column_name = 'organization_id'
        ORDER BY c.table_name
        """
    )).scalars().all()
    return list(rows)


def _fill_trigger(table: str, parent_column: str | None, parent_table: str | None) -> None:
    arguments = f"'{parent_column}', '{parent_table}'" if parent_column else ""
    op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_tenant_fill ON "{table}"')
    op.execute(
        f'CREATE TRIGGER trg_{table}_tenant_fill BEFORE INSERT ON "{table}" '
        f"FOR EACH ROW EXECUTE FUNCTION tenant_fill_organization_id({arguments})"
    )


def upgrade() -> None:
    bind = op.get_bind()

    # ── plans ─────────────────────────────────────────────────────────────
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("seat_limit", sa.Integer()),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("billing_cycle", sa.Text(), nullable=False, server_default="monthly"),
        sa.Column("price_amount", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="MNT"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("billing_cycle IN ('monthly','quarterly','yearly','custom')", name="ck_subscription_plans_billing_cycle"),
        sa.CheckConstraint("seat_limit IS NULL OR seat_limit > 0", name="ck_subscription_plans_seat_limit"),
    )
    plans = sa.table(
        "subscription_plans",
        sa.column("code", sa.Text()), sa.column("name", sa.Text()), sa.column("seat_limit", sa.Integer()),
        sa.column("features", postgresql.JSONB()), sa.column("price_amount", sa.Numeric()), sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(plans, [
        {"code": code, "name": name, "seat_limit": seats, "features": features, "price_amount": price, "sort_order": sort}
        for code, name, seats, features, price, sort in PLANS
    ])

    # ── organizations → tenants ───────────────────────────────────────────
    op.add_column("organizations", sa.Column("slug", sa.Text()))
    op.add_column("organizations", sa.Column("status", sa.Text(), nullable=False, server_default="active"))
    op.add_column("organizations", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("organizations", sa.Column("plan_code", sa.Text()))
    op.add_column("organizations", sa.Column("billing_cycle", sa.Text(), nullable=False, server_default="monthly"))
    op.add_column("organizations", sa.Column("seat_limit", sa.Integer()))
    op.add_column("organizations", sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("organizations", sa.Column("license_required", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("organizations", sa.Column("license_expires_at", sa.DateTime(timezone=True)))
    op.add_column("organizations", sa.Column("branding", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("organizations", sa.Column("contact_email", sa.Text()))
    op.add_column("organizations", sa.Column("status_reason", sa.Text()))
    op.add_column("organizations", sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.add_column("organizations", sa.Column("terminated_at", sa.DateTime(timezone=True)))

    # Every pre-SaaS organization is grandfathered: all features, unlimited
    # seats, no license needed. The lowest id is the primary tenant.
    bind.execute(sa.text(
        """
        UPDATE organizations o
           SET is_primary = (o.id = (SELECT min(id) FROM organizations)),
               slug = CASE WHEN o.id = (SELECT min(id) FROM organizations) THEN 'oyuns' ELSE 'org-' || o.id END,
               plan_code = 'enterprise',
               features = CAST(:features AS jsonb),
               license_required = false,
               branding = jsonb_build_object('display_name', o.name)
        """
    ), {"features": json.dumps(ALL_FEATURES)})
    # The company row was inserted with an explicit id (q5r6s7t8u9v0 /
    # seed_admin), so the sequence never advanced; the first tenant created
    # from the console would collide with it.
    bind.execute(sa.text(
        "SELECT setval(pg_get_serial_sequence('organizations', 'id'), GREATEST((SELECT max(id) FROM organizations), 1), "
        "(SELECT count(*) > 0 FROM organizations))"
    ))
    op.alter_column("organizations", "slug", nullable=False)
    op.create_unique_constraint("uq_organizations_slug", "organizations", ["slug"])
    op.create_check_constraint("ck_organizations_slug", "organizations", "slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'")
    op.create_check_constraint("ck_organizations_status", "organizations", "status IN ('pending_activation','active','suspended','terminated')")
    op.create_check_constraint("ck_organizations_billing_cycle", "organizations", "billing_cycle IN ('monthly','quarterly','yearly','custom')")
    op.create_check_constraint("ck_organizations_seat_limit", "organizations", "seat_limit IS NULL OR seat_limit >= 0")
    op.create_index("uq_organizations_primary", "organizations", ["is_primary"], unique=True, postgresql_where=sa.text("is_primary"))
    op.create_foreign_key("fk_organizations_plan_code", "organizations", "subscription_plans", ["plan_code"], ["code"], ondelete="SET NULL", onupdate="CASCADE")

    # ── operators, licenses, domains, audit ───────────────────────────────
    op.create_table(
        "platform_operators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text()),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="superadmin"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('superadmin','support')", name="ck_platform_operators_role"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_platform_operators_status"),
    )
    op.create_table(
        "tenant_licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.Text()),
        sa.Column("seat_limit", sa.Integer(), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("billing_cycle", sa.Text(), nullable=False, server_default="monthly"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="issued"),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("tenant_licenses.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column("issued_by_operator_id", sa.Integer(), sa.ForeignKey("platform_operators.id", ondelete="SET NULL")),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("activated_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("activated_by_operator_id", sa.Integer(), sa.ForeignKey("platform_operators.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.Text()),
        sa.Column("revoked_by_operator_id", sa.Integer(), sa.ForeignKey("platform_operators.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('issued','active','superseded','revoked')", name="ck_tenant_licenses_status"),
        sa.CheckConstraint("seat_limit >= 1", name="ck_tenant_licenses_seat_limit"),
        sa.CheckConstraint("expires_at > valid_from", name="ck_tenant_licenses_window"),
    )
    op.create_index("ix_tenant_licenses_org_status", "tenant_licenses", ["organization_id", "status"])
    op.create_index("uq_tenant_licenses_active", "tenant_licenses", ["organization_id"], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table(
        "tenant_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=False, unique=True),
        sa.Column("verification_token", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("hostname = lower(hostname)", name="ck_tenant_domains_lowercase"),
    )
    op.create_index("ix_tenant_domains_org", "tenant_domains", ["organization_id"])
    op.create_table(
        "platform_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("platform_operators.id", ondelete="SET NULL")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text()),
        sa.Column("target_id", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_platform_audit_logs_org_created", "platform_audit_logs", ["organization_id", "created_at"])

    # ── tenant key everywhere ─────────────────────────────────────────────
    op.execute(FILL_TRIGGER_FUNCTION)
    primary = "(SELECT id FROM organizations WHERE is_primary LIMIT 1)"
    bind.execute(sa.text(
        f"""
        UPDATE tasks t SET organization_id = coalesce(
          (SELECT e.organization_id FROM employees e WHERE e.id = t.assignee_id),
          (SELECT e.organization_id FROM employees e WHERE e.id = t.created_by_id),
          (SELECT p.organization_id FROM projects p WHERE p.id = t.project_id),
          {primary})
        WHERE t.organization_id IS NULL
        """
    ))
    bind.execute(sa.text(
        f"""
        UPDATE leave_requests l SET organization_id = coalesce(
          (SELECT e.organization_id FROM employees e WHERE e.id = l.employee_id), {primary})
        WHERE l.organization_id IS NULL
        """
    ))
    bind.execute(sa.text(f"UPDATE company_knowledge SET organization_id = {primary} WHERE organization_id IS NULL"))
    for table, parent_column, parent_table in NULLABLE_TENANT_TABLES:
        op.alter_column(table, "organization_id", nullable=False)
        _fill_trigger(table, parent_column, parent_table)

    for table, parent_column, parent_table in LEGACY_TENANT_TABLES:
        op.add_column(table, sa.Column("organization_id", sa.Integer()))
        if parent_column:
            bind.execute(sa.text(
                f'UPDATE "{table}" child SET organization_id = parent.organization_id '
                f'FROM "{parent_table}" parent WHERE parent.id = child."{parent_column}" AND child.organization_id IS NULL'
            ))
        if table == "work_time_entries":
            bind.execute(sa.text(
                "UPDATE work_time_entries w SET organization_id = r.organization_id FROM work_reports r "
                "WHERE r.id = w.report_id AND w.organization_id IS NULL"
            ))
        bind.execute(sa.text(f'UPDATE "{table}" SET organization_id = {primary} WHERE organization_id IS NULL'))
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_organization", table, "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
        _fill_trigger(table, parent_column, parent_table)

    # ── seats ─────────────────────────────────────────────────────────────
    op.execute(SEAT_TRIGGER_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_user_accounts_seat_limit BEFORE INSERT OR UPDATE OF status, organization_id, preferences "
        "ON user_accounts FOR EACH ROW EXECUTE FUNCTION enforce_tenant_seat_limit()"
    )
    op.execute(IDENTITY_FUNCTION)

    # ── row-level security ────────────────────────────────────────────────
    op.execute(TENANT_ROW_VISIBLE)
    for table in _tenant_tables(bind):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (tenant_row_visible(organization_id)) WITH CHECK (tenant_row_visible(organization_id))"
        )
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organizations")
    op.execute("CREATE POLICY tenant_isolation ON organizations USING (tenant_row_visible(id)) WITH CHECK (tenant_row_visible(id))")


def downgrade() -> None:
    bind = op.get_bind()
    for table in [*_tenant_tables(bind), "organizations"]:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION IF EXISTS tenant_row_visible(integer)")
    op.execute("DROP FUNCTION IF EXISTS platform_identity_in_use(text, text, integer)")
    op.execute("DROP TRIGGER IF EXISTS trg_user_accounts_seat_limit ON user_accounts")
    op.execute("DROP FUNCTION IF EXISTS enforce_tenant_seat_limit()")

    for table, _, _ in reversed(LEGACY_TENANT_TABLES):
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_tenant_fill ON "{table}"')
        op.drop_index(f"ix_{table}_organization_id", table_name=table)
        op.drop_constraint(f"fk_{table}_organization", table, type_="foreignkey")
        op.drop_column(table, "organization_id")
    for table, _, _ in NULLABLE_TENANT_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_tenant_fill ON "{table}"')
        op.alter_column(table, "organization_id", nullable=True)
    op.execute("DROP FUNCTION IF EXISTS tenant_fill_organization_id()")

    op.drop_index("ix_platform_audit_logs_org_created", table_name="platform_audit_logs")
    op.drop_table("platform_audit_logs")
    op.drop_index("ix_tenant_domains_org", table_name="tenant_domains")
    op.drop_table("tenant_domains")
    op.drop_index("uq_tenant_licenses_active", table_name="tenant_licenses")
    op.drop_index("ix_tenant_licenses_org_status", table_name="tenant_licenses")
    op.drop_table("tenant_licenses")
    op.drop_table("platform_operators")

    op.drop_constraint("fk_organizations_plan_code", "organizations", type_="foreignkey")
    op.drop_index("uq_organizations_primary", table_name="organizations")
    for name in ("ck_organizations_seat_limit", "ck_organizations_billing_cycle", "ck_organizations_status", "ck_organizations_slug"):
        op.drop_constraint(name, "organizations", type_="check")
    op.drop_constraint("uq_organizations_slug", "organizations", type_="unique")
    for column in ("terminated_at", "suspended_at", "status_reason", "contact_email", "branding", "license_expires_at",
                   "license_required", "features", "seat_limit", "billing_cycle", "plan_code", "is_primary", "status", "slug"):
        op.drop_column("organizations", column)
    op.drop_table("subscription_plans")
