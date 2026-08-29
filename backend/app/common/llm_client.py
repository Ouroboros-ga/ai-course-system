import logging
import time
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, AsyncGenerator

import httpx

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    usage: Dict[str, int]
    model: str
    finish_reason: str
    latency_ms: float


@dataclass
class Message:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMError(Exception):
    """A safe, classifiable failure returned by an LLM gateway.

    The exception text is allowed to reach a task status or the teacher UI, so
    it must never contain the gateway response body.  The small metadata set
    below lets callers make a compatible fallback decision without exposing
    provider-specific request ids, account details, or prompt echoes.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason_code: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code


def _llm_http_error_reason(*, status_code: int, body: str) -> str:
    """Classify only the safe HTTP-400 fallbacks we support.

    Different OpenAI-compatible gateways reject ``json_schema`` or an
    oversized context with different messages.  We intentionally retain no
    response text; a stable capability classification is sufficient for
    callers to retry with their prompt-constrained JSON path or to show an
    actionable "input too long" message.  Other 400s stay unclassified so
    invalid credentials, models, and request payloads cannot be hidden by a
    retry.
    """
    if status_code != 400:
        return ""
    normalized = body.casefold()
    if any(marker in normalized for marker in (
        "response_format",
        "json_schema",
        "json schema",
        "structured_output",
        "structured output",
    )):
        return "response_format_unsupported"
    if any(marker in normalized for marker in (
        "context length",
        "context_length",
        "maximum context",
        "max context",
        "context window",
        "input is too long",
        "input_too_long",
        "input length",
        "maximum input",
        "too many tokens",
        "token limit exceeded",
        "exceeds the maximum",
        "exceeded the maximum",
    )):
        return "input_length_exceeded"
    return ""


class BaseLLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        pass

    async def _make_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                latency_ms = (time.time() - start_time) * 1000
                result = response.json()
                result["_latency_ms"] = latency_ms
                return result
        except httpx.TimeoutException:
            raise LLMError(f"LLM API请求超时 ({timeout}秒)")
        except httpx.HTTPStatusError as e:
            # P1-B2: 响应体可能含账户标识、请求 ID、回显内容等敏感信息，
            # 不得写入异常消息或日志。仅保留 status_code 与无敏感信息的
            # 能力分类，供上层选择兼容性降级路径。
            try:
                body = e.response.text
            except Exception:
                body = "<unreadable>"
            status_code = e.response.status_code
            reason_code = _llm_http_error_reason(status_code=status_code, body=body)
            logger.warning(
                "LLM API请求失败: status=%s url=%s reason=%s",
                status_code,
                url,
                reason_code or "unclassified",
            )
            raise LLMError(
                f"LLM API请求失败: {status_code}",
                status_code=status_code,
                reason_code=reason_code,
            ) from None
        except Exception as e:
            raise LLMError(f"LLM API请求异常: {str(e)}")


class DoubaoClient(BaseLLMClient):
    def __init__(self):
        self.api_key = settings.DOUBAO_API_KEY or settings.LLM_API_KEY
        self.endpoint_id = settings.DOUBAO_ENDPOINT_ID
        self.base_url = settings.LLM_API_BASE or "https://ark.cn-beijing.volces.com/api/v3"
        self.model = settings.LLM_MODEL_NAME or "doubao-pro-32k"
        self.timeout = settings.LLM_TIMEOUT

        if not self.api_key:
            logger.warning("豆包API Key未配置，请在.env中设置DOUBAO_API_KEY")

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.endpoint_id or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        payload.update(kwargs)

        result = await self._make_request(url, headers, payload, self.timeout)

        choice = result.get("choices", [{}])[0]
        return LLMResponse(
            content=choice.get("message", {}).get("content", ""),
            usage=result.get("usage", {}),
            model=result.get("model", self.model),
            finish_reason=choice.get("finish_reason", ""),
            latency_ms=result.get("_latency_ms", 0),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.endpoint_id or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except Exception:
                            continue


class QwenClient(BaseLLMClient):
    def __init__(self):
        self.api_key = settings.QWEN_API_KEY or settings.LLM_API_KEY
        self.base_url = settings.LLM_API_BASE or "https://dashscope.aliyuncs.com/api/v1"
        self.model = settings.QWEN_MODEL_NAME or settings.LLM_MODEL_NAME or "qwen-turbo"
        self.timeout = settings.LLM_TIMEOUT

        if not self.api_key:
            logger.warning("通义千问API Key未配置，请在.env中设置QWEN_API_KEY")

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        url = f"{self.base_url}/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": {"messages": [m.to_dict() for m in messages]},
            "parameters": {
                "temperature": temperature or settings.LLM_TEMPERATURE,
                "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
                "result_format": "message",
            },
        }
        payload.update(kwargs)

        result = await self._make_request(url, headers, payload, self.timeout)

        output = result.get("output", {})
        return LLMResponse(
            content=output.get("choices", [{}])[0].get("message", {}).get("content", ""),
            usage=result.get("usage", {}),
            model=self.model,
            finish_reason=output.get("choices", [{}])[0].get("finish_reason", ""),
            latency_ms=result.get("_latency_ms", 0),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
        }

        payload = {
            "model": self.model,
            "input": {"messages": [m.to_dict() for m in messages]},
            "parameters": {
                "temperature": temperature or settings.LLM_TEMPERATURE,
                "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
                "result_format": "message",
                "incremental_output": True,
            },
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            try:
                                chunk = json.loads(data)
                                output = chunk.get("output", {})
                                choices = output.get("choices", [{}])
                                if choices:
                                    delta = choices[0].get("message", {})
                                    if "content" in delta:
                                        yield delta["content"]
                            except Exception:
                                continue


class SparkClient(BaseLLMClient):
    """讯飞星火 LLM（学科垂类基座，挑战杯 XH-202620）。

    星火开放平台 OpenAI 兼容 HTTP API（``/v1/chat/completions``），鉴权
    ``Authorization: Bearer <APIKey>``（配置 ``XFYUN_SPARK_API_KEY``）。
    未配置 Key 时仅告警：请求会在网关/上游失败并走调用方的降级语义；管理员开关
    （``LLMClient.set_enabled(False)``）关闭时在客户端层直接 fail-closed。
    """

    def __init__(self):
        self.api_key = settings.XFYUN_SPARK_API_KEY or settings.LLM_API_KEY
        self.base_url = settings.XFYUN_SPARK_BASE_URL.rstrip("/")
        # 星火端点使用自己的模型标识（OpenAI 兼容接口的 model 字段），
        # 不回退到通用 LLM_MODEL_NAME（那是豆包/OpenAI 兼容网关的模型名）。
        self.model = settings.XFYUN_SPARK_MODEL or "4.0Ultra"
        self.timeout = settings.LLM_TIMEOUT

        if not self.api_key:
            logger.warning("讯飞星火API Key未配置，请在.env中设置XFYUN_SPARK_API_KEY（LLM_PROVIDER=spark）")

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        payload.update(kwargs)

        result = await self._make_request(url, headers, payload, self.timeout)

        choice = result.get("choices", [{}])[0]
        return LLMResponse(
            content=choice.get("message", {}).get("content", ""),
            usage=result.get("usage", {}),
            model=result.get("model", self.model),
            finish_reason=choice.get("finish_reason", ""),
            latency_ms=result.get("_latency_ms", 0),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except Exception:
                            continue


class OpenAIClient(BaseLLMClient):
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_API_BASE or "https://api.openai.com/v1"
        self.model = settings.LLM_MODEL_NAME or "gpt-3.5-turbo"
        self.timeout = settings.LLM_TIMEOUT

        if not self.api_key:
            logger.warning("OpenAI API Key未配置，请在.env中设置LLM_API_KEY")

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        payload.update(kwargs)

        result = await self._make_request(url, headers, payload, self.timeout)

        choice = result.get("choices", [{}])[0]
        return LLMResponse(
            content=choice.get("message", {}).get("content", ""),
            usage=result.get("usage", {}),
            model=result.get("model", self.model),
            finish_reason=choice.get("finish_reason", ""),
            latency_ms=result.get("_latency_ms", 0),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except Exception:
                            continue


class LLMClient:
    _instance: Optional["LLMClient"] = None
    _client: Optional[BaseLLMClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_enabled"):
            self._enabled = True
        if self._client is None:
            self._client = self._create_client()

    def set_enabled(self, enabled: bool) -> None:
        """管理员开关：false 时所有 chat 调用 fail-closed，不静默降级。"""
        self._enabled = bool(enabled)
        if not self._enabled:
            # 保留当前 client 引用（配置可能随后恢复），只拒绝新调用。
            logger.info("LLM real provider disabled by administrator; chat calls will fail closed")
        else:
            logger.info("LLM real provider enabled by administrator")

    def _create_client(self) -> BaseLLMClient:
        provider = settings.LLM_PROVIDER.lower()

        clients = {
            "doubao": DoubaoClient,
            "qwen": QwenClient,
            "openai": OpenAIClient,
            "spark": SparkClient,
        }

        client_class = clients.get(provider)
        if not client_class:
            logger.warning(f"未知的LLM提供商: {provider}，使用默认豆包客户端")
            return DoubaoClient()

        logger.info(f"初始化LLM客户端: {provider}")
        return client_class()

    def replace_from_config(self, *, provider: str, base_url: str, model_name: str, api_key: str, extra_config: dict | None = None) -> None:
        if not api_key or not base_url or not model_name:
            raise LLMError("PROVIDER_NOT_CONFIGURED", reason_code="PROVIDER_NOT_CONFIGURED")
        settings.LLM_PROVIDER = provider
        settings.LLM_API_BASE = base_url.rstrip("/")
        settings.LLM_MODEL_NAME = model_name
        settings.LLM_API_KEY = api_key
        self._client = self._create_client()

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        self._require_enabled()
        return await self._client.chat(messages, temperature, max_tokens, **kwargs)

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        self._require_enabled()
        async for chunk in self._client.chat_stream(messages, temperature, max_tokens, **kwargs):
            yield chunk

    async def simple_chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append(Message(role="system", content=system_prompt))
        messages.append(Message(role="user", content=prompt))

        response = await self.chat(messages, temperature, max_tokens)
        return response.content

    def _require_enabled(self) -> None:
        """Fail closed when the administrator disabled the real LLM provider."""
        if not self._enabled:
            raise LLMError("LLM_DISABLED", reason_code="LLM_DISABLED")

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._client = None


llm_client = LLMClient()
