"""拆书导入相关的 Pydantic Schema"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
ImportMode = Literal["append", "overwrite"]
ExtractLevel = Literal["basic", "standard", "deep"]
WarningLevel = Literal["info", "warning", "error"]
BookImportExtractMode = Literal["tail", "full"]
BookImportSetupMode = Literal["auto", "manual"]
BookImportEntityType = Literal["character", "organization", "location", "item", "unknown"]


class BookImportWarning(BaseModel):
    """导入告警信息"""
    code: str = Field(..., description="告警编码")
    message: str = Field(..., description="告警内容")
    level: WarningLevel = Field(default="warning", description="告警等级")


class BookImportSplitReport(BaseModel):
    """TXT 切分诊断报告"""
    mode: str = Field(..., description="切分模式标识")
    mode_label: str = Field(..., description="切分模式中文名")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="切分置信度 0-1")
    chapter_count: int = Field(default=0, ge=0, description="识别章节数")
    total_words: int = Field(default=0, ge=0, description="总字数")
    average_words: int = Field(default=0, ge=0, description="平均章节字数")
    min_words: int = Field(default=0, ge=0, description="最短章节字数")
    max_words: int = Field(default=0, ge=0, description="最长章节字数")
    size_cv: float = Field(default=0.0, ge=0.0, description="章节长度变异系数")
    dialogue_ratio: float = Field(default=0.0, ge=0.0, description="文本样本对白行比例")
    heading_density: float = Field(default=0.0, ge=0.0, description="文本样本疑似标题行密度")
    problem_category: str = Field(default="ok", description="切分问题分类")
    problem_label: str = Field(default="未发现明显异常", description="切分问题中文标签")
    short_chapter_count: int = Field(default=0, ge=0, description="短章节数量")
    long_chapter_count: int = Field(default=0, ge=0, description="长章节数量")
    abnormal_chapter_numbers: list[int] = Field(default_factory=list, description="异常章节序号")
    reasons: list[str] = Field(default_factory=list, description="诊断原因")


class BookImportEntityCandidate(BaseModel):
    """拆书预扫描实体候选"""
    name: str = Field(..., description="候选名称")
    entity_type: BookImportEntityType = Field(default="unknown", description="候选类型")
    occurrence_count: int = Field(default=0, ge=0, description="全文出现次数")
    first_chapter_number: Optional[int] = Field(None, description="首次出现章节")
    evidence: list[str] = Field(default_factory=list, description="证据片段")
    confidence: float = Field(default=0.6, ge=0.0, le=1.0, description="候选分类置信度")
    classification_reason: Optional[str] = Field(None, description="分类依据说明")


class BookImportTokenBudgetStage(BaseModel):
    """拆书预览阶段 Token 预算估算"""
    stage: str = Field(..., description="阶段标识")
    label: str = Field(..., description="阶段名称")
    estimated_prompt_tokens: int = Field(default=0, ge=0, description="预估输入 token")
    estimated_completion_tokens: int = Field(default=0, ge=0, description="预估输出 token")
    estimated_total_tokens: int = Field(default=0, ge=0, description="预估总 token")
    api_calls: int = Field(default=0, ge=0, description="预估 API 调用次数")


class BookImportTokenBudget(BaseModel):
    """拆书任务 Token 预算估算，仅供参考"""
    estimated_prompt_tokens: int = Field(default=0, ge=0, description="预估输入 token")
    estimated_completion_tokens: int = Field(default=0, ge=0, description="预估输出 token")
    estimated_total_tokens: int = Field(default=0, ge=0, description="预估总 token")
    estimated_api_calls: int = Field(default=0, ge=0, description="预估 API 调用次数")
    pricing_source: str = Field(default="openrouter", description="参考价格来源")
    note: str = Field(default="", description="估算说明")
    stages: list[BookImportTokenBudgetStage] = Field(default_factory=list, description="分阶段估算")


class ProjectSuggestion(BaseModel):
    """项目建议信息（可在预览页修改）"""
    title: str = Field(..., min_length=1, max_length=200, description="项目标题")
    description: Optional[str] = Field(None, description="项目简介")
    theme: Optional[str] = Field(None, description="主题")
    genre: Optional[str] = Field(None, description="类型")
    narrative_perspective: str = Field(default="第三人称", description="叙事视角")
    target_words: int = Field(default=100000, ge=1000, description="目标字数（默认10万字）")
    world_time_period: Optional[str] = Field(None, description="时间背景")
    world_location: Optional[str] = Field(None, description="地理位置")
    world_atmosphere: Optional[str] = Field(None, description="氛围基调")
    world_rules: Optional[str] = Field(None, description="世界规则")


class BookImportChapter(BaseModel):
    """预览章节"""
    title: str = Field(..., min_length=1, max_length=200, description="章节标题")
    content: str = Field(default="", description="章节正文")
    summary: Optional[str] = Field(None, description="章节摘要")
    chapter_number: int = Field(..., ge=1, description="章节序号")
    outline_title: Optional[str] = Field(None, description="关联大纲标题（可选）")


class BookImportOutline(BaseModel):
    """预览大纲"""
    title: str = Field(..., min_length=1, max_length=200, description="大纲标题")
    content: Optional[str] = Field(None, description="大纲内容")
    order_index: int = Field(..., ge=1, description="排序序号")
    structure: Optional[dict[str, Any]] = Field(None, description="结构化大纲（与系统大纲生成结构一致）")


class BookImportTaskCreateRequest(BaseModel):
    """创建拆书任务请求"""
    extract_mode: BookImportExtractMode = Field(default="tail", description="提取范围：tail=截取末章，full=整本")
    tail_chapter_count: int = Field(default=10, ge=5, le=9999, description="当 extract_mode=tail 时，截取末尾章节数；需为5的倍数，超过50将按整本处理")
    setup_mode: BookImportSetupMode = Field(
        default="auto",
        description="预览设定生成方式：auto=AI反向生成项目信息/大纲，manual=跳过AI反向生成由用户手动填写"
    )


class BookImportTaskCreateResponse(BaseModel):
    """创建任务响应"""
    task_id: str
    status: TaskStatus


class BookImportTaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: TaskStatus
    progress: int = Field(..., ge=0, le=100)
    message: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class BookImportPreviewResponse(BaseModel):
    """预览数据响应"""
    task_id: str
    project_suggestion: ProjectSuggestion
    chapters: list[BookImportChapter]
    outlines: list[BookImportOutline]
    warnings: list[BookImportWarning]
    split_report: Optional[BookImportSplitReport] = None
    entity_candidates: list[BookImportEntityCandidate] = Field(default_factory=list)
    token_budget: Optional[BookImportTokenBudget] = None


class BookImportApplyRequest(BaseModel):
    """确认导入请求（支持前端修订后的数据）"""
    project_suggestion: ProjectSuggestion
    chapters: list[BookImportChapter]
    outlines: list[BookImportOutline] = Field(default_factory=list)
    entity_candidates: list[BookImportEntityCandidate] = Field(
        default_factory=list,
        description="用户确认导入的实体候选；目前仅人物/组织会写入角色与组织表"
    )
    import_mode: ImportMode = Field(default="append", description="导入模式")
    post_import_generation: Literal["auto", "manual"] = Field(
        default="auto",
        description="导入后设定处理：auto=继续AI生成世界观/职业/角色，manual=跳过AI生成由用户手动填写"
    )


class BookImportApplyResponse(BaseModel):
    """确认导入响应"""
    success: bool
    project_id: str
    statistics: dict[str, int]
    warnings: list[BookImportWarning] = Field(default_factory=list)


class BookImportRetryRequest(BaseModel):
    """重试失败步骤请求"""
    steps: list[str] = Field(..., min_length=1, description="需要重试的步骤名列表，如 world_building / career_system / characters")
