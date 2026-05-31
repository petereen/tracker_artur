"""add tasks and task_comments

Revision ID: c1a2b3d4e5f6
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_by_tg', sa.Text(), nullable=True),
        sa.Column('assignee_id', sa.Integer(), nullable=True),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), server_default='open', nullable=False),
        sa.Column('priority', sa.Integer(), server_default='2', nullable=True),
        sa.Column('reminder_intervals_min', postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by_id', sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open','in_progress','done','overdue','cancelled')",
            name='ck_tasks_status',
        ),
        sa.ForeignKeyConstraint(['created_by_id'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assignee_id'], ['employees.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['completed_by_id'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tasks_assignee_id', 'tasks', ['assignee_id'])
    op.create_index('ix_tasks_created_by_id', 'tasks', ['created_by_id'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])

    op.create_table(
        'task_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('author_tg', sa.Text(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_comments_task_id', 'task_comments', ['task_id'])


def downgrade() -> None:
    op.drop_index('ix_task_comments_task_id', table_name='task_comments')
    op.drop_table('task_comments')
    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index('ix_tasks_created_by_id', table_name='tasks')
    op.drop_index('ix_tasks_assignee_id', table_name='tasks')
    op.drop_table('tasks')
