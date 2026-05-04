"""添加AI用量统计表

Revision ID: cost001
Revises: abc12345
Create Date: 2026-05-04 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'cost001'
down_revision = 'abc12345'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ai_usage_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(100), nullable=False, comment='用户ID'),
        sa.Column('request_mode', sa.String(50), nullable=False, comment='请求类型'),
        sa.Column('provider', sa.String(50), nullable=False, comment='API提供商'),
        sa.Column('model', sa.String(180), nullable=False, comment='模型名称'),
        sa.Column('api_base_url', sa.String(500), comment='API地址'),
        sa.Column('prompt_tokens', sa.Integer(), default=0, comment='输入Token'),
        sa.Column('completion_tokens', sa.Integer(), default=0, comment='输出Token'),
        sa.Column('total_tokens', sa.Integer(), default=0, comment='总Token'),
        sa.Column('stream', sa.Boolean(), default=False, comment='是否流式调用'),
        sa.Column('auto_mcp', sa.Boolean(), default=False, comment='是否启用MCP'),
        sa.Column('tools_count', sa.Integer(), default=0, comment='可用工具数'),
        sa.Column('tool_calls_count', sa.Integer(), default=0, comment='工具调用次数'),
        sa.Column('retry_count', sa.Integer(), default=0, comment='重试次数'),
        sa.Column('success', sa.Boolean(), default=False, comment='是否成功'),
        sa.Column('duration_ms', sa.Integer(), comment='总耗时毫秒'),
        sa.Column('finish_reason', sa.String(100), comment='结束原因'),
        sa.Column('error_type', sa.String(120), comment='异常类型'),
        sa.Column('error_message', sa.Text(), comment='异常摘要'),
        sa.Column('reference_prompt_price', sa.Float(), comment='OpenRouter输入参考单价'),
        sa.Column('reference_completion_price', sa.Float(), comment='OpenRouter输出参考单价'),
        sa.Column('reference_estimated_cost', sa.Float(), comment='OpenRouter参考估算费用'),
        sa.Column('reference_currency', sa.String(20), default='USD', comment='参考货币'),
        sa.Column('pricing_source', sa.String(100), default='openrouter', comment='价格来源'),
        sa.Column('pricing_updated_at', sa.DateTime(), comment='价格缓存更新时间'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), comment='创建时间'),
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
