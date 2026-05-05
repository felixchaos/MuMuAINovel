"""灵感模式API - 通过对话引导创建项目"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any
import json

from app.database import get_db
from app.services.ai_service import AIService
from app.services.json_helper import loads_json
from app.api.settings import get_user_ai_service
from app.services.prompt_service import PromptService
from app.logger import get_logger

router = APIRouter(prefix="/inspiration", tags=["灵感模式"])
logger = get_logger(__name__)


# 不同阶段的temperature设置（递减以保持一致性）
TEMPERATURE_SETTINGS = {
    "title": 0.8,        # 书名阶段可以更有创意
    "description": 0.65, # 简介需要贴合书名和原始想法
    "theme": 0.55,       # 主题需要更加贴合
    "genre": 0.45        # 类型应该很明确
}


def validate_options_response(result: Dict[str, Any], step: str, max_retries: int = 3) -> tuple[bool, str]:
    """
    校验AI返回的选项格式是否正确
    
    Returns:
        (is_valid, error_message)
    """
    # 检查必需字段
    if "options" not in result:
        return False, "缺少options字段"
    
    options = result.get("options", [])
    
    # 检查options是否为数组
    if not isinstance(options, list):
        return False, "options必须是数组"
    
    # 检查数组长度
    if len(options) < 3:
        return False, f"选项数量不足，至少需要3个，当前只有{len(options)}个"
    
    if len(options) > 10:
        return False, f"选项数量过多，最多10个，当前有{len(options)}个"
    
    # 检查每个选项是否为字符串且不为空
    for i, option in enumerate(options):
        if not isinstance(option, str):
            return False, f"第{i+1}个选项不是字符串类型"
        if not option.strip():
            return False, f"第{i+1}个选项为空"
        if len(option) > 500:
            return False, f"第{i+1}个选项过长（超过500字符）"
    
    # 根据不同步骤进行特定校验
    if step == "genre":
        # 类型标签应该比较短
        for i, option in enumerate(options):
            if len(option) > 10:
                return False, f"类型标签【{option}】过长，应该在2-10字之间"
    
    return True, ""


def _append_inspiration_control_blocks(system_prompt: str, *blocks: str) -> str:
    """集中追加灵感模式的动态控制块，便于审计最终生效提示词。"""
    parts = [system_prompt.strip()]
    parts.extend(block.strip() for block in blocks if block and block.strip())
    return "\n\n".join(parts)


def _build_inspiration_retry_guardrail(attempt: int, *, require_option_count: bool) -> str:
    if attempt <= 0:
        return ""

    option_count_clause = "，确保 options 数组包含 6 个有效选项" if require_option_count else ""
    return (
        "【灵感模式重试约束】\n"
        f"这是第{attempt + 1}次生成，请务必严格按照 JSON 格式返回{option_count_clause}。"
    )


def _build_inspiration_feedback_guardrail(feedback: str, previous_options: Any) -> str:
    options = previous_options if isinstance(previous_options, list) else []
    option_lines = [
        f"- {str(option).strip()}"
        for option in options
        if str(option).strip()
    ]
    previous_options_text = "\n".join(option_lines) or "（无）"
    feedback_text = (feedback or "").strip() or "（无具体反馈）"

    return f"""【用户反馈调整】
用户对之前的选项不太满意，提供了以下反馈：
「{feedback_text}」

之前生成的选项：
{previous_options_text}

请根据用户反馈调整生成策略，提供更符合用户期望的新选项。
要求：
1. 仔细理解用户的反馈意图
2. 新选项要明显体现用户要求的调整方向
3. 保持与已有上下文的一致性
4. 确保返回 6 个有效选项"""


@router.post("/generate-options")
async def generate_options(
    data: Dict[str, Any],
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    ai_service: AIService = Depends(get_user_ai_service)
) -> Dict[str, Any]:
    """
    根据当前收集的信息生成下一步的选项建议（带自动重试）
    
    Request:
        {
            "step": "title",  // title/description/theme/genre
            "context": {
                "title": "...",
                "description": "...",
                "theme": "..."
            }
        }
    
    Response:
        {
            "prompt": "引导语",
            "options": ["选项1", "选项2", ...]
        }
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            step = data.get("step", "title")
            context = data.get("context", {})
            
            logger.info(f"灵感模式：生成{step}阶段的选项（第{attempt + 1}次尝试）")
            
            # 获取用户ID
            user_id = getattr(http_request.state, 'user_id', None)
            
            # 获取对应的提示词模板（根据step确定模板key）
            # 新结构：每个步骤有独立的 SYSTEM 和 USER 模板
            template_key_map = {
                "title": ("INSPIRATION_TITLE_SYSTEM", "INSPIRATION_TITLE_USER"),
                "description": ("INSPIRATION_DESCRIPTION_SYSTEM", "INSPIRATION_DESCRIPTION_USER"),
                "theme": ("INSPIRATION_THEME_SYSTEM", "INSPIRATION_THEME_USER"),
                "genre": ("INSPIRATION_GENRE_SYSTEM", "INSPIRATION_GENRE_USER")
            }
            template_keys = template_key_map.get(step)
            
            if not template_keys:
                return {
                    "error": f"不支持的步骤: {step}",
                    "prompt": "",
                    "options": []
                }
            
            system_key, user_key = template_keys
            
            # 获取自定义提示词模板（分别获取 system 和 user）
            system_template = await PromptService.get_template(system_key, user_id, db)
            user_template = await PromptService.get_template(user_key, user_id, db)
            
            # 准备格式化参数
            format_params = {
                "initial_idea": context.get("initial_idea", context.get("description", "")),
                "title": context.get("title", ""),
                "description": context.get("description", ""),
                "theme": context.get("theme", "")
            }
            
            # 格式化提示词
            system_prompt = system_template.format(**format_params)
            user_prompt = user_template.format(**format_params)
            
            system_prompt = _append_inspiration_control_blocks(
                system_prompt,
                _build_inspiration_retry_guardrail(attempt, require_option_count=True),
            )
            
            # 调用AI生成选项
            # 关键改进：使用递减的temperature以保持后续阶段与前文的一致性
            temperature = TEMPERATURE_SETTINGS.get(step, 0.7)
            logger.info(f"调用AI生成{step}选项... (temperature={temperature})")
            
            # 流式生成并累积文本
            accumulated_text = ""
            async for chunk in ai_service.generate_text_stream(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature
            ):
                accumulated_text += chunk
            
            response = {"content": accumulated_text}
            content = accumulated_text
            logger.info(f"AI返回内容长度: {len(content)}")
            
            # 解析JSON（使用统一的JSON清洗方法）
            try:
                # 使用统一的JSON清洗方法
                cleaned_content = ai_service._clean_json_response(content)
                
                result = loads_json(cleaned_content)
                
                # 校验返回格式
                is_valid, error_msg = validate_options_response(result, step)
                
                if not is_valid:
                    logger.warning(f"⚠️ 第{attempt + 1}次生成格式校验失败: {error_msg}")
                    if attempt < max_retries - 1:
                        logger.info("准备重试...")
                        continue  # 重试
                    else:
                        # 最后一次尝试也失败了
                        return {
                            "prompt": f"请为【{step}】提供内容：",
                            "options": ["让AI重新生成", "我自己输入"],
                            "error": f"AI生成格式错误（{error_msg}），已自动重试{max_retries}次，请手动重试或自己输入"
                        }
                
                logger.info(f"✅ 第{attempt + 1}次成功生成{len(result.get('options', []))}个有效选项")
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"第{attempt + 1}次JSON解析失败: {e}")
                
                if attempt < max_retries - 1:
                    logger.info("JSON解析失败，准备重试...")
                    continue  # 重试
                else:
                    # 最后一次尝试也失败了
                    return {
                        "prompt": f"请为【{step}】提供内容：",
                        "options": ["让AI重新生成", "我自己输入"],
                        "error": f"AI返回格式错误，已自动重试{max_retries}次，请手动重试或自己输入"
                    }
        
        except Exception as e:
            logger.error(f"第{attempt + 1}次生成失败: {e}", exc_info=True)
            if attempt < max_retries - 1:
                logger.info("发生异常，准备重试...")
                continue
            else:
                return {
                    "error": str(e),
                    "prompt": "生成失败，请重试",
                    "options": ["重新生成", "我自己输入"]
                }
    
    # 理论上不会到这里
    return {
        "error": "生成失败",
        "prompt": "请重试",
        "options": []
    }


@router.post("/refine-options")
async def refine_options(
    data: Dict[str, Any],
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    ai_service: AIService = Depends(get_user_ai_service)
) -> Dict[str, Any]:
    """
    基于用户反馈重新生成选项（支持多轮对话）
    
    Request:
        {
            "step": "title",  // 当前步骤
            "context": {
                "initial_idea": "...",
                "title": "...",
                "description": "...",
                "theme": "..."
            },
            "feedback": "我想要更悲剧一些的主题",  // 用户反馈
            "previous_options": ["选项1", "选项2", ...]  // 之前的选项（可选）
        }
    
    Response:
        {
            "prompt": "引导语",
            "options": ["新选项1", "新选项2", ...]
        }
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            step = data.get("step", "title")
            context = data.get("context", {})
            feedback = data.get("feedback", "")
            previous_options = data.get("previous_options", [])
            
            logger.info(f"灵感模式：根据反馈重新生成{step}阶段的选项（第{attempt + 1}次尝试）")
            logger.info(f"用户反馈: {feedback}")
            
            # 获取用户ID
            user_id = getattr(http_request.state, 'user_id', None)
            
            # 获取对应的提示词模板
            template_key_map = {
                "title": ("INSPIRATION_TITLE_SYSTEM", "INSPIRATION_TITLE_USER"),
                "description": ("INSPIRATION_DESCRIPTION_SYSTEM", "INSPIRATION_DESCRIPTION_USER"),
                "theme": ("INSPIRATION_THEME_SYSTEM", "INSPIRATION_THEME_USER"),
                "genre": ("INSPIRATION_GENRE_SYSTEM", "INSPIRATION_GENRE_USER")
            }
            template_keys = template_key_map.get(step)
            
            if not template_keys:
                return {
                    "error": f"不支持的步骤: {step}",
                    "prompt": "",
                    "options": []
                }
            
            system_key, user_key = template_keys
            
            # 获取自定义提示词模板
            system_template = await PromptService.get_template(system_key, user_id, db)
            user_template = await PromptService.get_template(user_key, user_id, db)
            
            # 准备格式化参数
            format_params = {
                "initial_idea": context.get("initial_idea", context.get("description", "")),
                "title": context.get("title", ""),
                "description": context.get("description", ""),
                "theme": context.get("theme", "")
            }
            
            # 格式化提示词
            system_prompt = system_template.format(**format_params)
            user_prompt = user_template.format(**format_params)
            
            system_prompt = _append_inspiration_control_blocks(
                system_prompt,
                _build_inspiration_feedback_guardrail(feedback, previous_options),
                _build_inspiration_retry_guardrail(attempt, require_option_count=False),
            )
            
            # 调用AI生成选项
            temperature = TEMPERATURE_SETTINGS.get(step, 0.7)
            # 反馈生成时使用稍高的temperature以获得更多样化的结果
            temperature = min(temperature + 0.1, 0.9)
            logger.info(f"调用AI根据反馈生成{step}选项... (temperature={temperature})")
            
            # 流式生成并累积文本
            accumulated_text = ""
            async for chunk in ai_service.generate_text_stream(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature
            ):
                accumulated_text += chunk
            
            content = accumulated_text
            logger.info(f"AI返回内容长度: {len(content)}")
            
            # 解析JSON
            try:
                cleaned_content = ai_service._clean_json_response(content)
                result = loads_json(cleaned_content)
                
                # 校验返回格式
                is_valid, error_msg = validate_options_response(result, step)
                
                if not is_valid:
                    logger.warning(f"⚠️ 第{attempt + 1}次生成格式校验失败: {error_msg}")
                    if attempt < max_retries - 1:
                        logger.info("准备重试...")
                        continue
                    else:
                        return {
                            "prompt": f"请为【{step}】提供内容：",
                            "options": ["让AI重新生成", "我自己输入"],
                            "error": f"AI生成格式错误（{error_msg}），已自动重试{max_retries}次"
                        }
                
                logger.info(f"✅ 第{attempt + 1}次根据反馈成功生成{len(result.get('options', []))}个有效选项")
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"第{attempt + 1}次JSON解析失败: {e}")
                
                if attempt < max_retries - 1:
                    logger.info("JSON解析失败，准备重试...")
                    continue
                else:
                    return {
                        "prompt": f"请为【{step}】提供内容：",
                        "options": ["让AI重新生成", "我自己输入"],
                        "error": f"AI返回格式错误，已自动重试{max_retries}次"
                    }
        
        except Exception as e:
            logger.error(f"第{attempt + 1}次根据反馈生成失败: {e}", exc_info=True)
            if attempt < max_retries - 1:
                logger.info("发生异常，准备重试...")
                continue
            else:
                return {
                    "error": str(e),
                    "prompt": "生成失败，请重试",
                    "options": ["重新生成", "我自己输入"]
                }
    
    return {
        "error": "生成失败",
        "prompt": "请重试",
        "options": []
    }


@router.post("/quick-generate")
async def quick_generate(
    data: Dict[str, Any],
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    ai_service: AIService = Depends(get_user_ai_service)
) -> Dict[str, Any]:
    """
    智能补全：根据用户已提供的部分信息，AI自动补全缺失字段
    
    Request:
        {
            "title": "书名（可选）",
            "description": "简介（可选）",
            "theme": "主题（可选）",
            "genre": ["类型1", "类型2"]（可选）
        }
    
    Response:
        {
            "title": "补全的书名",
            "description": "补全的简介",
            "theme": "补全的主题",
            "genre": ["补全的类型"]
        }
    """
    try:
        logger.info("灵感模式：智能补全")
        
        # 获取用户ID
        user_id = getattr(http_request.state, 'user_id', None)
        
        # 构建补全提示词
        existing_info = []
        if data.get("title"):
            existing_info.append(f"- 书名：{data['title']}")
        if data.get("description"):
            existing_info.append(f"- 简介：{data['description']}")
        if data.get("theme"):
            existing_info.append(f"- 主题：{data['theme']}")
        if data.get("genre"):
            existing_info.append(f"- 类型：{', '.join(data['genre'])}")
        
        existing_text = "\n".join(existing_info) if existing_info else "暂无信息"
        
        # 获取自定义提示词模板
        system_template = await PromptService.get_template("INSPIRATION_QUICK_COMPLETE", user_id, db)
        
        # 格式化提示词
        prompts = {
            "system": PromptService.format_prompt(system_template, existing=existing_text),
            "user": "请补全小说信息"
        }
        
        # 调用AI - 流式生成并累积文本
        accumulated_text = ""
        async for chunk in ai_service.generate_text_stream(
            prompt=prompts["user"],
            system_prompt=prompts["system"],
            temperature=0.7
        ):
            accumulated_text += chunk
        
        response = {"content": accumulated_text}
        content = accumulated_text
        
        # 解析JSON（使用统一的JSON清洗方法）
        try:
            # 使用统一的JSON清洗方法
            cleaned_content = ai_service._clean_json_response(content)
            
            result = loads_json(cleaned_content)
            
            # 合并用户已提供的信息（用户输入优先）
            final_result = {
                "title": data.get("title") or result.get("title", ""),
                "description": data.get("description") or result.get("description", ""),
                "theme": data.get("theme") or result.get("theme", ""),
                "genre": data.get("genre") or result.get("genre", [])
            }
            
            logger.info(f"✅ 智能补全成功")
            return final_result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            raise Exception("AI返回格式错误，请重试")
    
    except Exception as e:
        logger.error(f"智能补全失败: {e}", exc_info=True)
        return {
            "error": str(e)
        }
