import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlencode

import httpx

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TTSResponse:
    audio_data: bytes
    audio_format: str
    sample_rate: int
    duration_ms: Optional[float] = None
    latency_ms: float = 0


class TTSError(Exception):
    pass


class BaseTTSClient(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        pass

    async def _make_request(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        timeout: int = 60,
    ) -> Tuple[bytes, float]:
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if data:
                    response = await client.post(url, content=data, headers=headers)
                else:
                    response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                latency_ms = (time.time() - start_time) * 1000
                return response.content, latency_ms
        except httpx.TimeoutException:
            raise TTSError(f"TTS API请求超时 ({timeout}秒)")
        except httpx.HTTPStatusError as e:
            raise TTSError(f"TTS API请求失败: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise TTSError(f"TTS API请求异常: {str(e)}")


class AliyunTTSClient(BaseTTSClient):
    def __init__(self):
        self.access_key_id = settings.ALIYUN_TTS_ACCESS_KEY_ID or settings.TTS_API_KEY
        self.access_key_secret = settings.ALIYUN_TTS_ACCESS_KEY_SECRET or settings.TTS_API_SECRET
        self.app_key = settings.ALIYUN_TTS_APP_KEY or settings.TTS_APP_ID
        self.default_voice = settings.TTS_VOICE or "xiaoyun"
        self.default_sample_rate = settings.TTS_SAMPLE_RATE
        self.default_format = settings.TTS_FORMAT
        self.timeout = 60

        if not self.access_key_id or not self.access_key_secret or not self.app_key:
            logger.warning("阿里云TTS配置不完整，请在.env中设置ALIYUN_TTS相关配置")

    def _generate_signature(self, params: Dict[str, str], secret: str) -> str:
        sorted_params = sorted(params.items())
        canonicalized_query_string = "&".join(
            [f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted_params]
        )
        string_to_sign = f"POST&%2F&{quote(canonicalized_query_string, safe='~')}"
        hmac_obj = hmac.new(
            (secret + "&").encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
        )
        return base64.b64encode(hmac_obj.digest()).decode("utf-8")

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        url = "https://nls-gateway.cn-shanghai.aliyuncs.com/stream/v1/tts"

        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = str(uuid.uuid4())

        voice = voice or self.default_voice
        sample_rate = sample_rate or self.default_sample_rate
        output_format = output_format or self.default_format

        params = {
            "AccessKeyId": self.access_key_id,
            "Action": "CreateSynthesizeTask",
            "AppKey": self.app_key,
            "Format": output_format,
            "SampleRate": str(sample_rate),
            "Text": text,
            "Voice": voice,
            "Timestamp": timestamp,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": nonce,
            "SignatureVersion": "1.0",
            "Version": "2019-02-28",
        }

        signature = self._generate_signature(params, self.access_key_secret)
        params["Signature"] = signature

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        audio_data, latency_ms = await self._make_request(
            url, headers, data=urlencode(params).encode("utf-8"), timeout=self.timeout
        )

        return TTSResponse(
            audio_data=audio_data,
            audio_format=output_format,
            sample_rate=sample_rate,
            latency_ms=latency_ms,
        )


class TencentTTSClient(BaseTTSClient):
    def __init__(self):
        self.secret_id = settings.TENCENT_TTS_SECRET_ID or settings.TTS_API_KEY
        self.secret_key = settings.TENCENT_TTS_SECRET_KEY or settings.TTS_API_SECRET
        self.app_id = settings.TENCENT_TTS_APP_ID or settings.TTS_APP_ID
        self.default_voice = settings.TTS_VOICE or "101001"
        self.default_sample_rate = settings.TTS_SAMPLE_RATE
        self.default_format = settings.TTS_FORMAT
        self.timeout = 60

        if not self.secret_id or not self.secret_key:
            logger.warning("腾讯云TTS配置不完整，请在.env中设置TENCENT_TTS相关配置")

    def _generate_signature(self, payload: str, timestamp: int, service: str) -> str:
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        credential_scope = f"{date}/{service}/tc3_request"

        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"POST\n/\n\ncontent-type:application/json\nhost:{service}.tencentcloudapi.com\n\n"
            f"content-type;host\n{hashed_payload}"
        )

        string_to_sign = (
            f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        def _hmac_sha256(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = _hmac_sha256(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = _hmac_sha256(secret_date, service)
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        return (
            f"TC3-HMAC-SHA256 Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders=content-type;host, Signature={signature}"
        )

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        url = "https://tts.tencentcloudapi.com"
        service = "tts"

        voice = voice or self.default_voice
        sample_rate = sample_rate or self.default_sample_rate
        output_format = output_format or self.default_format

        payload_dict = {
            "Text": text,
            "VoiceType": int(voice) if voice.isdigit() else 101001,
            "SampleRate": sample_rate,
            "Codec": output_format,
            "Speed": kwargs.get("speed", 0),
            "Volume": kwargs.get("volume", 0),
        }

        payload = json.dumps(payload_dict)
        timestamp = int(time.time())

        headers = {
            "Content-Type": "application/json",
            "Host": f"{service}.tencentcloudapi.com",
            "X-TC-Action": "TextToVoice",
            "X-TC-Version": "2019-08-23",
            "X-TC-Timestamp": str(timestamp),
            "Authorization": self._generate_signature(payload, timestamp, service),
        }

        response_data, latency_ms = await self._make_request(
            url, headers, payload=payload_dict, timeout=self.timeout
        )

        result = json.loads(response_data)
        audio_base64 = result.get("Response", {}).get("Audio", "")
        if not audio_base64:
            raise TTSError("腾讯云TTS返回的音频数据为空")

        audio_data = base64.b64decode(audio_base64)

        return TTSResponse(
            audio_data=audio_data,
            audio_format=output_format,
            sample_rate=sample_rate,
            latency_ms=latency_ms,
        )


class MockTTSClient(BaseTTSClient):
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        logger.info(f"[Mock TTS] 合成文本: {text[:50]}...")
        return TTSResponse(
            audio_data=b"MOCK_AUDIO_DATA",
            audio_format=output_format or "mp3",
            sample_rate=sample_rate or 16000,
            latency_ms=100,
        )


class TTSClient:
    _instance: Optional["TTSClient"] = None
    _client: Optional[BaseTTSClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._client = self._create_client()

    def _create_client(self) -> BaseTTSClient:
        provider = settings.TTS_PROVIDER.lower()

        clients = {
            "aliyun": AliyunTTSClient,
            "tencent": TencentTTSClient,
            "mock": MockTTSClient,
        }

        client_class = clients.get(provider)
        if not client_class:
            logger.warning(f"未知的TTS提供商: {provider}，使用Mock客户端")
            return MockTTSClient()

        logger.info(f"初始化TTS客户端: {provider}")
        return client_class()

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        if not text or not text.strip():
            raise TTSError("合成文本不能为空")

        if len(text) > 5000:
            logger.warning(f"文本长度超过5000字符 ({len(text)})，可能影响合成效果")

        return await self._client.synthesize(text, voice, sample_rate, output_format, **kwargs)

    async def synthesize_to_base64(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> str:
        response = await self.synthesize(text, voice, sample_rate, output_format, **kwargs)
        return base64.b64encode(response.audio_data).decode("utf-8")

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._client = None


tts_client = TTSClient()
