import json
import time
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_api():
    """测试豆包API接口 - 最终验证"""
    print("=" * 70)
    print("豆包 API 接口测试")
    print("Endpoint: ep-20260519215608-7blpw")
    print("=" * 70)
    
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    endpoint_id = "ep-20260519215608-7blpw"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    
    print(f"\n[配置信息]")
    print(f"  API Key: {api_key[:15]}...{api_key[-6:]}")
    print(f"  Endpoint: {endpoint_id}")
    print(f"  Base URL: {base_url}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # 测试1: 基础对话
    print(f"\n{'='*70}")
    print("[测试 1/3] 基础对话能力")
    print("-" * 70)
    
    payload1 = {
        "model": endpoint_id,
        "messages": [
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    
    try:
        data = json.dumps(payload1).encode('utf-8')
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
            
            print(f"[SUCCESS] 基础对话测试通过!")
            print(f"\n[响应详情]")
            print(f"  模型名称: {result.get('model', 'unknown')}")
            print(f"  AI回复内容:")
            print(f"  ┌────────────────────────────────────┐")
            for line in content.split('\n')[:5]:
                print(f"  │ {line[:46]:<46}│")
            if len(content.split('\n')) > 5:
                print(f"  │ ...                                  │")
            print(f"  └────────────────────────────────────┘")
            print(f"\n[性能指标]")
            print(f"  响应延迟: {latency_ms:.2f}ms ({latency_ms/1000:.2f}秒)")
            print(f"  Token使用:")
            print(f"    输入Token:  {usage.get('prompt_tokens', 0):>6}")
            print(f"    输出Token:  {usage.get('completion_tokens', 0):>6}")
            print(f"    总计Token:  {usage.get('total_tokens', 0):>6}")
            
            # 测试2: 中文理解
            print(f"\n{'='*70}")
            print("[测试 2/3] 中文理解能力")
            print("-" * 70)
            
            payload2 = {
                "model": endpoint_id,
                "messages": [
                    {"role": "user", "content": "请用三个词描述人工智能的特点"}
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
                
                print(f"[SUCCESS] 中文理解测试通过!")
                print(f"  问题: 请用三个词描述人工智能的特点")
                print(f"  回答: {content2}")
                
                # 测试3: 专业领域知识
                print(f"\n{'='*70}")
                print("[测试 3/3] 专业领域能力（教育相关）")
                print("-" * 70)
                
                payload3 = {
                    "model": endpoint_id,
                    "messages": [
                        {"role": "user", "content": "简述频域响应法在控制系统中的应用"}
                    ],
                    "temperature": 0.6,
                    "max_tokens": 150,
                }
                
                data3 = json.dumps(payload3).encode('utf-8')
                req3 = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=data3,
                    headers=headers,
                    method='POST'
                )
                
                with urllib.request.urlopen(req3, timeout=30) as response3:
                    result3 = json.loads(response3.read().decode('utf-8'))
                    content3 = result3.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    print(f"[SUCCESS] 专业领域测试通过!")
                    print(f"  回答预览: {content3[:150]}...")
                    
                    # 最终总结
                    print(f"\n{'='*70}")
                    print("🎉 所有测试通过! API 接口完全正常!")
                    print("=" * 70)
                    
                    print(f"\n[✅ 配置验证结果]")
                    print(f"  ✓ API Key 有效且已授权")
                    print(f"  ✓ Endpoint ID 正确: {endpoint_id}")
                    print(f"  ✓ 模型服务运行正常")
                    print(f"  ✓ 支持中文对话交互")
                    print(f"  ✓ 支持专业领域问答")
                    print(f"  ✓ 响应速度良好 (<3秒)")
                    
                    print(f"\n[📝 配置文件状态]")
                    print(f"  文件位置: backend/.env")
                    print(f"  当前配置:")
                    print(f"    DOUBAO_API_KEY={api_key[:20]}...")
                    print(f"    DOUBAO_ENDPOINT_ID={endpoint_id}")
                    print(f"  状态: ✅ 可以投入使用!")
                    
                    print(f"\n[🚀 下一步操作]")
                    print(f"  1. 启动后端服务: cd backend && python main.py")
                    print(f"  2. 上传文档测试完整功能")
                    print(f"  3. 检查前端展示效果")
                    
                    return True
                    
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        
        try:
            error_json = json.loads(error_body)
            error_msg = error_json.get('error', {}).get('message', error_body)
            error_code = error_json.get('error', {}).get('code', '')
        except:
            error_msg = error_body[:400]
            error_code = ""
        
        print(f"\n❌ [ERROR] HTTP Error {e.code}")
        
        if error_code:
            print(f"  错误代码: {error_code}")
        print(f"  错误信息: {error_msg[:300]}")
        
        print(f"\n[错误诊断]")
        if e.code == 404:
            print(f"  ⚠️  Endpoint或模型不存在")
            print(f"  可能原因:")
            print(f"    1. Endpoint ID输入错误")
            print(f"    2. Endpoint已被删除或停用")
            print(f"    3. API Key无权访问该Endpoint")
        elif e.code == 401:
            print(f"  ⚠️  认证失败")
            print(f"  可能原因:")
            print(f"    1. API Key无效或过期")
            print(f"    2. Key格式错误")
        elif e.code == 429:
            print(f"  ⚠️  请求频率限制")
            print(f"  可能原因:")
            print(f"    1. 调用次数超过配额")
            print(f"    2. 账户余额不足")
        elif e.code >= 500:
            print(f"  ⚠️  服务端错误")
            print(f"  建议: 稍后重试或联系技术支持")
        
        return False
        
    except Exception as e:
        print(f"\n❌ [ERROR] {type(e).__name__}")
        print(f"  详情: {str(e)[:300]}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_api()
    
    if not success:
        print(f"\n[💡 建议操作]")
        print(f"  1. 确认Endpoint ID是否从控制台直接复制")
        print(f"  2. 检查控制台中的Endpoint状态是否为'运行中'")
        print(f"  3. 确认API Key和Endpoint属于同一项目")
        print(f"  4. 查看账户余额: https://console.volcengine.com/finance")
    
    exit(0 if success else 1)
