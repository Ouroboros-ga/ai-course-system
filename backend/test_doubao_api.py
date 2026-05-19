import requests
import json
import time


def test_doubao_api():
    """测试豆包API接口"""
    print("=" * 60)
    print("开始测试豆包 API 接口...")
    print("=" * 60)
    
    # 从 .env 文件读取配置（手动解析）
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    endpoint_id = "Doubao1.5-pro-32k"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    print(f"\n配置信息:")
    print(f"  - API Key: {api_key[:10]}...{api_key[-6:]}")
    print(f"  - Endpoint ID: {endpoint_id}")
    print(f"  - Base URL: {base_url}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # 测试1: 简单对话
    print("\n【测试1】简单对话测试")
    print("-" * 40)
    
    payload = {
        "model": endpoint_id,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    
    print(f"发送消息: {payload['messages'][0]['content']}")
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        latency_ms = (time.time() - start_time) * 1000
        
        if response.status_code == 200:
            result = response.json()
            choice = result.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            
            print(f"\n✅ API 调用成功!")
            print(f"模型: {result.get('model', 'unknown')}")
            print(f"响应内容: {content[:300]}...")
            print(f"完成原因: {choice.get('finish_reason', '')}")
            print(f"延迟: {latency_ms:.2f}ms")
            print(f"Token使用: {result.get('usage', {})}")
            
            # 测试2: 流式输出
            print("\n\n【测试2】流式输出测试")
            print("-" * 40)
            
            payload_stream = {
                "model": endpoint_id,
                "messages": [
                    {"role": "user", "content": "请用3句话介绍人工智能的发展历程"}
                ],
                "temperature": 0.7,
                "max_tokens": 500,
                "stream": True,
            }
            
            print("流式输出内容:")
            
            response_stream = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload_stream,
                timeout=30,
                stream=True
            )
            
            if response_stream.status_code == 200:
                full_content = ""
                for line in response_stream.iter_lines():
                    if line:
                        line_str = line.decode('utf-8')
                        if line_str.startswith("data: "):
                            data = line_str[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    print(delta["content"], end="", flush=True)
                                    full_content += delta["content"]
                            except Exception:
                                continue
                
                print("\n\n✅ 流式输出完成!")
                print(f"总字符数: {len(full_content)}")
                
                print("\n" + "=" * 60)
                print("🎉 所有测试通过！豆包 API 接口正常运行")
                print("=" * 60)
                return True
            else:
                print(f"\n❌ 流式请求失败!")
                print(f"状态码: {response_stream.status_code}")
                print(f"响应: {response_stream.text[:500]}")
                return False
                
        else:
            print(f"\n❌ API 调用失败!")
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text[:500]}")
            return False
            
    except requests.exceptions.Timeout:
        print("\n❌ 请求超时!")
        return False
    except Exception as e:
        print(f"\n❌ 发生错误: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_doubao_api()
    exit(0 if success else 1)
