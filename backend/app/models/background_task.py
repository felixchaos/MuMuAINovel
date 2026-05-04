"""后台任务数据模型 - 用于长时间运行的AI生成任务"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid


class BackgroundTask(Base):
    """后台任务表 - 追踪所有长时间运行的生成任务"""
    __tablename__ = "background_tasks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True, comment="用户ID")
    project_id = Column(String(36), nullable=False, index=True, comment="项目ID")
    
    # 任务类型
    task_type = Column(String(50), nullable=False, comment="任务类型: outline_new/outline_continue/outline_expand/chapter_generate/chapter_batch/wizard/book_import_parse")
    
    # 任务状态
    status = Column(String(20), default="pending", comment="任务状态: pending/running/completed/failed/cancelled")
    progress = Column(Integer, default=0, comment="进度百分比(0-100)")
    status_message = Column(String(500), comment="当前状态消息")
    
    # 任务输入/输出
    task_input = Column(JSON, comment="任务输入参数(JSON)")
    task_result = Column(JSON, comment="任务结果(JSON)")
    error_message = Column(Text, comment="错误信息")
    
    # 进度详情（用于前端展示实时进度）
    progress_details = Column(JSON, comment="进度详情: {stage, message, word_count, etc.}")
    
    # 取消支持
    cancel_requested = Column(Boolean, default=False, comment="是否请求取消")
    
    # 重试信息
    retry_count = Column(Integer, default=0, comment="已重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    
    # 时间记录
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    def __repr__(self):
        return f"<BackgroundTask(id={self.id[:8]}, type={self.task_type}, status={self.status}, progress={self.progress}%)>"
