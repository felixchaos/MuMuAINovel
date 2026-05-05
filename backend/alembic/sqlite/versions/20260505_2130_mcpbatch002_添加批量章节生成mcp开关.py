"""添加批量章节生成MCP开关

Revision ID: mcpbatch002
Revises: cost002
Create Date: 2026-05-05 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'mcpbatch002'
down_revision = 'cost002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'batch_generation_tasks',
        sa.Column('enable_mcp', sa.Boolean(), nullable=True, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('batch_generation_tasks', 'enable_mcp')
