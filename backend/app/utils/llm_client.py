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
    pass


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
            raise LLMError(f"LLM API请求失败: {e.response.status_code} - {e.response.text}")
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


class WenxinClient(BaseLLMClient):
    def __init__(self):
        self.api_key = settings.WENXIN_API_KEY or settings.LLM_API_KEY
        self.secret_key = settings.WENXIN_SECRET_KEY
        self.base_url = settings.LLM_API_BASE or "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop"
        self.model = settings.LLM_MODEL_NAME or "ernie-bot-4"
        self.timeout = settings.LLM_TIMEOUT
        self._access_token: Optional[str] = None
        self._token_expire_time: float = 0

        if not self.api_key or not self.secret_key:
            logger.warning("文心一言API Key未配置，请在.env中设置WENXIN_API_KEY和WENXIN_SECRET_KEY")

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expire_time:
            return self._access_token

        url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={self.api_key}&client_secret={self.secret_key}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url)
            response.raise_for_status()
            result = response.json()
            self._access_token = result.get("access_token")
            self._token_expire_time = time.time() + result.get("expires_in", 86400) - 300
            return self._access_token

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        access_token = await self._get_access_token()
        url = f"{self.base_url}/chat/{self.model}?access_token={access_token}"

        headers = {"Content-Type": "application/json"}
        payload = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_output_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        payload.update(kwargs)

        result = await self._make_request(url, headers, payload, self.timeout)

        return LLMResponse(
            content=result.get("result", ""),
            usage={
                "prompt_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": result.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": result.get("usage", {}).get("total_tokens", 0),
            },
            model=self.model,
            finish_reason="stop" if result.get("is_truncated") is False else "length",
            latency_ms=result.get("_latency_ms", 0),
        )

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        access_token = await self._get_access_token()
        url = f"{self.base_url}/chat/{self.model}?access_token={access_token}&stream=True"

        headers = {"Content-Type": "application/json"}
        payload = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature or settings.LLM_TEMPERATURE,
            "max_output_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "stream": True,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            chunk = json.loads(data)
                            if "result" in chunk:
                                yield chunk["result"]
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
        if self._client is None:
            self._client = self._create_client()

    def _create_client(self) -> BaseLLMClient:
        provider = settings.LLM_PROVIDER.lower()

        clients = {
            "doubao": DoubaoClient,
            "qwen": QwenClient,
            "wenxin": WenxinClient,
            "openai": OpenAIClient,
        }

        client_class = clients.get(provider)
        if not client_class:
            logger.warning(f"未知的LLM提供商: {provider}，使用默认豆包客户端")
            return DoubaoClient()

        logger.info(f"初始化LLM客户端: {provider}")
        return client_class()

    async def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        return await self._client.chat(messages, temperature, max_tokens, **kwargs)

    async def chat_stream(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
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

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._client = None


llm_client = LLMClient()
