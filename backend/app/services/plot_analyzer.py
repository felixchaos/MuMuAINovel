"""剧情分析服务 - 自动分析章节的钩子、伏笔、冲突等元素"""
from typing import Dict, Any, List, Optional, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai_service import AIService
from app.services.json_helper import loads_json
from app.services.prompt_service import prompt_service, PromptService
from app.logger import get_logger
import json
import re
import asyncio

logger = get_logger(__name__)

# 重试回调类型定义
OnRetryCallback = Callable[[int, int, int, str], Awaitable[None]]
# 参数: (当前重试次数, 最大重试次数, 等待时间秒数, 错误原因)


class PlotAnalyzer:
    """剧情分析器 - 使用AI分析章节内容"""
    
    def __init__(self, ai_service: AIService):
        """
        初始化剧情分析器
        
        Args:
            ai_service: AI服务实例
        """
        self.ai_service = ai_service
        self.last_error: Optional[str] = None
        logger.info("✅ PlotAnalyzer初始化成功")

    @staticmethod
    def _is_non_retryable_ai_error(error: Optional[str]) -> bool:
        if not error:
            return False
        non_retryable_markers = (
            "promptFeedback.blockReason=PROHIBITED_CONTENT",
            "Gemini 请求被拦截",
        )
        return any(marker in error for marker in non_retryable_markers)
    
    async def analyze_chapter(
        self,
        chapter_number: int,
        title: str,
        content: str,
        word_count: int,
        user_id: str = None,
        db: AsyncSession = None,
        max_retries: int = 3,
        existing_foreshadows: Optional[List[Dict[str, Any]]] = None,
        on_retry: Optional[OnRetryCallback] = None,
        characters_info: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        分析单章内容（带重试机制）
        
        Args:
            chapter_number: 章节号
            title: 章节标题
            content: 章节内容
            word_count: 字数
            user_id: 用户ID（用于获取自定义提示词）
            db: 数据库会话（用于查询自定义提示词）
            max_retries: 最大重试次数，默认3次
            existing_foreshadows: 已埋入的伏笔列表（用于回收匹配）
            on_retry: 重试时的回调函数，参数为 (当前重试次数, 最大重试次数, 等待秒数, 错误原因)
            characters_info: 项目角色信息文本（用于角色名称匹配）
        
        Returns:
            分析结果字典,失败返回None
        """
        logger.info(f"🔍 开始分析第{chapter_number}章: {title}")
        self.last_error = None
        
        # 如果内容过长,截取前8000字(避免超token)
        analysis_content = content[:8000] if len(content) > 8000 else content
        
        # 获取自定义提示词模板
        try:
            if user_id and db:
                template = await PromptService.get_template("PLOT_ANALYSIS", user_id, db)
            else:
                # 降级到系统默认模板
                template = PromptService.PLOT_ANALYSIS
        except Exception as e:
            logger.warning(f"⚠️ 获取提示词模板失败，使用默认模板: {str(e)}")
            template = PromptService.PLOT_ANALYSIS
        
        # 格式化已有伏笔列表
        foreshadows_text = self._format_existing_foreshadows(existing_foreshadows)
        
        # 格式化提示词
        prompt = PromptService.format_prompt(
            template,
            chapter_number=chapter_number,
            title=title,
            word_count=word_count,
            content=analysis_content,
            existing_foreshadows=foreshadows_text,
            characters_info=characters_info if characters_info else "（暂无角色信息）"
        )

        if self.ai_service.api_provider == "gemini":
            prompt = (
                "以下任务是虚构中文网络小说的文学结构分析。"
                "请只分析剧情、角色状态、伏笔和叙事结构；"
                "不要扩展、模仿或生成现实伤害内容。\n\n"
                f"{prompt}"
            )
        
        last_error = None
        logger.debug(f"章节分析提示词{prompt}")
        for attempt in range(1, max_retries + 1):
            try:
                # 调用AI进行分析
                logger.info(f"  📡 调用AI分析(内容长度: {len(analysis_content)}字, 尝试 {attempt}/{max_retries})...")
                accumulated_text = ""
                
                try:
                    async for chunk in self.ai_service.generate_text_stream(
                        prompt=prompt,
                        temperature=0.3  # 降低温度以获得更稳定的JSON输出
                    ):
                        accumulated_text += chunk
                except GeneratorExit:
                    # 流式响应被中断
                    logger.warning(f"⚠️ 流式响应被中断(GeneratorExit)，已累积 {len(accumulated_text)} 字符")
                    # 如果已经累积了足够内容，继续尝试解析
                    if len(accumulated_text) < 100:
                        raise Exception("流式响应中断，内容不足")
                except Exception as stream_error:
                    logger.error(f"❌ 流式生成出错: {str(stream_error)}")
                    raise
                
                # 检查响应是否为空
                if not accumulated_text or len(accumulated_text.strip()) < 10:
                    logger.warning(f"⚠️ AI响应为空或过短(长度: {len(accumulated_text)}), 尝试 {attempt}/{max_retries}")
                    last_error = "AI响应为空或过短"
                    self.last_error = last_error
                    if attempt < max_retries:
                        wait_time = min(2 ** attempt, 10)
                        logger.info(f"  ⏳ 等待 {wait_time} 秒后重试...")
                        # 调用重试回调，通知调用方正在重试
                        if on_retry:
                            try:
                                await on_retry(attempt, max_retries, wait_time, last_error)
                            except Exception as callback_error:
                                logger.warning(f"⚠️ 重试回调执行失败: {callback_error}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"❌ 第{chapter_number}章分析失败: AI响应为空，已达最大重试次数")
                        return None
                
                # 提取内容
                response_text = accumulated_text
                logger.debug(f"  收到AI响应，长度: {len(response_text)} 字符")
                
                # 解析JSON结果
                analysis_result = self._parse_analysis_response(response_text)
                
                if analysis_result:
                    logger.info(f"✅ 第{chapter_number}章分析完成 (尝试 {attempt}/{max_retries})")
                    logger.info(f"  - 钩子: {len(analysis_result.get('hooks', []))}个")
                    logger.info(f"  - 伏笔: {len(analysis_result.get('foreshadows', []))}个")
                    logger.info(f"  - 情节点: {len(analysis_result.get('plot_points', []))}个")
                    logger.info(f"  - 整体评分: {analysis_result.get('scores', {}).get('overall', 'N/A')}")
                    return analysis_result
                else:
                    # JSON解析失败，重试
                    logger.warning(f"⚠️ JSON解析失败, 尝试 {attempt}/{max_retries}")
                    last_error = "JSON解析失败"
                    self.last_error = last_error
                    if attempt < max_retries:
                        wait_time = min(2 ** attempt, 10)
                        logger.info(f"  ⏳ 等待 {wait_time} 秒后重试...")
                        # 调用重试回调，通知调用方正在重试
                        if on_retry:
                            try:
                                await on_retry(attempt, max_retries, wait_time, last_error)
                            except Exception as callback_error:
                                logger.warning(f"⚠️ 重试回调执行失败: {callback_error}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"❌ 第{chapter_number}章分析失败: JSON解析错误，已达最大重试次数")
                        return None
                    
            except Exception as e:
                last_error = str(e)
                self.last_error = last_error
                logger.error(f"❌ 章节分析异常(尝试 {attempt}/{max_retries}): {last_error}")

                if self._is_non_retryable_ai_error(last_error):
                    logger.error(f"❌ 第{chapter_number}章分析失败: {last_error}，该错误不可通过重试恢复")
                    return None
                
                if attempt < max_retries:
                    wait_time = min(2 ** attempt, 10)
                    logger.info(f"  ⏳ 等待 {wait_time} 秒后重试...")
                    # 调用重试回调，通知调用方正在重试
                    if on_retry:
                        try:
                            await on_retry(attempt, max_retries, wait_time, last_error)
                        except Exception as callback_error:
                            logger.warning(f"⚠️ 重试回调执行失败: {callback_error}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ 第{chapter_number}章分析失败: {last_error}，已达最大重试次数")
                    return None
        
        # 不应该到达这里，但作为安全措施
        logger.error(f"❌ 第{chapter_number}章分析失败: {last_error}")
        self.last_error = last_error
        return None
    
    def _format_existing_foreshadows(self, foreshadows: Optional[List[Dict[str, Any]]]) -> str:
        """
        格式化已有伏笔列表，用于注入到分析提示词中
        
        核心策略（重构版）：
        - 分层展示所有已埋入伏笔，让AI能识别"自然回收"
        - 第1层：本章必须回收的伏笔（最详细）
        - 第2层：超期伏笔（较详细）
        - 第3层：其他已埋入伏笔（精简信息，供AI判断是否自然回收了）
        
        Args:
            foreshadows: 伏笔列表，每个包含 id, title, content, plant_chapter_number, resolve_status 等
        
        Returns:
            格式化的文本
        """
        if not foreshadows:
            return "（暂无已埋入的伏笔）"
        
        # 分类伏笔
        must_resolve = [fs for fs in foreshadows if fs.get('resolve_status') == 'must_resolve_now']
        overdue = [fs for fs in foreshadows if fs.get('resolve_status') == 'overdue']
        others = [fs for fs in foreshadows if fs.get('resolve_status') not in ('must_resolve_now', 'overdue')]
        
        lines = []
        
        # === 第1层：本章必须回收的伏笔（最详细）===
        if must_resolve:
            lines.append("=" * 40)
            lines.append("【🎯 本章必须回收的伏笔】")
            lines.append("=" * 40)
            for i, fs in enumerate(must_resolve, 1):
                fs_id = fs.get('id', 'unknown')
                fs_title = fs.get('title', '未命名伏笔')
                fs_content = fs.get('content', '')[:200]
                plant_chapter = fs.get('plant_chapter_number', '?')
                hint_text = fs.get('hint_text', '')
                
                lines.append(f"{i}. 【ID: {fs_id}】{fs_title}")
                lines.append(f"   埋入章节：第{plant_chapter}章")
                lines.append(f"   伏笔内容：{fs_content}{'...' if len(fs.get('content', '')) > 200 else ''}")
                if hint_text:
                    lines.append(f"   埋入暗示：{hint_text[:100]}")
                lines.append(f"   ⚠️ 回收时 reference_foreshadow_id 填写: {fs_id}")
                lines.append("")
        
        # === 第2层：超期伏笔 ===
        if overdue:
            lines.append("【⚠️ 超期未回收伏笔 - 如章节内容回收了请标记】")
            for fs in overdue[:5]:
                fs_id = fs.get('id', 'unknown')
                fs_title = fs.get('title', '')
                plant_chapter = fs.get('plant_chapter_number', '?')
                lines.append(f"- 【ID: {fs_id}】{fs_title}（第{plant_chapter}章埋入）")
            lines.append("")
        
        # === 第3层：其他已埋入伏笔（精简）===
        if others:
            lines.append("【📋 其他已埋入伏笔 - 如章节内容自然回收了请标记】")
            for fs in others[:10]:
                fs_id = fs.get('id', 'unknown')
                fs_title = fs.get('title', '')
                plant_chapter = fs.get('plant_chapter_number', '?')
                lines.append(f"- 【ID: {fs_id}】{fs_title}（第{plant_chapter}章埋入）")
            if len(others) > 10:
                lines.append(f"  ... 还有{len(others) - 10}个伏笔未列出")
            lines.append("")
        
        # 操作指引
        lines.append("提示：如果章节内容回收了上述任一伏笔，请在 foreshadows 数组中")
        lines.append("添加 type='resolved' 的记录，并在 reference_foreshadow_id 填写对应ID。")
        
        return "\n".join(lines)
    
    def _parse_analysis_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        解析AI返回的分析结果（使用统一的JSON清洗方法）
        
        Args:
            response: AI返回的文本
        
        Returns:
            解析后的字典,失败返回None
        """
        try:
            # 使用统一的JSON清洗方法
            cleaned = self.ai_service._clean_json_response(response)
            
            # 尝试解析JSON
            result = loads_json(cleaned)
            
            # 验证必要字段
            required_fields = ['hooks', 'plot_points', 'scores']
            for field in required_fields:
                if field not in result:
                    logger.warning(f"⚠️ 分析结果缺少字段: {field}")
                    result[field] = [] if field != 'scores' else {}
            
            logger.info("✅ 成功解析分析结果")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON解析失败: {str(e)}")
            logger.error(f"  原始响应(前500字): {response[:500]}")
            return None
        except Exception as e:
            logger.error(f"❌ 解析异常: {str(e)}")
            return None
    
    def extract_memories_from_analysis(
        self,
        analysis: Dict[str, Any],
        chapter_id: str,
        chapter_number: int,
        chapter_content: str = "",
        chapter_title: str = ""
    ) -> List[Dict[str, Any]]:
        """
        从分析结果中提取记忆片段
        
        Args:
            analysis: 分析结果
            chapter_id: 章节ID
            chapter_number: 章节号
            chapter_content: 章节完整内容(用于计算位置)
            chapter_title: 章节标题
        
        Returns:
            记忆片段列表
        """
        memories = []
        
        try:
            # 【新增】0. 提取章节摘要作为记忆（用于语义检索相关章节）
            chapter_summary = ""
            
            # 尝试从分析结果获取摘要
            if analysis.get('summary'):
                chapter_summary = analysis.get('summary')
            # 或者从情节点组合生成摘要
            elif analysis.get('plot_points'):
                plot_summaries = [p.get('content', '') for p in analysis.get('plot_points', [])[:3]]
                chapter_summary = "；".join(plot_summaries)
            # 或者使用内容前300字
            elif chapter_content:
                chapter_summary = chapter_content[:300] + ("..." if len(chapter_content) > 300 else "")
            
            # 如果有摘要，添加到记忆中
            if chapter_summary:
                memories.append({
                    'type': 'chapter_summary',
                    'content': chapter_summary,
                    'title': f"第{chapter_number}章《{chapter_title}》摘要",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': 0.6,  # 中等重要性
                        'tags': ['摘要', '章节概览', chapter_title],
                        'is_foreshadow': 0,
                        'text_position': 0,
                        'text_length': len(chapter_summary)
                    }
                })
                logger.info(f"  ✅ 添加章节摘要记忆: {len(chapter_summary)}字")
            
            # 1. 提取钩子作为记忆
            for i, hook in enumerate(analysis.get('hooks', [])):
                if hook.get('strength', 0) >= 6:  # 只保存强度>=6的钩子
                    keyword = hook.get('keyword', '')
                    position, length = self._find_text_position(chapter_content, keyword)
                    
                    logger.info(f"  钩子位置: keyword='{keyword[:30]}...', pos={position}, len={length}")
                    
                    memories.append({
                        'type': 'hook',
                        'content': f"[{hook.get('type', '未知')}钩子] {hook.get('content', '')}",
                        'title': f"{hook.get('type', '钩子')} - {hook.get('position', '')}",
                        'metadata': {
                            'chapter_id': chapter_id,
                            'chapter_number': chapter_number,
                            'importance_score': min(hook.get('strength', 5) / 10, 1.0),
                            'tags': [hook.get('type', '钩子'), hook.get('position', '')],
                            'is_foreshadow': 0,
                            'keyword': keyword,
                            'text_position': position,
                            'text_length': length,
                            'strength': hook.get('strength', 5),
                            'position_desc': hook.get('position', '')
                        }
                    })
            
            # 2. 提取伏笔作为记忆
            for i, foreshadow in enumerate(analysis.get('foreshadows', [])):
                is_planted = foreshadow.get('type') == 'planted'
                keyword = foreshadow.get('keyword', '')
                position, length = self._find_text_position(chapter_content, keyword)
                
                logger.info(f"  伏笔位置: keyword='{keyword[:30]}...', pos={position}, len={length}")
                
                memories.append({
                    'type': 'foreshadow',
                    'content': foreshadow.get('content', ''),
                    'title': f"{'埋下伏笔' if is_planted else '回收伏笔'}",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': min(foreshadow.get('strength', 5) / 10, 1.0),
                        'tags': ['伏笔', foreshadow.get('type', 'planted')],
                        'is_foreshadow': 1 if is_planted else 2,
                        'reference_chapter': foreshadow.get('reference_chapter'),
                        'keyword': keyword,
                        'text_position': position,
                        'text_length': length,
                        'foreshadow_type': foreshadow.get('type', 'planted'),
                        'strength': foreshadow.get('strength', 5)
                    }
                })
            
            # 3. 提取关键情节点
            for i, plot_point in enumerate(analysis.get('plot_points', [])):
                if plot_point.get('importance', 0) >= 0.6:  # 只保存重要性>=0.6的情节点
                    keyword = plot_point.get('keyword', '')
                    position, length = self._find_text_position(chapter_content, keyword)
                    
                    logger.info(f"  情节点位置: keyword='{keyword[:30]}...', pos={position}, len={length}")
                    
                    memories.append({
                        'type': 'plot_point',
                        'content': f"{plot_point.get('content', '')}。影响: {plot_point.get('impact', '')}",
                        'title': f"情节点 - {plot_point.get('type', '未知')}",
                        'metadata': {
                            'chapter_id': chapter_id,
                            'chapter_number': chapter_number,
                            'importance_score': plot_point.get('importance', 0.5),
                            'tags': ['情节点', plot_point.get('type', '未知')],
                            'is_foreshadow': 0,
                            'keyword': keyword,
                            'text_position': position,
                            'text_length': length
                        }
                    })
            
            # 4. 提取角色状态变化
            for i, char_state in enumerate(analysis.get('character_states', [])):
                char_name = char_state.get('character_name', '未知角色')
                memories.append({
                    'type': 'character_event',
                    'content': f"{char_name}的状态变化: {char_state.get('state_before', '')} → {char_state.get('state_after', '')}。{char_state.get('psychological_change', '')}",
                    'title': f"{char_name}的变化",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': 0.7,
                        'tags': ['角色', char_name, '状态变化'],
                        'related_characters': [char_name],
                        'is_foreshadow': 0
                    }
                })

            # 5. 提取场景事实，供后续续写/重写保持地点与氛围连续
            for i, scene in enumerate(analysis.get('scenes', [])):
                if isinstance(scene, dict):
                    location = str(scene.get('location') or '').strip()
                    atmosphere = str(scene.get('atmosphere') or '').strip()
                    duration = str(scene.get('duration') or '').strip()
                    keyword = str(scene.get('keyword') or location or atmosphere or '').strip()
                else:
                    location = str(scene or '').strip()
                    atmosphere = ''
                    duration = ''
                    keyword = location
                if not any([location, atmosphere, duration]):
                    continue

                position, length = self._find_text_position(chapter_content, keyword)
                content_parts = [
                    f"地点: {location}" if location else "",
                    f"氛围: {atmosphere}" if atmosphere else "",
                    f"时长: {duration}" if duration else "",
                ]
                memories.append({
                    'type': 'scene',
                    'content': "；".join(part for part in content_parts if part),
                    'title': f"场景 - {location or f'第{i + 1}个场景'}",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': 0.55,
                        'tags': ['场景', location, atmosphere],
                        'related_locations': [location] if location else [],
                        'is_foreshadow': 0,
                        'keyword': keyword,
                        'text_position': position,
                        'text_length': length
                    }
                })

            # 6. 提取组织自身变化，避免只更新当前组织状态而丢失历史事实
            for i, org_state in enumerate(analysis.get('organization_states', [])):
                if not isinstance(org_state, dict):
                    continue
                org_name = str(org_state.get('organization_name') or '未知组织').strip()
                key_event = str(org_state.get('key_event') or '').strip()
                status_description = str(org_state.get('status_description') or '').strip()
                keyword = key_event or org_name
                position, length = self._find_text_position(chapter_content, keyword)
                content_parts = [
                    f"{org_name}状态变化",
                    status_description,
                    f"势力变化: {org_state.get('power_change')}" if org_state.get('power_change') is not None else "",
                    f"新据点: {org_state.get('new_location')}" if org_state.get('new_location') else "",
                    f"新目标: {org_state.get('new_purpose')}" if org_state.get('new_purpose') else "",
                    f"关键事件: {key_event}" if key_event else "",
                ]
                memories.append({
                    'type': 'organization_event',
                    'content': "；".join(part for part in content_parts if part),
                    'title': f"{org_name}组织变化",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': 0.7,
                        'tags': ['组织', org_name, '状态变化'],
                        'related_characters': [org_name],
                        'related_locations': [org_state.get('new_location')] if org_state.get('new_location') else [],
                        'is_foreshadow': 0,
                        'keyword': keyword,
                        'text_position': position,
                        'text_length': length,
                        'is_destroyed': bool(org_state.get('is_destroyed'))
                    }
                })

            # 7. 提取明确世界观事实/规则声明，只记录原文明确给出的稳定设定
            for i, fact in enumerate(analysis.get('worldbuilding_facts', [])):
                if isinstance(fact, dict):
                    content = str(fact.get('content') or '').strip()
                    category = str(fact.get('category') or '世界观').strip()
                    keyword = str(fact.get('keyword') or content[:25]).strip()
                    location = str(fact.get('location') or '').strip()
                    impact = str(fact.get('impact') or '').strip()
                else:
                    content = str(fact or '').strip()
                    category = '世界观'
                    keyword = content[:25]
                    location = ''
                    impact = ''
                if not content:
                    continue

                position, length = self._find_text_position(chapter_content, keyword)
                memories.append({
                    'type': 'world_detail',
                    'content': f"{content}{'。影响: ' + impact if impact else ''}",
                    'title': f"世界观设定 - {category}",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': 0.65,
                        'tags': ['世界观', category],
                        'related_locations': [location] if location else [],
                        'is_foreshadow': 0,
                        'keyword': keyword,
                        'text_position': position,
                        'text_length': length
                    }
                })

            # 8. 如果有重要冲突,也记录下来
            conflict = analysis.get('conflict', {})
            
            if conflict and conflict.get('level', 0) >= 7:
                # 确保 parties 和 types 都是字符串列表
                parties = conflict.get('parties', [])
                if parties and isinstance(parties, list):
                    parties = [str(p) for p in parties]
                
                types = conflict.get('types', [])
                if types and isinstance(types, list):
                    types = [str(t) for t in types]
                
                memories.append({
                    'type': 'plot_point',
                    'content': f"重要冲突: {conflict.get('description', '')}。冲突各方: {', '.join(parties)}",
                    'title': f"冲突 - 强度{conflict.get('level', 0)}",
                    'metadata': {
                        'chapter_id': chapter_id,
                        'chapter_number': chapter_number,
                        'importance_score': min(conflict.get('level', 5) / 10, 1.0),
                        'tags': ['冲突'] + types,
                        'is_foreshadow': 0
                    }
                })
            
            logger.info(f"📝 从分析中提取了{len(memories)}条记忆")
            return memories
            
        except Exception as e:
            logger.error(f"❌ 提取记忆失败: {str(e)}")
            return []
    
    def _find_text_position(self, full_text: str, keyword: str) -> tuple[int, int]:
        """
        在全文中查找关键词位置
        
        Args:
            full_text: 完整文本
            keyword: 关键词
        
        Returns:
            (起始位置, 长度) 如果未找到返回(-1, 0)
        """
        if not keyword or not full_text:
            return (-1, 0)
        
        try:
            # 1. 精确匹配
            pos = full_text.find(keyword)
            if pos != -1:
                return (pos, len(keyword))
            
            # 2. 去除标点符号后匹配
            import re
            clean_keyword = re.sub(r'[，。！？、；：""''（）《》【】]', '', keyword)
            clean_text = re.sub(r'[，。！？、；：""''（）《》【】]', '', full_text)
            pos = clean_text.find(clean_keyword)
            
            if pos != -1:
                # 反向映射到原文位置（简化处理）
                return (pos, len(clean_keyword))
            
            # 3. 模糊匹配：查找关键词的前半部分
            if len(keyword) > 10:
                partial = keyword[:min(15, len(keyword))]
                pos = full_text.find(partial)
                if pos != -1:
                    return (pos, len(partial))
            
            # 4. 未找到
            logger.debug(f"未找到关键词位置: {keyword[:30]}...")
            return (-1, 0)
            
        except Exception as e:
            logger.error(f"查找位置失败: {str(e)}")
            return (-1, 0)
    
    def generate_analysis_summary(self, analysis: Dict[str, Any]) -> str:
        """
        生成分析摘要文本
        
        Args:
            analysis: 分析结果
        
        Returns:
            格式化的摘要文本
        """
        try:
            lines = ["=== 章节分析报告 ===\n"]
            
            # 整体评分
            scores = analysis.get('scores', {})
            lines.append(f"【整体评分】")
            lines.append(f"  整体质量: {scores.get('overall', 'N/A')}/10")
            lines.append(f"  节奏把控: {scores.get('pacing', 'N/A')}/10")
            lines.append(f"  吸引力: {scores.get('engagement', 'N/A')}/10")
            lines.append(f"  连贯性: {scores.get('coherence', 'N/A')}/10\n")
            
            # 剧情阶段
            lines.append(f"【剧情阶段】{analysis.get('plot_stage', '未知')}\n")
            
            # 钩子统计
            hooks = analysis.get('hooks', [])
            if hooks:
                lines.append(f"【钩子分析】共{len(hooks)}个")
                for hook in hooks[:3]:  # 只显示前3个
                    lines.append(f"  • [{hook.get('type')}] {hook.get('content', '')[:50]}... (强度:{hook.get('strength', 0)})")
                lines.append("")
            
            # 伏笔统计
            foreshadows = analysis.get('foreshadows', [])
            if foreshadows:
                planted = sum(1 for f in foreshadows if f.get('type') == 'planted')
                resolved = sum(1 for f in foreshadows if f.get('type') == 'resolved')
                lines.append(f"【伏笔分析】埋下{planted}个, 回收{resolved}个\n")
            
            # 冲突分析
            conflict = analysis.get('conflict', {})
            if conflict:
                lines.append(f"【冲突分析】")
                lines.append(f"  类型: {', '.join(conflict.get('types', []))}")
                lines.append(f"  强度: {conflict.get('level', 0)}/10")
                lines.append(f"  进度: {int(conflict.get('resolution_progress', 0) * 100)}%\n")
            
            # 改进建议
            suggestions = analysis.get('suggestions', [])
            if suggestions:
                lines.append(f"【改进建议】")
                for i, sug in enumerate(suggestions, 1):
                    lines.append(f"  {i}. {sug}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"❌ 生成摘要失败: {str(e)}")
            return "分析摘要生成失败"


# 创建全局实例(需要时手动初始化)
_plot_analyzer_instance = None

def get_plot_analyzer(ai_service: AIService) -> PlotAnalyzer:
    """获取剧情分析器实例"""
    global _plot_analyzer_instance
    if _plot_analyzer_instance is None:
        _plot_analyzer_instance = PlotAnalyzer(ai_service)
    return _plot_analyzer_instance
