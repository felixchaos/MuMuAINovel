"""Gemini 客户端"""
from typing import Any, AsyncGenerator, Dict, List, Optional
import json
import httpx
from app.services.ai_config import AIClientConfig, default_config
from app.logger import get_logger

logger = get_logger(__name__)


class GeminiResponseError(ValueError):
    """Gemini 返回了非 HTTP 错误，但没有可用正文。"""


class GeminiPromptBlockedError(GeminiResponseError):
    """Gemini 在 promptFeedback 层拦截了请求。"""


class GeminiClient:
    """Google Gemini API 客户端"""

    def __init__(self, api_key: str, base_url: Optional[str] = None, config: Optional[AIClientConfig] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.config = config or default_config
        http_cfg = self.config.http
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=http_cfg.connect_timeout,
                read=http_cfg.read_timeout,
                write=http_cfg.write_timeout,
                pool=http_cfg.pool_timeout
            )
        )

    def _convert_tools_to_gemini(self, tools: list) -> list:
        """将 OpenAI 格式工具转换为 Gemini 格式"""
        gemini_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                params = func.get("parameters", {}).copy() if func.get("parameters") else {}
                params.pop("$schema", None)
                params.pop("additionalProperties", None)
                if params and "type" not in params:
                    params["type"] = "object"
                decl = {
                    "name": func["name"],
                    "description": func.get("description") or func["name"],
                }
                if params:
                    decl["parameters"] = params
                gemini_tools.append(decl)
        return [{"functionDeclarations": gemini_tools}] if gemini_tools else []

    def _normalize_finish_reason(self, finish_reason: Optional[str]) -> str:
        mapping = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "safety",
            "RECITATION": "recitation",
            "OTHER": "other",
            "BLOCKLIST": "blocklist",
            "PROHIBITED_CONTENT": "prohibited_content",
            "SPII": "spii",
            "MALFORMED_FUNCTION_CALL": "malformed_function_call",
        }
        if not finish_reason:
            return "stop"
        return mapping.get(finish_reason, finish_reason.lower())

    def _compact_safety_ratings(self, ratings: Optional[list]) -> str:
        if not ratings:
            return ""
        compact = []
        for rating in ratings[:6]:
            category = rating.get("category")
            probability = rating.get("probability")
            blocked = rating.get("blocked")
            parts = [str(x) for x in (category, probability) if x]
            if blocked is True:
                parts.append("blocked=True")
            if parts:
                compact.append("/".join(parts))
        return "; ".join(compact)

    def _usage_from_metadata(self, usage: Dict[str, Any]) -> Dict[str, Optional[int]]:
        return {
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
        }

    def _raise_for_prompt_block(self, data: Dict[str, Any]) -> None:
        prompt_feedback = data.get("promptFeedback") or {}
        block_reason = prompt_feedback.get("blockReason")
        if not block_reason:
            return

        ratings = self._compact_safety_ratings(prompt_feedback.get("safetyRatings"))
        message = f"Gemini 请求被拦截: promptFeedback.blockReason={block_reason}"
        if ratings:
            message += f", safetyRatings={ratings}"
        raise GeminiPromptBlockedError(message)

    def _raise_for_empty_candidate(self, candidate: Dict[str, Any]) -> None:
        finish_reason = candidate.get("finishReason")
        ratings = self._compact_safety_ratings(candidate.get("safetyRatings"))
        message = f"Gemini 返回空候选: finishReason={finish_reason or 'UNKNOWN'}"
        if ratings:
            message += f", safetyRatings={ratings}"
        raise GeminiResponseError(message)

    async def chat_completion(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            payload["tools"] = self._convert_tools_to_gemini(tools)

        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        self._raise_for_prompt_block(data)
        
        candidates = data.get("candidates", [])
        if not candidates or len(candidates) == 0:
            raise GeminiResponseError("Gemini 返回空 candidates")
        
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = ""
        tool_calls = []
        
        for part in parts:
            if "text" in part:
                text += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{fc['name']}",
                    "type": "function",
                    "function": {"name": fc["name"], "arguments": fc.get("args", {})}
                })

        if not text and not tool_calls:
            self._raise_for_empty_candidate(candidate)
        
        usage = data.get("usageMetadata") or {}
        return {
            "content": text,
            "tool_calls": tool_calls if tool_calls else None,
            "finish_reason": "tool_calls" if tool_calls else self._normalize_finish_reason(candidate.get("finishReason")),
            "usage": self._usage_from_metadata(usage)
        }

    async def chat_completion_stream(
        self,
        messages: list,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str] = None,
        tools: Optional[list] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式生成，支持工具调用
        
        Yields:
            Dict with keys:
            - content: str - 文本内容块
            - tool_calls: list - 工具调用列表（如果有）
            - done: bool - 是否结束
        """
        url = f"{self.base_url}/models/{model}:streamGenerateContent?key={self.api_key}&alt=sse"
        
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            payload["tools"] = self._convert_tools_to_gemini(tools)

        try:
            async with self.client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                try:
                    saw_content = False
                    saw_tool_calls = False
                    saw_finish_reason = False

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                usage = data.get("usageMetadata") or {}
                                if usage:
                                    yield {"usage": self._usage_from_metadata(usage)}

                                self._raise_for_prompt_block(data)

                                candidates = data.get("candidates", [])
                                if candidates and len(candidates) > 0:
                                    candidate = candidates[0]
                                    parts = candidate.get("content", {}).get("parts", [])
                                    finish_reason = candidate.get("finishReason")
                                    if parts and len(parts) > 0:
                                        text = ""
                                        function_calls = []
                                        for part in parts:
                                            if "text" in part:
                                                text += part["text"]
                                            elif "functionCall" in part:
                                                fc = part["functionCall"]
                                                function_calls.append({
                                                    "id": f"call_{fc['name']}",
                                                    "type": "function",
                                                    "function": {
                                                        "name": fc["name"],
                                                        "arguments": fc.get("args", {})
                                                    }
                                                })
                                        
                                        if text:
                                            saw_content = True
                                            yield {"content": text}
                                        if function_calls:
                                            saw_tool_calls = True
                                            yield {"tool_calls": function_calls}

                                    if finish_reason:
                                        saw_finish_reason = True
                                        if not parts and (finish_reason != "STOP" or (not saw_content and not saw_tool_calls)):
                                            self._raise_for_empty_candidate(candidate)
                                        yield {
                                            "finish_reason": self._normalize_finish_reason(finish_reason),
                                            "done": True
                                        }
                            except json.JSONDecodeError:
                                continue

                    if not saw_content and not saw_tool_calls and not saw_finish_reason:
                        raise GeminiResponseError("Gemini 流式响应没有返回正文或结束原因")
                except GeneratorExit:
                    # 生成器被关闭，这是正常的清理过程
                    logger.debug("Gemini 流式响应生成器被关闭(GeneratorExit)")
                    raise
                except Exception as iter_error:
                    logger.error(f"Gemini 流式响应迭代出错: {str(iter_error)}")
                    raise
        except GeneratorExit:
            # 重新抛出GeneratorExit，让调用方处理
            raise
        except Exception as e:
            logger.error(f"Gemini 流式请求出错: {str(e)}")
            raise
