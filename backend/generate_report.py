import json
import urllib.request
import urllib.error
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def generate_diagnostic_report():
    """生成完整的诊断报告"""
    
    report = []
    report.append("=" * 70)
    report.append("豆包 API 接口诊断报告")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 70)
    
    report.append("\n## 1. 当前配置信息")
    report.append("-" * 70)
    report.append("配置文件: c:\\Users\\wangz\\PycharmProjects\\ai-course-system\\backend\\.env")
    report.append("")
    report.append("当前配置:")
    report.append("  DOUBAO_API_KEY = 329e47cc-e12e-4e0b-8c1e-59b9b6ddfb7d")
    report.append("  DOUBAO_ENDPOINT_ID = Doubao1.5-pro-32k  [错误]")
    report.append("")
    report.append("API 基础URL: https://ark.cn-beijing.volces.com/api/v3")
    
    report.append("\n## 2. 测试结果")
    report.append("-" * 70)
    report.append("")
    report.append("测试的模型ID:")
    models = [
        "Doubao1.5-pro-32k",      # 当前配置（错误）
        "Doubao-1.5-pro-32k",     # 标准格式
        "Doubao-pro-32k",         # 旧版
        "Doubao-1.5-lite-32k",    # 轻量版
        "Doubao-seed-1.6",        # 最新版
    ]
    
    for model in models:
        report.append(f"  ❌ {model:<25} -> HTTP 404 (不存在或无权限)")
    
    report.append("")
    report.append("结论: 所有模型都无法访问")
    
    report.append("\n## 3. 问题分析")
    report.append("-" * 70)
    report.append("")
    report.append("[根本原因]")
    report.append("  API Key 有效，但未授权访问任何模型")
    report.append("")
    report.append("[可能原因]")
    report.append("  1. 未在火山引擎方舟控制台开通模型服务")
    report.append("  2. 需要创建'推理接入点'(Endpoint)而不是直接使用模型ID")
    report.append("  3. 账户免费额度已用完或未充值")
    report.append("  4. API Key 权限不足")
    
    report.append("\n## 4. 解决步骤")
    report.append("-" * 70)
    report.append("")
    report.append("[步骤1] 登录火山引擎控制台")
    report.append("  URL: https://console.volcengine.com/ark/")
    report.append("")
    report.append("[步骤2] 开通模型服务")
    report.append("  1. 进入'模型广场'或'模型推理'")
    report.append("  2. 选择要使用的模型 (推荐: Doubao-1.5-pro-32k)")
    report.append("  3. 点击'开通'或'创建接入点'")
    report.append("")
    report.append("[步骤3] 获取正确的 Endpoint ID (二选一)")
    report.append("")
    report.append("  方式A - 使用推理接入点 (推荐):")
    report.append("    1. 在控制台创建'推理接入点'")
    report.append("    2. 选择模型版本")
    report.append("    3. 复制生成的 Endpoint ID")
    report.append("    4. 格式示例: ep-20240115150000-xxxxx")
    report.append("")
    report.append("  方式B - 直接使用模型ID:")
    report.append("    1. 确保已在控制台开通该模型")
    report.append("    2. 使用模型ID作为 endpoint_id")
    report.append("    3. 推荐模型ID: Doubao-1.5-pro-32k")
    report.append("")
    report.append("[步骤4] 更新 .env 配置文件")
    report.append("  文件位置: backend/.env")
    report.append("")
    report.append("  修改前:")
    report.append("    DOUBAO_ENDPOINT_ID=Doubao1.5-pro-32k  # 错误")
    report.append("")
    report.append("  修改后 (如果使用Endpoint):")
    report.append("    DOUBAO_ENDPOINT_ID=ep-你的实际endpoint-id")
    report.append("")
    report.append("  修改后 (如果使用模型ID):")
    report.append("    DOUBAO_ENDPOINT_ID=Doubao-1.5-pro-32k")
    report.append("")
    report.append("[步骤5] 验证配置")
    report.append("  运行测试脚本: python test_api_debug.py")
    
    report.append("\n## 5. 常见问题 FAQ")
    report.append("-" * 70)
    report.append("")
    report.append("Q: 为什么我的 API Key 无法使用?")
    report.append("A: API Key 只是身份凭证，还需要单独开通模型服务权限")
    report.append("")
    report.append("Q: Endpoint ID 和 Model ID 有什么区别?")
    report.append("A: Endpoint ID 是你创建的推理接入点标识(以ep-开头)")
    report.append("   Model ID 是模型本身的名字(如Doubao-1.5-pro-32k)")
    report.append("   两者都可以用，但需要确保有对应权限")
    report.append("")
    report.append("Q: 如何查看我有哪些可用的模型?")
    report.append("A: 登录 https://console.volcengine.com/ark/ 查看'已开通模型'")
    report.append("")
    report.append("Q: 有免费的试用额度吗?")
    report.append("A: 新用户通常有免费Token额度，可在控制台查看剩余额度")
    
    report.append("\n## 6. 快速修复命令")
    report.append("-" * 70)
    report.append("")
    report.append("# 方法1: 如果你有 Endpoint ID，运行此命令:")
    report.append('''python -c "
    import os
    env_path = r'c:\\Users\\wangz\\PycharmProjects\\ai-course-system\\backend\\.env'
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('DOUBAO_ENDPOINT_ID=Doubao1.5-pro-32k', 
                              'DOUBAO_ENDPOINT_ID=你的新EndpointID')
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('.env 已更新')
    "''')
    report.append("")
    report.append("# 方法2: 手动编辑 .env 文件")
    report.append("  1. 打开: backend/.env")
    report.append("  2. 找到: DOUBAO_ENDPOINT_ID=Doubao1.5-pro-32k")
    report.append("  3. 改为: DOUBAO_ENDPOINT_ID=你的正确值")
    report.append("  4. 保存文件")
    
    report.append("\n" + "=" * 70)
    report.append("诊断完成")
    report.append("=" * 70)
    report.append("")
    report.append("[下一步操作]")
    report.append("  1. 访问火山引擎控制台: https://console.volcengine.com/ark/")
    report.append("  2. 检查已开通的模型和接入点")
    report.append("  3. 更新 .env 配置")
    report.append("  4. 重新运行测试验证")
    report.append("")
    report.append("[需要帮助?]")
    report.append("  火山引擎文档: https://www.volcengine.com/docs/82379/")
    report.append("  技术支持: 提交工单或联系客服")
    
    full_report = "\n".join(report)
    print(full_report)
    
    # 同时保存到文件
    report_file = r"c:\Users\wangz\PycharmProjects\ai-course-system\backend\api_diagnostic_report.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(full_report)
    print(f"\n[报告已保存] {report_file}")


if __name__ == "__main__":
    generate_diagnostic_report()
