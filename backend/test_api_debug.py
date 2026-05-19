import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


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
            {"role": "user", "content": "你好"}
        ],
        "temperature": 0.7,
        "max_tokens": 50,
    }
    
    print(f"发送消息: {payload['messages'][0]['content']}")
    print(f"请求URL: {base_url}/chat/completions")
    print(f"使用的model: {payload['model']}")
    
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
            
            print(f"\n[SUCCESS] API 调用成功!")
            print(f"模型: {result.get('model', 'unknown')}")
            print(f"响应内容: {content[:300]}")
            print(f"完成原因: {choice.get('finish_reason', '')}")
            print(f"延迟: {latency_ms:.2f}ms")
            print(f"Token使用: {json.dumps(result.get('usage', {}), ensure_ascii=False)}")
            
            print("\n" + "=" * 60)
            print("[PASS] 测试通过! 豆包 API 接口正常运行")
            print("=" * 60)
            return True
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"\n[ERROR] HTTP Error {e.code}")
        print(f"响应内容: {error_body[:1000]}")
        
        if e.code == 404:
            print("\n[诊断] 404错误可能原因:")
            print("  1. Endpoint ID 不正确或不存在")
            print("  2. API URL 路径错误")
            print("  3. 模型名称格式错误")
            print(f"\n当前Endpoint ID: {endpoint_id}")
            print("正确的Endpoint ID格式应该是: ep-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
            
        return False
        
    except urllib.error.URLError as e:
        print(f"\n[ERROR] URL Error")
        print(f"原因: {str(e.reason)}")
        return False
        
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_doubao_api()
    exit(0 if success else 1)
