import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_api():
    """测试豆包API接口"""
    print("=" * 60)
    print("豆包 API 接口测试")
    print("=" * 60)
    
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    endpoint_id = "Doubao-Seed-1.8_TPM_IN10K"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    print(f"\n[配置信息]")
    print(f"  API Key: {api_key[:12]}...{api_key[-6:]}")
    print(f"  Endpoint: {endpoint_id}")
    print(f"  Base URL: {base_url}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": endpoint_id,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    
    print(f"\n[发送请求]")
    print(f"  消息: {payload['messages'][0]['content']}")
    
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
            usage = result.get("usage", {})
            
            print(f"\n{'='*60}")
            print("[SUCCESS] API 调用成功!")
            print("=" * 60)
            print(f"[响应信息]")
            print(f"  模型: {result.get('model', 'unknown')}")
            print(f"  内容: {content}")
            print(f"  完成原因: {choice.get('finish_reason', '')}")
            print(f"  响应延迟: {latency_ms:.2f}ms")
            print(f"  Token使用:")
            print(f"    - 输入Token: {usage.get('prompt_tokens', 'N/A')}")
            print(f"    - 输出Token: {usage.get('completion_tokens', 'N/A')}")
            print(f"    - 总计Token: {usage.get('total_tokens', 'N/A')}")
            
            print(f"\n{'='*60}")
            print("[PASS] 豆包 API 接口正常运行!")
            print("=" * 60)
            
            return True
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"\n[ERROR] HTTP Error {e.code}")
        
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get('error', {}).get('message', error_body)
            print(f"  错误信息: {error_msg}")
        except:
            print(f"  响应内容: {error_body[:500]}")
        
        if e.code == 404:
            print("\n[诊断] 模型不存在或无权限访问")
            print("  请检查:")
            print("    1. Endpoint ID 是否正确")
            print("    2. 是否已在控制台开通该模型")
            print("    3. API Key 是否有该模型的权限")
        elif e.code == 401:
            print("\n[诊断] 认证失败")
            print("  请检查 API Key 是否正确")
        elif e.code == 429:
            print("\n[诊断] 请求频率超限或配额不足")
            print("  请稍后重试或检查账户额度")
        
        return False
        
    except urllib.error.URLError as e:
        print(f"\n[ERROR] 网络错误")
        print(f"  原因: {str(e.reason)}")
        return False
        
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_api()
    exit(0 if success else 1)
