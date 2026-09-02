from app.platform.adapters.digital_human import DigitalHumanAdapter
from app.platform.adapters.llm import LLMAdapter
from app.platform.adapters.ppt import PPTAdapter
from app.platform.adapters.tts import TTSAdapter
from app.platform.adapters.voice_clone import VoiceCloneAdapter


def get_llm_adapter(client=None) -> LLMAdapter:
    if client is None:
        from app.common.llm_client import llm_client
        client = llm_client
    return LLMAdapter(client)


def get_tts_adapter(client=None) -> TTSAdapter:
    if client is None:
        from app.common.tts_client import tts_client
        client = tts_client
    return TTSAdapter(client)


def get_voice_clone_adapter(client=None) -> VoiceCloneAdapter:
    if client is None:
        from app.common.tts_client import voice_clone_client
        client = voice_clone_client
    return VoiceCloneAdapter(client)


def get_ppt_adapter(client=None) -> PPTAdapter:
    if client is None:
        from app.services.ppt_generation_service import ppt_generation_service
        client = ppt_generation_service.xfyun_client
    return PPTAdapter(client)


def get_digital_human_adapter(client=None, provider: str | None = None) -> DigitalHumanAdapter:
    """Return the legacy digital-human adapter.

    数字人（avatar）功能已关闭：不再注册 Duix 等云端 Provider，仅保留通用
    适配器以便历史调用方（当前无 app 内调用方）继续使用本地 client。
    """
    if client is None:
        from app.common.digital_human_client import digital_human_client
        client = digital_human_client
    return DigitalHumanAdapter(client)
