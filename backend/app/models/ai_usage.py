"""AI 调用用量记录模型"""
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid


class AIUsageLog(Base):
    """AI 调用 Token 用量表。

    这里只记录 token 和 OpenRouter 价格库给出的参考估算，不做真实扣费。
    """

    __tablename__ = "ai_usage_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True, comment="用户ID")
    request_mode = Column(String(50), nullable=False, index=True, comment="请求类型")
    provider = Column(String(50), nullable=False, index=True, comment="API提供商")
    model = Column(String(180), nullable=False, index=True, comment="模型名称")
    api_base_url = Column(String(500), index=True, comment="API地址")

    prompt_tokens = Column(Integer, default=0, comment="输入Token")
    completion_tokens = Column(Integer, default=0, comment="输出Token")
    total_tokens = Column(Integer, default=0, comment="总Token")

    stream = Column(Boolean, default=False, comment="是否流式调用")
    auto_mcp = Column(Boolean, default=False, comment="是否启用MCP")
    tools_count = Column(Integer, default=0, comment="可用工具数")
    tool_calls_count = Column(Integer, default=0, comment="工具调用次数")
    retry_count = Column(Integer, default=0, comment="重试次数")
    success = Column(Boolean, default=False, index=True, comment="是否成功")
    duration_ms = Column(Integer, comment="总耗时毫秒")
    finish_reason = Column(String(100), comment="结束原因")
    error_type = Column(String(120), comment="异常类型")
    error_message = Column(Text, comment="异常摘要")

    reference_prompt_price = Column(Float, comment="OpenRouter输入参考单价")
    reference_completion_price = Column(Float, comment="OpenRouter输出参考单价")
    reference_estimated_cost = Column(Float, comment="OpenRouter参考估算费用")
    reference_currency = Column(String(20), default="USD", comment="参考货币")
    pricing_source = Column(String(100), default="openrouter", comment="价格来源")
    pricing_updated_at = Column(DateTime, comment="价格缓存更新时间")

    created_at = Column(DateTime, server_default=func.now(), index=True, comment="创建时间")

    def __repr__(self):
        return (
            f"<AIUsageLog(id={self.id[:8]}, user={self.user_id}, "
            f"model={self.model}, total_tokens={self.total_tokens})>"
        )
