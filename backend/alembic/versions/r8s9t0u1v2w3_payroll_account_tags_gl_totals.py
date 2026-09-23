"""Tag ERP accounts for payroll and link payroll GL rows to source runs."""

from alembic import op
import sqlalchemy as sa


revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


PURPOSES = (
    "salary_expense", "employee_shi_payable", "employer_shi_expense",
    "employer_shi_payable", "pit_payable", "net_pay_payable", "bank",
    "advance_clearing", "other_deductions_payable",
)


def upgrade() -> None:
    op.create_table(
        "payroll_account_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("erp_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(length=48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "account_id", "purpose", name="uq_payroll_account_tag"),
    )
    op.add_column("erp_general_ledger_entries", sa.Column("payroll_run_id", sa.Integer(), nullable=True))
    op.add_column("erp_general_ledger_entries", sa.Column("payroll_role", sa.String(length=48), nullable=True))
    op.create_foreign_key(
        "fk_erp_gl_payroll_run", "erp_general_ledger_entries", "payroll_runs",
        ["payroll_run_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_erp_gl_org_payroll_run_role", "erp_general_ledger_entries",
        ["organization_id", "payroll_run_id", "payroll_role"],
    )

    # Move the existing single-purpose payroll account convention into tags.
    op.execute(sa.text("""
        INSERT INTO payroll_account_tags (organization_id, account_id, purpose)
        SELECT organization_id, id, purpose FROM erp_accounts
        WHERE purpose IN :purposes
        ON CONFLICT (organization_id, account_id, purpose) DO NOTHING
    """).bindparams(sa.bindparam("purposes", expanding=True)).params(purposes=list(PURPOSES)))
    op.execute(sa.text("""
        INSERT INTO payroll_account_tags (organization_id, account_id, purpose)
        SELECT pp.organization_id, a.id, mapped.role
        FROM payroll_posting_profiles pp
        CROSS JOIN LATERAL jsonb_each_text(pp.account_roles) AS mapped(role, account_id)
        JOIN erp_accounts a ON a.id = CASE WHEN mapped.account_id ~ '^[0-9]+$' THEN mapped.account_id::integer END AND a.organization_id = pp.organization_id
        WHERE mapped.role IN :purposes
        ON CONFLICT (organization_id, account_id, purpose) DO NOTHING
    """).bindparams(sa.bindparam("purposes", expanding=True)).params(purposes=list(PURPOSES)))
    op.execute(sa.text("""
        INSERT INTO payroll_account_tags (organization_id, account_id, purpose)
        SELECT cm.organization_id, cm.account_id, 'salary_expense'
        FROM payroll_salary_component_masters cm
        JOIN erp_accounts a ON a.id = cm.account_id AND a.organization_id = cm.organization_id
        WHERE cm.account_id IS NOT NULL
        ON CONFLICT (organization_id, account_id, purpose) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO payroll_account_tags (organization_id, account_id, purpose)
        SELECT DISTINCT p.organization_id, li.account_id, 'salary_expense'
        FROM payslip_line_items li
        JOIN payslips p ON p.id = li.payslip_id
        JOIN erp_accounts a ON a.id = li.account_id AND a.organization_id = p.organization_id
        WHERE li.account_id IS NOT NULL
        ON CONFLICT (organization_id, account_id, purpose) DO NOTHING
    """))

    # Preserve period membership for historic runs, creating a closed period
    # for each unmatched date/profile window.
    op.execute(sa.text("""
        INSERT INTO payroll_periods
            (organization_id, code, name, start_date, end_date, tax_year,
             payroll_frequency, statutory_profile_id, status)
        SELECT DISTINCT r.organization_id,
            'legacy-' || to_char(r.period_start, 'YYYYMMDD') || '-' || to_char(r.period_end, 'YYYYMMDD') || '-p' || r.statutory_profile_id,
            'Historical ' || to_char(r.period_start, 'YYYY-MM-DD') || ' to ' || to_char(r.period_end, 'YYYY-MM-DD'),
            r.period_start, r.period_end, extract(year from r.period_end)::integer,
            r.payroll_frequency, r.statutory_profile_id, 'closed'
        FROM payroll_runs r
        WHERE r.payroll_period_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM payroll_periods p
            WHERE p.organization_id = r.organization_id
              AND p.start_date = r.period_start AND p.end_date = r.period_end
              AND p.statutory_profile_id = r.statutory_profile_id
          )
        ON CONFLICT (organization_id, code) DO NOTHING
    """))
    op.execute(sa.text("""
        UPDATE payroll_runs r SET payroll_period_id = (
            SELECT p.id FROM payroll_periods p
            WHERE p.organization_id = r.organization_id
              AND p.start_date = r.period_start AND p.end_date = r.period_end
              AND p.statutory_profile_id = r.statutory_profile_id
            ORDER BY p.id LIMIT 1
        ) WHERE r.payroll_period_id IS NULL
    """))

    # Associate ledger rows to their payroll run using the source document.
    op.execute(sa.text("""
        UPDATE erp_general_ledger_entries gl
        SET payroll_run_id = (d.payload->>'payroll_run_id')::integer
        FROM erp_documents d
        JOIN payroll_runs r ON r.id = (d.payload->>'payroll_run_id')::integer
        WHERE gl.document_id = d.id
          AND gl.organization_id = r.organization_id
          AND gl.payroll_run_id IS NULL
          AND d.document_type = 'payroll_run'
          AND d.payload ? 'payroll_run_id'
    """))
    op.execute(sa.text("""
        UPDATE erp_general_ledger_entries gl
        SET payroll_role = CASE
          WHEN memo ILIKE '%gross salary expense%' THEN 'salary_expense'
          WHEN memo ILIKE '%employer SHI expense%' THEN 'employer_shi_expense'
          WHEN memo ILIKE '%employee SHI payable%' THEN 'employee_shi_payable'
          WHEN memo ILIKE '%employer SHI payable%' THEN 'employer_shi_payable'
          WHEN memo ILIKE '%PIT payable%' THEN 'pit_payable'
          WHEN memo ILIKE '%net salary payable%' THEN 'net_pay_payable'
          WHEN memo ILIKE '%advance clearing%' THEN 'advance_clearing'
          WHEN memo ILIKE '%other employee deductions payable%' THEN 'other_deductions_payable'
          ELSE NULL END
        WHERE payroll_run_id IS NOT NULL
    """))
    op.execute(sa.text("""
        UPDATE erp_general_ledger_entries reversal
        SET payroll_role = original.payroll_role
        FROM erp_general_ledger_entries original
        WHERE reversal.reversal_of_id = original.id
          AND reversal.payroll_run_id IS NOT NULL
          AND reversal.payroll_role IS NULL
          AND original.payroll_role IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_index("ix_erp_gl_org_payroll_run_role", table_name="erp_general_ledger_entries")
    op.drop_constraint("fk_erp_gl_payroll_run", "erp_general_ledger_entries", type_="foreignkey")
    op.drop_column("erp_general_ledger_entries", "payroll_role")
    op.drop_column("erp_general_ledger_entries", "payroll_run_id")
    op.drop_table("payroll_account_tags")
