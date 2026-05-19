import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_model(model_id):
    """测试指定模型"""
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "temperature": 0.7,
        "max_tokens": 50,
    }
    
    print(f"\n测试模型: {model_id}")
    print("-" * 40)
    
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
            
            print(f"[SUCCESS] 模型 {model_id} 可用!")
            print(f"响应: {content[:100]}")
            print(f"延迟: {latency_ms:.0f}ms")
            return True
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"[FAILED] HTTP {e.code}")
        if e.code == 404:
            print(f"  模型不存在或无权限访问")
        elif e.code == 401:
            print(f"  API Key 无效或过期")
        else:
            print(f"  {error_body[:200]}")
        return False
        
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {str(e)}")
        return False


def main():
    print("=" * 60)
    print("豆包 API 接口测试")
    print("=" * 60)
    
    # 测试多个可能的模型ID
    models_to_test = [
        "Doubao-1.5-pro-32k",      # 新版推荐
        "Doubao-pro-32k",          # 旧版
        "Doubao-1.5-lite-32k",     # 轻量版
        "Doubao-seed-1.6",         # 最新seed系列
        "doubao-pro-32k",          # 小写版本
    ]
    
    results = []
    for model in models_to_test:
        success = test_model(model)
        results.append((model, success))
        time.sleep(0.5)  # 避免请求过快
    
    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)
    
    for model, success in results:
        status = "[OK]" if success else "[FAIL]"
        print(f"{status} {model}")
    
    successful_models = [m for m, s in results if s]
    
    if successful_models:
        print(f"\n[建议] 可用模型: {successful_models[0]}")
        print("\n请更新 .env 文件中的 DOUBAO_ENDPOINT_ID 为:")
        print(f"DOUBAO_ENDPOINT_ID={successful_models[0]}")
    else:
        print("\n[警告] 所有模型都不可用!")
        print("请检查:")
        print("  1. API Key 是否正确: 329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d")
        print("  2. 是否已在火山引擎控制台开通对应模型")
        print("  3. 账户是否有足够余额或免费额度")


if __name__ == "__main__":
    main()
