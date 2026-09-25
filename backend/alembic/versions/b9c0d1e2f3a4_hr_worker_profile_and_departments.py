"""HR worker profile: registration number, contacts, employment type and statuses

Adds the HR fields a Mongolian employer needs on every worker record
(Регистрын дугаар, gender, address, emergency contact, employment type,
probation end, termination reason), widens employment_status beyond
active/inactive, and gives departments a description.

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f3
Create Date: 2026-09-25 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUSES = "('active','probation','on_leave','suspended','inactive','terminated')"
EMPLOYMENT_TYPES = "('full_time','part_time','contract','intern')"


def upgrade() -> None:
    op.add_column("departments", sa.Column("description", sa.Text(), nullable=True))

    op.add_column("employee_details", sa.Column("registration_number", sa.String(10), nullable=True))
    op.add_column("employee_details", sa.Column("gender", sa.String(8), nullable=True))
    op.add_column("employee_details", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("employee_details", sa.Column("emergency_contact_name", sa.Text(), nullable=True))
    op.add_column("employee_details", sa.Column("emergency_contact_phone", sa.Text(), nullable=True))
    op.add_column("employee_details", sa.Column("employment_type", sa.String(20), nullable=False, server_default="full_time"))
    op.add_column("employee_details", sa.Column("probation_end_date", sa.Date(), nullable=True))
    op.add_column("employee_details", sa.Column("termination_reason", sa.Text(), nullable=True))

    # Normalise legacy values before the status constraint lands; the person
    # row's is_active flag is the source of truth for anything unrecognised.
    op.execute(
        f"""
        UPDATE employee_details AS d
        SET employment_status = CASE WHEN e.is_active THEN 'active' ELSE 'inactive' END
        FROM employees AS e
        WHERE e.id = d.employee_id AND d.employment_status NOT IN {STATUSES}
        """
    )
    op.create_check_constraint("ck_employee_details_employment_status", "employee_details", f"employment_status IN {STATUSES}")
    op.create_check_constraint("ck_employee_details_employment_type", "employee_details", f"employment_type IN {EMPLOYMENT_TYPES}")
    op.create_index(
        "uq_employee_details_org_registration_number",
        "employee_details",
        ["organization_id", "registration_number"],
        unique=True,
        postgresql_where=sa.text("registration_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_employee_details_org_registration_number", table_name="employee_details")
    op.drop_constraint("ck_employee_details_employment_type", "employee_details", type_="check")
    op.drop_constraint("ck_employee_details_employment_status", "employee_details", type_="check")
    op.execute(
        "UPDATE employee_details SET employment_status = CASE WHEN employment_status IN ('active','probation') THEN 'active' ELSE 'inactive' END"
    )
    for column in (
        "termination_reason", "probation_end_date", "employment_type", "emergency_contact_phone",
        "emergency_contact_name", "address", "gender", "registration_number",
    ):
        op.drop_column("employee_details", column)
    op.drop_column("departments", "description")
