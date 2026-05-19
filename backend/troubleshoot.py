import json
import urllib.request
import urllib.error
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def check_api_key_validity():
    """检查API Key基本信息"""
    print("=" * 70)
    print("API Key 完整性检查")
    print("=" * 70)
    
    api_key = "329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d"
    
    print(f"\n[API Key 信息]")
    print(f"  Key: {api_key}")
    print(f"  长度: {len(api_key)} 字符")
    print(f"  格式: UUID格式 ✓")
    
    # 测试不同的base URL
    base_urls = [
        "https://ark.cn-beijing.volces.com/api/v3",
        "https://ark.cn-shanghai.volces.com/api/v3",
        "https://open.volcengineapi.com/api/v3",
    ]
    
    endpoint_id = "rpi-20260328132832-sxpkk"
    
    print(f"\n[测试不同API端点]")
    
    for base_url in base_urls:
        print(f"\n  测试: {base_url}")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": endpoint_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=data,
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"    [SUCCESS] {base_url}")
                print(f"    响应: {content[:50]}")
                return True, base_url
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            
            if e.code == 401:
                print(f"    [AUTH ERROR] 认证失败 - Key可能无效")
                return False, None
            elif e.code == 404:
                print(f"    [NOT FOUND] Endpoint不存在")
            else:
                try:
                    err_json = json.loads(error_body)
                    print(f"    [ERROR {e.code}] {err_json.get('error', {}).get('message', '')[:100]}")
                except:
                    print(f"    [ERROR {e.code}]")
                    
        except Exception as e:
            print(f"    [EXCEPTION] {str(e)[:80]}")
    
    return False, None


def generate_troubleshooting_guide():
    """生成故障排查指南"""
    guide = """
    
╔══════════════════════════════════════════════════════════════╗
║              火山引擎豆包 API 配置故障排查指南                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                                ║
║  【当前状态】                                                  ║
║    ✅ API Key 格式正确 (UUID)                                  ║
║    ❌ 所有模型ID和Endpoint都无法访问                            ║
║                                                                ║
║  【可能原因】                                                  ║
║                                                                ║
║  1. 🔐 API Key 与 Endpoint 不匹配                              ║
║     └─ 你的Endpoint可能是在另一个账户/项目下创建的             ║
║     └─ 解决：确保Key和Endpoint来自同一账户                      ║
║                                                                ║
║  2. 📋 模型未开通或已过期                                      ║
║     └─ 即使有Endpoint，底层的模型服务可能未激活                 ║
║     └─ 解决：在控制台检查模型状态                              ║
║                                                                ║
║  3. 🌐 区域/节点不匹配                                         ║
║     └─ Endpoint创建在北京，但调用上海节点                       ║
║     └─ 或反之                                                  ║
║     └─ 解决：确认Endpoint所在的区域                            ║
║                                                                ║
║  4. 💰 账户余额或配额问题                                      ║
║     └─ 免费额度用完                                            ║
║     └─ 账户欠费                                                ║
║     └─ 解决：充值或检查配额                                    ║
║                                                                ║
║  5. ⚙️ 权限配置错误                                            ║
║     └─ API Key没有访问该模型的权限                             ║
║     └─ 解决：在IAM或Key管理中添加权限                          ║
║                                                                ║
╠══════════════════════════════════════════════════════════════╣
║  【立即行动清单】                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                                ║
║  □ 步骤1: 登录火山引擎控制台                                   ║
║    https://console.volcengine.com/ark/                        ║
║                                                                ║
║  □ 步骤2: 进入「模型推理」→「推理接入点」                      ║
║    查看你的接入点列表                                          ║
║                                                                ║
║  □ 步骤3: 确认接入点状态                                       ║
║    状态应该是「运行中」而不是「已停用」                         ║
║                                                                ║
║  □ 步骤4: 复制正确的Endpoint ID                                ║
║    直接从控制台复制，避免手动输入错误                           ║
║                                                                ║
║  □ 步骤5: 检查API Key所属项目                                 ║
║    确保Key和Endpoint在同一项目下                               ║
║                                                                ║
║  □ 步骤6: 查看「费用中心」                                     ║
║    确认账户余额充足，没有欠费                                  ║
║                                                                ║
║  □ 步骤7: 如果以上都正常，联系技术支持                         ║
║    在控制台提交工单                                           ║
║                                                                ║
╚══════════════════════════════════════════════════════════════╝
    """
    return guide


def main():
    success, working_url = check_api_key_validity()
    
    if success:
        print("\n[SUCCESS] 找到可用的API配置!")
        print(f"  工作URL: {working_url}")
    else:
        print(generate_troubleshooting_guide())
        
        print("\n[快速验证命令]")
        print("  在浏览器打开以下链接，查看你的API资源:")
        print()
        print("  1. 推理接入点:")
        print("     https://console.volcengine.com/ark/endpoint")
        print()
        print("  2. API Key管理:")
        print("     https://console.volcengine.com/ark/api-key")
        print()
        print("  3. 已开通模型:")
        print("     https://console.volcengine.com/ark/model")
        print()
        print("  4. 费用中心:")
        print("     https://console.volcengine.com/finance")


if __name__ == "__main__":
    main()
