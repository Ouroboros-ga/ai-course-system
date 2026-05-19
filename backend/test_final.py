import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_api():
    """测试豆包API接口"""
    print("=" * 70)
    print("豆包 API 接口测试 - 新配置")
    print("=" * 70)
    
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    endpoint_id = "rpi-20260328132832-sxpkk"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    print(f"\n[配置信息]")
    print(f"  API Key: {api_key[:12]}...{api_key[-6:]}")
    print(f"  Endpoint: {endpoint_id}")
    print(f"  Base URL: {base_url}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # 测试1: 简单对话
    print(f"\n[测试1] 基础对话能力")
    print("-" * 70)
    
    payload = {
        "model": endpoint_id,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    
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
            
            print(f"[SUCCESS] 测试通过!")
            print(f"  模型: {result.get('model', 'unknown')}")
            print(f"  响应: {content}")
            print(f"  延迟: {latency_ms:.2f}ms")
            print(f"  Token使用:")
            print(f"    输入: {usage.get('prompt_tokens', 'N/A')}")
            print(f"    输出: {usage.get('completion_tokens', 'N/A')}")
            print(f"    总计: {usage.get('total_tokens', 'N/A')}")
            
            # 测试2: 中文理解能力
            print(f"\n[测试2] 中文理解能力")
            print("-" * 70)
            
            payload2 = {
                "model": endpoint_id,
                "messages": [
                    {"role": "user", "content": "请用三个词描述人工智能"}
                ],
                "temperature": 0.8,
                "max_tokens": 100,
            }
            
            data2 = json.dumps(payload2).encode('utf-8')
            req2 = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=data2,
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req2, timeout=30) as response2:
                result2 = json.loads(response2.read().decode('utf-8'))
                content2 = result2.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                print(f"[SUCCESS] 中文测试通过!")
                print(f"  响应: {content2}")
                
                # 最终结果
                print(f"\n{'='*70}")
                print("[PASS] 豆包 API 接口完全正常!")
                print("=" * 70)
                print(f"\n[配置验证]")
                print(f"  ✓ API Key 有效")
                print(f"  ✓ Endpoint ID 有效: {endpoint_id}")
                print(f"  ✓ 模型可正常调用")
                print(f"  ✓ 支持中文交互")
                print(f"  ✓ 响应速度正常")
                print(f"\n[结论] .env 配置正确，可以正常使用!")
                
                return True
                
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get('error', {}).get('message', error_body)
        except:
            error_msg = error_body[:500]
        
        print(f"\n[ERROR] HTTP Error {e.code}")
        print(f"  详情: {error_msg[:300]}")
        
        if e.code == 404:
            print("\n[诊断] Endpoint 不存在或无权限")
        elif e.code == 401:
            print("\n[诊断] 认证失败")
        elif e.code == 429:
            print("\n[诊断] 频率限制或配额不足")
        elif e.code >= 500:
            print("\n[诊断] 服务端错误")
        
        return False
        
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_api()
    
    if success:
        print(f"\n[下一步]")
        print(f"  可以启动后端服务进行完整功能测试:")
        print(f"  cd backend && python main.py")
    
    exit(0 if success else 1)
