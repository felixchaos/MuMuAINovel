"""添加AI用量统计表

Revision ID: cost002
Revises: def45678ghi9
Create Date: 2026-05-04 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'cost002'
down_revision = 'def45678ghi9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_usage_logs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('request_mode', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('api_base_url', sa.String(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), default=0),
        sa.Column('completion_tokens', sa.Integer(), default=0),
        sa.Column('total_tokens', sa.Integer(), default=0),
        sa.Column('stream', sa.Boolean(), default=False),
        sa.Column('auto_mcp', sa.Boolean(), default=False),
        sa.Column('tools_count', sa.Integer(), default=0),
        sa.Column('tool_calls_count', sa.Integer(), default=0),
        sa.Column('retry_count', sa.Integer(), default=0),
        sa.Column('success', sa.Boolean(), default=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('finish_reason', sa.String(), nullable=True),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('reference_prompt_price', sa.Float(), nullable=True),
        sa.Column('reference_completion_price', sa.Float(), nullable=True),
        sa.Column('reference_estimated_cost', sa.Float(), nullable=True),
        sa.Column('reference_currency', sa.String(), default='USD'),
        sa.Column('pricing_source', sa.String(), default='openrouter'),
        sa.Column('pricing_updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_usage_logs_user_created', 'ai_usage_logs', ['user_id', 'created_at'])
    op.create_index('ix_ai_usage_logs_user_model', 'ai_usage_logs', ['user_id', 'model'])
    op.create_index('ix_ai_usage_logs_user_api', 'ai_usage_logs', ['user_id', 'api_base_url'])
    op.create_index('ix_ai_usage_logs_user_request_mode', 'ai_usage_logs', ['user_id', 'request_mode'])


def downgrade() -> None:
    op.drop_index('ix_ai_usage_logs_user_request_mode', table_name='ai_usage_logs')
    op.drop_index('ix_ai_usage_logs_user_api', table_name='ai_usage_logs')
    op.drop_index('ix_ai_usage_logs_user_model', table_name='ai_usage_logs')
    op.drop_index('ix_ai_usage_logs_user_created', table_name='ai_usage_logs')
    op.drop_table('ai_usage_logs')
