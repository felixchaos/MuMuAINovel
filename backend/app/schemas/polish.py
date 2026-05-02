"""AI去味相关的Pydantic模型"""
from pydantic import BaseModel, Field
from typing import List, Optional


class PolishRequest(BaseModel):
    """AI去味请求模型"""
    original_text: str = Field(..., description="原始文本（AI生成的文本）")
    project_id: Optional[str] = Field(None, description="项目ID（可选，用于记录历史）")
    provider: Optional[str] = Field(None, description="AI提供商")
    model: Optional[str] = Field(None, description="AI模型")
    temperature: Optional[float] = Field(0.8, description="温度参数，建议0.7-0.9")
    instruction: Optional[str] = Field(None, description="本次润色/优化的附加指令")


class PolishResponse(BaseModel):
    """AI去味响应模型"""
    original_text: str = Field(..., description="原始文本")
    polished_text: str = Field(..., description="去味后的文本")
    word_count_before: int = Field(..., description="处理前字数")
    word_count_after: int = Field(..., description="处理后字数")


class OutlineOptimizeTaskRequest(BaseModel):
    """后台优化大纲请求"""
    project_id: str = Field(..., description="项目ID")
    outline_ids: Optional[List[str]] = Field(None, description="要优化的大纲ID列表；为空则优化项目全部大纲")
    provider: Optional[str] = Field(None, description="AI提供商")
    model: Optional[str] = Field(None, description="AI模型")
    temperature: Optional[float] = Field(0.6, description="温度参数")


class CharacterOptimizeTaskRequest(BaseModel):
    """后台优化角色/组织请求"""
    project_id: str = Field(..., description="项目ID")
    character_ids: List[str] = Field(..., description="要优化的角色/组织ID列表")
    provider: Optional[str] = Field(None, description="AI提供商")
    model: Optional[str] = Field(None, description="AI模型")
    temperature: Optional[float] = Field(0.6, description="温度参数")
