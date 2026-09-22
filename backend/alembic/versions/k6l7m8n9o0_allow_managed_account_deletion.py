"""Allow deleting accounts that have contract review history."""

from typing import Sequence, Union

from alembic import op


revision: str = "k6l7m8n9o0"
down_revision: Union[str, Sequence[str], None] = "j5k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Review rows retain their decision and reviewer name snapshot after the
    # account is removed. The account id is historical metadata, not a reason
    # to keep a deleted login alive.
    op.drop_constraint(
        "contract_reviews_reviewer_account_id_fkey",
        "contract_reviews",
        type_="foreignkey",
    )
    op.alter_column("contract_reviews", "reviewer_account_id", nullable=True)
    op.create_foreign_key(
        "fk_contract_reviews_reviewer_account",
        "contract_reviews",
        "user_accounts",
        ["reviewer_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contract_reviews_reviewer_account",
        "contract_reviews",
        type_="foreignkey",
    )
    op.alter_column("contract_reviews", "reviewer_account_id", nullable=False)
    op.create_foreign_key(
        "contract_reviews_reviewer_account_id_fkey",
        "contract_reviews",
        "user_accounts",
        ["reviewer_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
