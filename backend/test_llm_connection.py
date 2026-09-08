"""
测试LLM连接是否正常
"""
import asyncio
import sys
import os
from pathlib import Path

# 设置控制台编码为UTF-8
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')

sys.path.insert(0, str(Path(__file__).parent))

from app.common.llm_client import llm_client, Message


async def test_llm():
    print("=" * 50)
    print("LLM连接测试")
    print("=" * 50)
    
    try:
        print("\n正在测试豆包API连接...")
        print(f"API Key: {llm_client._client.api_key[:20]}...")
        print(f"Endpoint ID: {llm_client._client.endpoint_id}")
        print(f"Base URL: {llm_client._client.base_url}")
        
        messages = [
            Message(role="user", content="你好，请简单介绍一下你自己。")
        ]
        
        print("\n发送测试消息...")
        response = await llm_client.chat(messages, temperature=0.7, max_tokens=100)
        
        print("\n" + "=" * 50)
        print("✅ LLM连接成功!")
        print("=" * 50)
        print(f"\n响应内容:\n{response.content}")
        print(f"\n模型: {response.model}")
        print(f"Token使用: {response.usage}")
        print(f"响应时间: {response.latency_ms:.2f}ms")
        print(f"结束原因: {response.finish_reason}")
        
        return True
        
    except Exception as e:
        print("\n" + "=" * 50)
        print("❌ LLM连接失败!")
        print("=" * 50)
        print(f"\n错误信息: {str(e)}")
        print(f"\n错误类型: {type(e).__name__}")
        
        import traceback
        print("\n详细错误堆栈:")
        traceback.print_exc()
        
        return False


async def test_simple_chat():
    print("\n" + "=" * 50)
    print("测试simple_chat方法")
    print("=" * 50)
    
    try:
        response = await llm_client.simple_chat(
            prompt="1+1等于几？",
            system_prompt="你是一个友好的助手，请简洁回答问题。"
        )
        
        print("\n✅ simple_chat测试成功!")
        print(f"响应: {response}")
        return True
        
    except Exception as e:
        print(f"\n❌ simple_chat测试失败: {str(e)}")
        return False


if __name__ == "__main__":
    print("\n开始LLM测试...\n")
    
    success1 = asyncio.run(test_llm())
    success2 = asyncio.run(test_simple_chat())
    
    print("\n" + "=" * 50)
    print("测试总结")
    print("=" * 50)
    print(f"基础chat测试: {'✅ 通过' if success1 else '❌ 失败'}")
    print(f"simple_chat测试: {'✅ 通过' if success2 else '❌ 失败'}")
    
    if success1 and success2:
        print("\n🎉 所有测试通过! LLM工作正常。")
        sys.exit(0)
    else:
        print("\n⚠️ 部分测试失败，请检查配置。")
        sys.exit(1)