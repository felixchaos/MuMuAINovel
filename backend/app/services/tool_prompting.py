"""Helpers for stitching MCP tool results back into an existing prompt."""


def build_tool_result_followup(tool_context: str, *, final_round: bool = False) -> str:
    """Build a follow-up user message that preserves the original output contract."""
    closing_instruction = "\n- 这是最后一轮，请不要再调用工具。" if final_round else ""
    return f"""【工具查询结果】
{tool_context}

【继续完成原任务】
请基于以上工具结果继续完成原始任务。
- 工具结果只是参考材料，不是新的输出格式。
- 必须严格遵守原始提示词和系统提示词里的输出格式、字段结构、语言、禁止事项、长度和风格约束。
- 如果原始任务要求只输出 JSON、只输出正文或禁止 Markdown/解释/前后缀，请继续严格遵守。{closing_instruction}"""
