import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.common.llm_client import llm_client, Message


async def test_doubao_api():
    """测试豆包API接口是否正常"""
    print("=" * 60)
    print("开始测试豆包 API 接口...")
    print("=" * 60)
    
    try:
        # 测试1: 简单对话
        print("\n【测试1】简单对话测试")
        print("-" * 40)
        
        messages = [
            Message(role="user", content="你好，请用一句话介绍你自己")
        ]
        
        print(f"发送消息: {messages[0].content}")
        response = await llm_client.chat(messages)
        
        print(f"\n✅ API 调用成功!")
        print(f"模型: {response.model}")
        print(f"响应内容: {response.content[:200]}...")
        print(f"完成原因: {response.finish_reason}")
        print(f"延迟: {response.latency_ms:.2f}ms")
        print(f"Token使用: {response.usage}")
        
        # 测试2: 流式输出
        print("\n\n【测试2】流式输出测试")
        print("-" * 40)
        
        messages_stream = [
            Message(role="user", content="请用3句话介绍人工智能的发展历程")
        ]
        
        print("流式输出内容:")
        full_content = ""
        async for chunk in llm_client.chat_stream(messages_stream):
            print(chunk, end="", flush=True)
            full_content += chunk
        
        print("\n\n✅ 流式输出完成!")
        print(f"总字符数: {len(full_content)}")
        
        # 测试3: simple_chat 方法
        print("\n\n【测试3】simple_chat 方法测试")
        print("-" * 40)
        
        result = await llm_client.simple_chat(
            prompt="什么是机器学习？请用简短的语言回答",
            system_prompt="你是一个专业的AI助手"
        )
        
        print(f"✅ simple_chat 成功!")
        print(f"响应: {result[:200]}...")
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！豆包 API 接口正常运行")
        print("=" * 60)
        return True
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ API 测试失败!")
        print("=" * 60)
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_doubao_api())
    sys.exit(0 if success else 1)
