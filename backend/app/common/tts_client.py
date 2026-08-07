import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
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
            error_text = e.response.text
            try:
                error_json = json.loads(error_text)
                error_msg = error_json.get("message", error_text)
            except:
                error_msg = error_text
            raise TTSError(f"TTS API请求失败: {e.response.status_code} - {error_msg}")
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

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


class VolcengineTTSClient(BaseTTSClient):
    """
    火山引擎TTS客户端
    文档: https://www.volcengine.com/docs/6561/79823
    支持预置音色合成 + 声音复刻克隆音色合成
    """
    
    def __init__(self):
        self.app_id = settings.VOLCENGINE_TTS_APP_ID
        self.access_token = settings.VOLCENGINE_TTS_ACCESS_TOKEN
        self.secret_key = settings.VOLCENGINE_TTS_SECRET_KEY
        self.clone_api_key = settings.VOLCENGINE_VOICE_CLONE_API_KEY
        self.clone_model_type = settings.VOLCENGINE_VOICE_CLONE_MODEL_TYPE
        self.default_voice = settings.TTS_VOICE or "zh_female_shuangkuaisisi_moon_bigtts"
        self.default_sample_rate = settings.TTS_SAMPLE_RATE
        self.default_format = settings.TTS_FORMAT
        self.timeout = 60
        
        if not self.app_id or not self.access_token or not self.secret_key:
            logger.warning("火山引擎TTS配置不完整，请在.env中设置VOLCENGINE_TTS相关配置")
    
    def _generate_signature(self, payload: str) -> str:
        hmac_obj = hmac.new(
            self.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        )
        return hmac_obj.hexdigest()
    
    def _is_clone_voice(self, voice: str) -> bool:
        """判断是否为克隆音色（以S_开头）"""
        return voice and voice.startswith("S_")
    
    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        sample_rate: Optional[int] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> TTSResponse:
        voice = voice or self.default_voice
        sample_rate = sample_rate or self.default_sample_rate
        output_format = output_format or self.default_format
        
        # 克隆音色使用volcano_icl集群 + x-api-key认证
        if self._is_clone_voice(voice):
            return await self._synthesize_clone(text, voice, sample_rate, output_format, **kwargs)
        
        # 预置音色使用volcano_tts集群
        return await self._synthesize_preset(text, voice, sample_rate, output_format, **kwargs)
    
    async def _synthesize_preset(
        self,
        text: str,
        voice: str,
        sample_rate: int,
        output_format: str,
        **kwargs,
    ) -> TTSResponse:
        """预置音色合成（原有逻辑）"""
        url = "https://openspeech.bytedance.com/api/v1/tts"
        
        format_map = {"mp3": "mp3", "wav": "wav", "pcm": "pcm"}
        audio_format = format_map.get(output_format.lower(), "mp3")
        
        payload_dict = {
            "app": {
                "appid": self.app_id,
                "token": self.access_token,
                "cluster": "volcano_tts",
            },
            "user": {"uid": "user_001"},
            "audio": {
                "voice_type": voice,
                "encoding": audio_format,
                "speed_ratio": kwargs.get("speed_ratio", 1.0),
                "volume_ratio": kwargs.get("volume_ratio", 1.0),
                "pitch_ratio": kwargs.get("pitch_ratio", 1.0),
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "operation": "query",
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer; {self.access_token}",
        }
        
        try:
            response_data, latency_ms = await self._make_request(
                url, headers, payload=payload_dict, timeout=self.timeout
            )
            result = json.loads(response_data.decode('utf-8'))
            
            if result.get("code") != 3000:
                raise TTSError(f"火山引擎TTS错误: {result.get('message', '未知错误')}")
            
            data = result.get("data")
            if not data:
                raise TTSError("火山引擎TTS返回的数据为空")
            
            audio_base64 = data if isinstance(data, str) else data.get("audio", "")
            if not audio_base64:
                raise TTSError("火山引擎TTS返回的音频数据为空")
            
            audio_data = base64.b64decode(audio_base64)
            return TTSResponse(
                audio_data=audio_data,
                audio_format=output_format,
                sample_rate=sample_rate,
                latency_ms=latency_ms,
            )
        except json.JSONDecodeError as e:
            raise TTSError(f"火山引擎TTS响应解析失败: {str(e)}")
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            raise TTSError(f"火山引擎TTS请求失败: {str(e)}")
    
    async def _synthesize_clone(
        self,
        text: str,
        voice: str,
        sample_rate: int,
        output_format: str,
        **kwargs,
    ) -> TTSResponse:
        """克隆音色合成（使用volcano_icl集群 + x-api-key认证）"""
        url = "https://openspeech.bytedance.com/api/v1/tts"
        
        if not self.clone_api_key:
            raise TTSError("声音复刻API Key未配置，请在.env中设置VOLCENGINE_VOICE_CLONE_API_KEY")
        
        format_map = {"mp3": "mp3", "wav": "wav", "pcm": "pcm"}
        audio_format = format_map.get(output_format.lower(), "mp3")
        
        payload_dict = {
            "app": {
                "cluster": "volcano_icl",
            },
            "user": {"uid": "ai-course-system"},
            "audio": {
                "voice_type": voice,
                "encoding": audio_format,
                "speed_ratio": kwargs.get("speed_ratio", 1.0),
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "operation": "query",
            }
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.clone_api_key,
        }
        
        try:
            response_data, latency_ms = await self._make_request(
                url, headers, payload=payload_dict, timeout=self.timeout
            )
            result = json.loads(response_data.decode('utf-8'))
            
            if result.get("code") != 3000:
                raise TTSError(f"声音复刻TTS错误: {result.get('message', '未知错误')}")
            
            data = result.get("data")
            if not data:
                raise TTSError("声音复刻TTS返回的数据为空")
            
            audio_base64 = data if isinstance(data, str) else data.get("audio", "")
            if not audio_base64:
                raise TTSError("声音复刻TTS返回的音频数据为空")
            
            audio_data = base64.b64decode(audio_base64)
            return TTSResponse(
                audio_data=audio_data,
                audio_format=output_format,
                sample_rate=sample_rate,
                latency_ms=latency_ms,
            )
        except json.JSONDecodeError as e:
            raise TTSError(f"声音复刻TTS响应解析失败: {str(e)}")
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            raise TTSError(f"声音复刻TTS请求失败: {str(e)}")


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
            "volcengine": VolcengineTTSClient,
            "mock": MockTTSClient,
        }

        client_class = clients.get(provider)
        import os
        if provider == "mock" and os.getenv("AI_COURSE_TESTING") != "1" and not settings.ALLOW_DEMO_PROVIDERS:
            raise TTSError("PROVIDER_NOT_CONFIGURED")
        if not client_class:
            logger.warning(f"未知的TTS提供商: {provider}，使用Mock客户端")
            raise TTSError("PROVIDER_NOT_CONFIGURED")

        logger.info(f"初始化TTS客户端: {provider}")
        return client_class()

    def replace_from_config(self, *, provider: str, api_key: str, extra_config: dict | None = None) -> None:
        if not provider or not api_key:
            raise TTSError("PROVIDER_NOT_CONFIGURED")
        settings.TTS_PROVIDER = provider
        self._client = self._create_client()

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


class VoiceCloneClient:
    """
    火山引擎声音复刻客户端
    文档: https://www.volcengine.com/docs/6561/1305191
    
    流程：上传参考音频 → 训练 → 获取speaker_id → 用于TTS合成
    """

    def __init__(self):
        self.app_id = settings.VOLCENGINE_TTS_APP_ID
        self.access_token = settings.VOLCENGINE_TTS_ACCESS_TOKEN
        self.model_type = settings.VOLCENGINE_VOICE_CLONE_MODEL_TYPE
        self.timeout = 120  # 训练可能较慢

        if not self.app_id or not self.access_token:
            logger.warning("声音复刻配置不完整，需要VOLCENGINE_TTS_APP_ID和VOLCENGINE_TTS_ACCESS_TOKEN")

    def _get_resource_id(self) -> str:
        """根据model_type返回Resource-Id"""
        if self.model_type == 4:
            return "seed-icl-2.0"
        return "seed-icl-1.0"

    async def upload_and_train(
        self,
        audio_bytes: bytes,
        speaker_id: str,
        audio_format: str = "mp3",
        language: int = 0,
    ) -> dict:
        """
        上传音频并训练声音复刻模型
        
        Args:
            audio_bytes: 音频二进制数据
            speaker_id: 唯一音色代号（建议用 teacher_{user_id}_{asset_id}）
            audio_format: 音频格式（mp3/wav/ogg/m4a/aac/pcm）
            language: 语种 0=中文 1=英文
        
        Returns:
            {"speaker_id": "S_xxxxxxxxx", "status": "success"} 或抛出异常
        """
        url = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload"

        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

        payload = {
            "appid": self.app_id,
            "speaker_id": speaker_id,
            "audios": [
                {
                    "audio_bytes": audio_base64,
                    "audio_format": audio_format,
                }
            ],
            "source": 2,
            "language": language,
            "model_type": self.model_type,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer; {self.access_token}",
            "Resource-Id": self._get_resource_id(),
        }

        try:
            start_time = time.time()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                latency_ms = (time.time() - start_time) * 1000

            result = response.json()
            logger.info(f"[VoiceClone] 上传训练响应: code={result.get('code')}, latency={latency_ms:.0f}ms")

            code = result.get("code")
            if code == 0 or code == 3000:
                # 训练成功，提取speaker_id
                data = result.get("data", {})
                resp_speaker_id = data.get("speaker_id", speaker_id)
                return {
                    "speaker_id": resp_speaker_id,
                    "status": "success",
                    "message": "声音复刻训练成功",
                }
            else:
                error_msg = result.get("message", "未知错误")
                # 常见错误码
                error_map = {
                    1109: "音频与文本差异过大(WER Error)",
                    1105: "音频质量不足，请上传更清晰的录音",
                    1101: "音频时长不足，建议至少10秒",
                }
                detail = error_map.get(code, error_msg)
                raise TTSError(f"声音复刻训练失败(code={code}): {detail}")

        except httpx.TimeoutException:
            raise TTSError(f"声音复刻训练请求超时 ({self.timeout}秒)")
        except json.JSONDecodeError:
            raise TTSError("声音复刻训练响应解析失败")
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            raise TTSError(f"声音复刻训练请求异常: {str(e)}")

    async def query_status(self, speaker_id: str) -> dict:
        """
        查询声音复刻训练状态
        
        Returns:
            {"status": "success"/"pending"/"failed", "speaker_id": "S_xxx"}
        """
        url = "https://openspeech.bytedance.com/api/v1/mega_tts/audio/status"

        payload = {
            "appid": self.app_id,
            "speaker_id": speaker_id,
            "model_type": self.model_type,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer; {self.access_token}",
            "Resource-Id": self._get_resource_id(),
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload, headers=headers)

            result = response.json()
            code = result.get("code")
            data = result.get("data", {})

            if code == 0 or code == 3000:
                status = data.get("status", "unknown")
                return {
                    "speaker_id": speaker_id,
                    "status": "success" if status in ("success", "trained", "online") else "pending",
                    "detail": data,
                }
            else:
                return {
                    "speaker_id": speaker_id,
                    "status": "failed",
                    "message": result.get("message", "查询失败"),
                }
        except Exception as e:
            return {
                "speaker_id": speaker_id,
                "status": "failed",
                "message": str(e),
            }


voice_clone_client = VoiceCloneClient()
