"""merge contract archive and global-search migration heads"""

from typing import Sequence, Union


revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, Sequence[str], None] = (
    "b2c3d4e5f6g7",
    "m6n7o8p9q0r1",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
