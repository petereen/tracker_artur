"""Correct the inactive 2026 payroll example without publishing it."""
from alembic import op
import sqlalchemy as sa


revision = "p9q0r1s2t3u4"
down_revision = "k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_work_policies", sa.Column("hazard_class", sa.String(length=16), nullable=False, server_default="standard"))
    op.alter_column("payroll_work_policies", "stacking_policy", existing_type=sa.String(length=24), server_default="stack")
    op.alter_column(
        "employee_payroll_profiles",
        "insured_category",
        existing_type=sa.String(length=32),
        server_default="01001",
    )
    # Update only the unapproved seed example. Existing employee assignments
    # and frozen payslip snapshots retain their historical contributor code.
    op.execute(sa.text("""
        UPDATE shi_rate_tiers AS tier
        SET insured_category = '01001'
        FROM statutory_config_profiles AS profile
        WHERE tier.profile_id = profile.id
          AND profile.code = 'MN_EXAMPLE_2026'
          AND profile.is_example IS TRUE
          AND profile.status = 'draft'
          AND tier.insured_category = 'employee'
    """))
    op.execute(sa.text("""
        UPDATE shi_rate_tiers AS tier
        SET rate = CASE tier.insurance_fund
              WHEN 'unemployment' THEN 0.005
              WHEN 'injury' THEN 0.005
              ELSE tier.rate
            END,
            base_ceiling_policy = 'none'
        FROM statutory_config_profiles AS profile
        WHERE tier.profile_id = profile.id
          AND profile.code = 'MN_EXAMPLE_2026'
          AND profile.is_example IS TRUE
          AND profile.status = 'draft'
          AND tier.payer = 'employer'
    """))


def downgrade() -> None:
    # Do not restore the stale rates: downgrade must not rewrite a draft that
    # may have been reviewed or copied into a later version.
    op.alter_column(
        "employee_payroll_profiles",
        "insured_category",
        existing_type=sa.String(length=32),
        server_default="employee",
    )
    op.drop_column("payroll_work_policies", "hazard_class")
    op.alter_column("payroll_work_policies", "stacking_policy", existing_type=sa.String(length=24), server_default="exclusive")
