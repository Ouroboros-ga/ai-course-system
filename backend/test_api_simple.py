import json
import time
import urllib.request
import urllib.error


def test_doubao_api():
    """测试豆包API接口"""
    print("=" * 60)
    print("开始测试豆包 API 接口...")
    print("=" * 60)
    
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
    
    print("\n【测试】简单对话测试")
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
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=data,
            headers=headers,
            method='POST'
        )
        
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=30) as response:
            latency_ms = (time.time() - start_time) * 1000
            result = json.loads(response.read().decode('utf-8'))
            
            choice = result.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
            
            print(f"\n✅ API 调用成功!")
            print(f"模型: {result.get('model', 'unknown')}")
            print(f"响应内容: {content[:300]}...")
            print(f"完成原因: {choice.get('finish_reason', '')}")
            print(f"延迟: {latency_ms:.2f}ms")
            print(f"Token使用: {result.get('usage', {})}")
            
            print("\n" + "=" * 60)
            print("🎉 测试通过！豆包 API 接口正常运行")
            print("=" * 60)
            return True
            
    except urllib.error.HTTPError as e:
        print(f"\n❌ HTTP 错误!")
        print(f"状态码: {e.code}")
        print(f"响应: {e.read().decode('utf-8')[:500]}")
        return False
    except urllib.error.URLError as e:
        print(f"\n❌ URL 错误!")
        print(f"错误信息: {str(e.reason)}")
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
