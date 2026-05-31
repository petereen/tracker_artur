"""notification policy: quiet hours, digests, outbox

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

import datetime as _dt


def upgrade() -> None:
    # manager_settings — политика уведомлений
    op.add_column('manager_settings', sa.Column('quiet_start', sa.Time(), server_default='20:00:00', nullable=True))
    op.add_column('manager_settings', sa.Column('quiet_end', sa.Time(), server_default='09:00:00', nullable=True))
    op.add_column('manager_settings', sa.Column('work_weekdays', postgresql.ARRAY(sa.Integer()), server_default='{1,2,3,4,5}', nullable=True))
    op.add_column('manager_settings', sa.Column('morning_digest_time', sa.Time(), server_default='09:00:00', nullable=True))
    op.add_column('manager_settings', sa.Column('evening_digest_time', sa.Time(), server_default='18:00:00', nullable=True))
    op.add_column('manager_settings', sa.Column('overdue_escalation_days', sa.Integer(), server_default='1', nullable=True))
    op.add_column('manager_settings', sa.Column('notifications_enabled', sa.Boolean(), server_default=sa.true(), nullable=True))

    # tasks — защита от повторного пинга о просрочке
    op.add_column('tasks', sa.Column('overdue_pinged_at', sa.DateTime(timezone=True), nullable=True))

    # notification_outbox — мост api → бот
    op.create_table(
        'notification_outbox',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('recipient_tg', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('dedup_key', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedup_key', name='uq_notification_outbox_dedup_key'),
    )
    op.create_index('ix_notification_outbox_status', 'notification_outbox', ['status', 'not_before'])


def downgrade() -> None:
    op.drop_index('ix_notification_outbox_status', table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_column('tasks', 'overdue_pinged_at')
    for col in ('notifications_enabled', 'overdue_escalation_days', 'evening_digest_time',
                'morning_digest_time', 'work_weekdays', 'quiet_end', 'quiet_start'):
        op.drop_column('manager_settings', col)
