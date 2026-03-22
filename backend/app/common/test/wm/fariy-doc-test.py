"""
测试 fairy-doc 基础功能
"""


def test_import():
    """测试模块导入"""
    print("=" * 60)
    print("测试 1: 模块导入")
    print("=" * 60)

    # 尝试不同的导入方式
    import_attempts = [
        ("fairy_doc", "fairy_doc"),
        ("magic_doc", "magic_doc"),
        ("magic_doc.api", "magic_doc.api"),
    ]

    for module_name, import_name in import_attempts:
        try:
            module = __import__(import_name)
            print(f"✓ 成功导入: {module_name}")
            print(f"  版本: {getattr(module, '__version__', '未知')}")
            print(f"  路径: {getattr(module, '__file__', '未知')}")

            # 列出主要功能
            public_items = [item for item in dir(module) if not item.startswith("_")]
            print(f"  主要功能: {public_items[:10]}")

            return module
        except ImportError as e:
            print(f"✗ 导入 {module_name} 失败: {e}")
            continue

    print("\n✗ 所有导入尝试均失败")
    return None


def test_dependencies():
    """测试关键依赖"""
    print("\n" + "=" * 60)
    print("测试 2: 关键依赖")
    print("=" * 60)

    dependencies = [
        ("jinja2", "Jinja2"),
        ("torch", "PyTorch"),
        ("transformers", "Transformers"),
    ]

    for module_name, display_name in dependencies:
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "未知")
            print(f"✓ {display_name}: {version}")
        except ImportError:
            print(f"✗ {display_name}: 未安装")


def test_gpu_availability():
    """测试 GPU 可用性"""
    print("\n" + "=" * 60)
    print("测试 3: GPU 可用性")
    print("=" * 60)

    try:
        import torch

        print(f"CUDA 可用: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"CUDA 版本: {torch.version.cuda}")
            print(f"GPU 数量: {torch.cuda.device_count()}")
            print(f"GPU 名称: {torch.cuda.get_device_name(0)}")
        else:
            print("⚠ CUDA 不可用，将使用 CPU 模式")
    except ImportError:
        print("✗ PyTorch 未安装")


def test_basic_functionality():
    """测试基本功能"""
    print("\n" + "=" * 60)
    print("测试 4: 基本功能测试")
    print("=" * 60)

    # 创建测试文件
    test_text = """
这是一个测试文档。
包含多行文本。
用于测试 fairy-doc 的文本处理功能。
"""

    test_file = "test_document.txt"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(test_text)

    print(f"✓ 创建测试文件: {test_file}")

    # 尝试不同的 API 调用方式
    try:
        # 方式 1: 使用 magic_doc
        try:
            from magic_doc import DocumentParser

            parser = DocumentParser()
            result = parser.parse(test_file)
            print("✓ 使用 magic_doc.DocumentParser 成功")
            print(f"  解析结果: {result[:100] if result else '空'}")
            return True

        except (ImportError, AttributeError):
            pass

        # 方式 2: 使用其他可能的 API
        try:
            from magic_doc.api import parse_document

            result = parse_document(test_file)
            print("✓ 使用 magic_doc.api.parse_document 成功")
            print(f"  解析结果: {result[:100] if result else '空'}")
            return True

        except (ImportError, AttributeError):
            pass

        # 方式 3: 直接使用模块函数
        try:
            import magic_doc

            if hasattr(magic_doc, "parse"):
                result = magic_doc.parse(test_file)
                print("✓ 使用 magic_doc.parse 成功")
                print(f"  解析结果: {result[:100] if result else '空'}")
                return True

        except Exception:
            pass

        print("⚠ 未找到可用的 API 接口")
        print("  请查看模块文档了解正确的使用方法")
        return False

    except Exception as e:
        print(f"✗ 功能测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False


def show_usage_examples():
    """显示使用示例"""
    print("\n" + "=" * 60)
    print("常见使用方式示例")
    print("=" * 60)

    examples = """
# 示例 1: 基本文档解析
from magic_doc import DocumentParser

parser = DocumentParser()
result = parser.parse("document.pdf")
print(result)

# 示例 2: 使用 GPU 加速
from magic_doc import DocumentParser

parser = DocumentParser(device='cuda')
result = parser.parse("document.pdf")

# 示例 3: 批量处理
from magic_doc import DocumentParser
import glob

parser = DocumentParser()
for file in glob.glob("*.pdf"):
    result = parser.parse(file)
    print(f"{file}: {len(result)} 字符")

# 示例 4: 自定义配置
from magic_doc import DocumentParser, Config

config = Config(
    ocr_engine='tesseract',
    use_gpu=True,
    language='chi_sim+eng'
)
parser = DocumentParser(config=config)
result = parser.parse("scanned_document.pdf")
"""
    print(examples)


def main():
    print("Fairy-Doc 功能测试程序")
    print("=" * 60)

    # 运行测试
    module = test_import()
    test_dependencies()
    test_gpu_availability()

    if module:
        test_basic_functionality()

    show_usage_examples()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
