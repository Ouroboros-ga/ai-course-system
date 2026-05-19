import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_single_model(model_id, api_key):
    """测试单个模型"""
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 10,
    }
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=data,
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode('utf-8'))
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, f"OK - {content[:50]}"
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        if e.code == 404:
            return False, "404 Not Found"
        else:
            try:
                err_json = json.loads(error_body)
                return False, f"HTTP {e.code} - {err_json.get('error', {}).get('message', '')[:100]}"
            except:
                return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:100]


def main():
    print("=" * 70)
    print("批量测试可能的模型ID格式")
    print("=" * 70)
    
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    
    # 基于当前配置生成多种可能格式
    base_name = "Doubao-Seed-1.8"
    models_to_test = [
        # 原始配置
        "Doubao-Seed-1.8_TPM_IN10K",
        
        # 标准格式（从搜索结果看到的）
        "Doubao-seed-1-8-251228",
        "doubao-seed-1-8-251228",
        "Doubao-seed-1.8-251228",
        
        # 其他seed系列
        "Doubao-seed-2-0-lite-260215",
        "Doubao-seed-1-6",
        "Doubao-Seed-1.6",
        
        # 常用pro模型
        "Doubao-1.5-pro-32k",
        "Doubao-pro-32k",
        
        # lite模型
        "Doubao-1.5-lite-32k",
        "Doubao-lite-32k",
        
        # 小写版本
        "doubao-seed-1.8",
        "doubao-1.5-pro-32k",
    ]
    
    print(f"\nAPI Key: {api_key[:12]}...{api_key[-6:]}")
    print(f"\n测试 {len(models_to_test)} 个候选模型ID:\n")
    
    results = []
    for i, model in enumerate(models_to_test, 1):
        success, msg = test_single_model(model, api_key)
        status = "[OK]" if success else "[--]"
        print(f"{status} {i:2d}. {model:<35} -> {msg}")
        results.append((model, success))
        time.sleep(0.3)
    
    print("\n" + "=" * 70)
    successful = [m for m, s in results if s]
    
    if successful:
        print(f"[SUCCESS] 找到 {len(successful)} 个可用模型:")
        for m in successful:
            print(f"  ✓ {m}")
        print(f"\n[建议] 使用第一个可用模型更新 .env:")
        print(f"  DOUBAO_ENDPOINT_ID={successful[0]}")
    else:
        print("[FAILED] 所有模型都无法访问")
        print("\n[诊断]")
        print("  1. API Key 可能没有访问任何模型的权限")
        print("  2. 需要在火山引擎控制台开通模型服务")
        print("  3. 可能需要创建推理接入点(Endpoint)")
        print("\n[下一步]")
        print("  请访问: https://console.volcengine.com/ark/")
        print("  查看已开通的模型列表和接入点")


if __name__ == "__main__":
    main()
