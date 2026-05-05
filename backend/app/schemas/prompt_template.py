"""提示词模板相关的Pydantic模型"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class PromptTemplateBase(BaseModel):
    """提示词模板基础模型"""
    template_key: str = Field(..., description="模板键名")
    template_name: str = Field(..., description="模板显示名称")
    template_content: str = Field(..., description="模板内容")
    description: Optional[str] = Field(None, description="模板描述")
    category: Optional[str] = Field(None, description="模板分类")
    parameters: Optional[str] = Field(None, description="模板参数定义(JSON)")
    is_active: bool = Field(True, description="是否启用")


class PromptTemplateCreate(PromptTemplateBase):
    """创建提示词模板请求模型"""
    pass


class PromptTemplateUpdate(BaseModel):
    """更新提示词模板请求模型"""
    template_name: Optional[str] = Field(None, description="模板显示名称")
    template_content: Optional[str] = Field(None, description="模板内容")
    description: Optional[str] = Field(None, description="模板描述")
    category: Optional[str] = Field(None, description="模板分类")
    parameters: Optional[str] = Field(None, description="模板参数定义(JSON)")
    is_active: Optional[bool] = Field(None, description="是否启用")


class PromptTemplateResponse(PromptTemplateBase):
    """提示词模板响应模型"""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    is_system_default: bool
    created_at: datetime
    updated_at: datetime


class PromptTemplateListResponse(BaseModel):
    """提示词模板列表响应"""
    templates: List[PromptTemplateResponse]
    total: int
    categories: List[str]


class PromptTemplateCategoryResponse(BaseModel):
    """提示词模板分类响应"""
    category: str
    count: int
    templates: List[PromptTemplateResponse]


class PromptTemplateExportItem(BaseModel):
    """提示词模板导出项模型"""
    template_key: str = Field(..., description="模板键名")
    template_name: str = Field(..., description="模板显示名称")
    template_content: str = Field(..., description="模板内容")
    description: Optional[str] = Field(None, description="模板描述")
    category: Optional[str] = Field(None, description="模板分类")
    parameters: Optional[str] = Field(None, description="模板参数定义(JSON)")
    is_active: bool = Field(True, description="是否启用")
    is_customized: bool = Field(..., description="是否为用户自定义（false=系统默认，true=用户自定义）")
    system_content_hash: Optional[str] = Field(None, description="系统默认内容的哈希值，用于比对")


class PromptTemplateExport(BaseModel):
    """提示词模板导出模型"""
    templates: List[PromptTemplateExportItem]
    export_time: datetime
    version: str = "2.0"
    statistics: Optional[dict] = Field(None, description="导出统计信息")


class PromptTemplateImportResult(BaseModel):
    """提示词模板导入结果"""
    message: str
    statistics: dict = Field(..., description="导入统计信息")
    converted_templates: List[dict] = Field(default_factory=list, description="被转换为自定义的模板列表")


class PromptTemplatePreviewRequest(BaseModel):
    """提示词模板预览请求"""
    template_content: str = Field(..., description="模板内容")
    parameters: dict = Field(..., description="参数字典")
