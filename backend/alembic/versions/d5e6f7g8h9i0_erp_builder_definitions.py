"""add ERP form, workflow, and scoped role builder records

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d5e6f7g8h9i0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("erp_access_roles", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("erp_documents", sa.Column("definition_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("erp_documents", sa.Column("workflow_state", sa.String(64), nullable=False, server_default="draft"))
    op.create_table(
        "erp_team_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_role_id", sa.Integer(), sa.ForeignKey("erp_access_roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "access_role_id", name="uq_erp_team_role"),
    )
    op.create_table(
        "erp_form_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("fields", json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("workflow", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "operation", "version", name="uq_erp_form_definition_version"),
    )
    op.create_index("ix_erp_form_definitions_org_operation_status", "erp_form_definitions", ["organization_id", "operation", "status"])
    op.create_table(
        "erp_master_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False), sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("payload", json, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("workflow_state", sa.String(64), nullable=False, server_default="draft"),
        sa.Column("scope", json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_by_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("materialized_entity_type", sa.String(40)), sa.Column("materialized_entity_id", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_erp_master_requests_org_operation_state", "erp_master_requests", ["organization_id", "operation", "workflow_state"])
    op.create_table(
        "erp_workflow_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False), sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(64)), sa.Column("to_state", sa.String(64), nullable=False), sa.Column("comment", sa.Text()),
        sa.Column("actor_account_id", sa.Integer(), sa.ForeignKey("user_accounts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_erp_workflow_transition_entity", "erp_workflow_transitions", ["organization_id", "entity_type", "entity_id", "created_at"])
    # Preserve legacy custom fields as the first immutable published definition for their resource.
    op.get_bind().exec_driver_sql("""
        INSERT INTO erp_form_definitions (organization_id, operation, version, status, fields, workflow, published_at)
        SELECT organization_id,
               replace(resource, 'document:', ''),
               1, 'published',
               jsonb_agg(jsonb_build_object('key', key, 'label', label, 'field_type', field_type,
                   'section', CASE WHEN resource IN ('party', 'item') THEN 'master' ELSE 'header' END,
                   'required', required, 'options', options, 'position', 0)),
               jsonb_build_object(
                   'initial_state', 'draft',
                   'states', jsonb_build_array(
                       jsonb_build_object('key', 'draft', 'terminal', false),
                       jsonb_build_object('key', 'approved', 'terminal', true),
                       jsonb_build_object('key', 'rejected', 'terminal', true),
                       jsonb_build_object('key', 'cancelled', 'terminal', true)
                   ),
                   'transitions', '[]'::jsonb
               ),
               now()
        FROM erp_custom_fields
        GROUP BY organization_id, resource
        ON CONFLICT (organization_id, operation, version) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_erp_workflow_transition_entity", table_name="erp_workflow_transitions")
    op.drop_table("erp_workflow_transitions")
    op.drop_index("ix_erp_master_requests_org_operation_state", table_name="erp_master_requests")
    op.drop_table("erp_master_requests")
    op.drop_index("ix_erp_form_definitions_org_operation_status", table_name="erp_form_definitions")
    op.drop_table("erp_form_definitions")
    op.drop_table("erp_team_roles")
    op.drop_column("erp_documents", "workflow_state")
    op.drop_column("erp_documents", "definition_version")
    op.drop_column("erp_access_roles", "is_active")
