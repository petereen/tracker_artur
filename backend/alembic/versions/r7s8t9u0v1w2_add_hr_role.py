"""Allow HR role assignments."""

from typing import Sequence, Union

from alembic import op


revision: str = "r7s8t9u0v1w2"
down_revision: Union[str, Sequence[str], None] = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_role_assignments_role", "role_assignments", type_="check")
    op.create_check_constraint(
        "ck_role_assignments_role",
        "role_assignments",
        "role IN ('admin','manager','team_lead','hr','member','contractor','client_auditor')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_assignments WHERE role = 'hr'")
    op.drop_constraint("ck_role_assignments_role", "role_assignments", type_="check")
    op.create_check_constraint(
        "ck_role_assignments_role",
        "role_assignments",
        "role IN ('admin','manager','team_lead','member','contractor','client_auditor')",
    )

