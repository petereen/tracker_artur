"""Allow archived payroll component codes to be reused."""

from alembic import op
import sqlalchemy as sa


revision = "q6r7s8t9u0v1"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_payroll_component_master_org_code",
        "payroll_salary_component_masters",
        type_="unique",
    )
    op.create_index(
        "uq_payroll_component_master_org_code_active",
        "payroll_salary_component_masters",
        ["organization_id", "code"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_payroll_component_master_org_code_active",
        table_name="payroll_salary_component_masters",
    )
    op.create_unique_constraint(
        "uq_payroll_component_master_org_code",
        "payroll_salary_component_masters",
        ["organization_id", "code"],
    )
