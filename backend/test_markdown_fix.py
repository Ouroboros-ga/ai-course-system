"""
测试Markdown生成修复效果
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.api.v1.endpoints.document import (
    _create_beautiful_markdown,
    _create_default_script,
)


def test_beautiful_markdown():
    """测试精美Markdown生成"""
    print("=" * 60)
    print("测试精美Markdown生成功能")
    print("=" * 60)
    
    script_content = {
        "title": "控制系统的数学模型",
        "summary": "本章介绍控制系统的时域和复数域数学模型，包括微分方程、传递函数等重要概念。",
        "keywords": ["微分方程", "传递函数", "拉氏变换", "结构图", "信号流图"],
        "total_duration": 600,
        "nodes": [
            {
                "chapter_id": "chap_001",
                "node_type": "lecture",
                "title": "动态数学模型的定义",
                "content": "动态数学模型是描述系统动态特性的数学表达式。最基本的动态数学模型是微分方程。",
                "page_start": 1,
                "page_end": 1,
                "duration": 60,
                "is_key_point": True,
            },
            {
                "chapter_id": "chap_002",
                "node_type": "lecture",
                "title": "建立微分方程的步骤",
                "content": "1. 确定输入量和输出量\n2. 列写各环节方程\n3. 消去中间变量",
                "page_start": 2,
                "page_end": 3,
                "duration": 90,
                "is_key_point": True,
            },
            {
                "chapter_id": "chap_003",
                "node_type": "summary",
                "title": "本章总结",
                "content": "本章学习了控制系统的数学模型，包括时域和复数域的表示方法。",
                "page_start": 10,
                "page_end": 10,
                "duration": 60,
                "is_key_point": False,
            },
        ],
    }
    
    filename = "控制系统的数学模型.pptx"
    
    markdown = _create_beautiful_markdown(script_content, filename)
    
    print("\n生成的精美Markdown内容：")
    print("-" * 60)
    print(markdown)
    print("-" * 60)
    
    assert "# 控制系统的数学模型" in markdown, "缺少一级标题"
    assert "## 课程简介" in markdown, "缺少课程简介"
    assert "### 关键词" in markdown, "缺少关键词部分"
    assert "## 课程内容" in markdown, "缺少课程内容"
    assert "⭐" in markdown, "缺少重点标记"
    assert "📌" in markdown, "缺少总结标记"
    assert "**微分方程**" in markdown, "关键词未加粗"
    
    print("\n✅ 所有断言通过！")
    print("\n验证项目：")
    print("  ✓ 包含一级标题")
    print("  ✓ 包含课程简介")
    print("  ✓ 包含关键词（已加粗）")
    print("  ✓ 包含课程内容")
    print("  ✓ 重点知识点有⭐标记")
    print("  ✓ 总结部分有📌标记")


def test_default_script():
    """测试默认脚本生成"""
    print("\n" + "=" * 60)
    print("测试默认脚本生成功能")
    print("=" * 60)
    
    content = """
    控制系统的数学模型
    动态数学模型的定义
    描述系统动态特性的数学表达式
    建立微分方程的步骤
    确定输入输出量，列写方程，消去中间变量
    """
    
    filename = "test.pptx"
    
    script = _create_default_script(filename, content)
    
    print("\n生成的默认脚本：")
    print("-" * 60)
    import json
    print(json.dumps(script, indent=2, ensure_ascii=False))
    print("-" * 60)
    
    assert "title" in script, "缺少标题"
    assert "nodes" in script, "缺少节点"
    assert len(script["nodes"]) > 0, "节点列表为空"
    
    print("\n✅ 默认脚本生成成功！")
    print(f"  生成了 {len(script['nodes'])} 个节点")


def test_markdown_structure():
    """测试Markdown结构完整性"""
    print("\n" + "=" * 60)
    print("测试Markdown结构完整性")
    print("=" * 60)
    
    script_content = _create_default_script("测试课程.pptx", "这是一个测试内容，用于验证Markdown生成的结构完整性。")
    markdown = _create_beautiful_markdown(script_content, "测试课程.pptx")
    
    lines = markdown.split("\n")
    
    h1_count = sum(1 for line in lines if line.startswith("# "))
    h2_count = sum(1 for line in lines if line.startswith("## "))
    h3_count = sum(1 for line in lines if line.startswith("### "))
    
    print(f"\nMarkdown结构统计：")
    print(f"  一级标题 (#): {h1_count}")
    print(f"  二级标题 (##): {h2_count}")
    print(f"  三级标题 (###): {h3_count}")
    
    assert h1_count >= 1, "至少需要1个一级标题"
    assert h2_count >= 2, "至少需要2个二级标题"
    
    print("\n✅ Markdown结构完整！")


if __name__ == "__main__":
    try:
        test_beautiful_markdown()
        test_default_script()
        test_markdown_structure()
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！修复验证成功！")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
