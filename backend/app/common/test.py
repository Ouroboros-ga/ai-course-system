from ppt_parser import PPTParser

# 初始化解析器
parser = PPTParser(extract_images=False)

# 解析 PPT（这里会自动读取你传入的文件）
result = parser.parse("test_pptx.pptx")

# 输出整体信息

print(f"文件名：{result.file_name}")
print(f"总页数：{result.slide_count}")
print("=" * 50)

# 遍历打印 所有页
for slide in result.slides:
    print(f"第 {slide.slide_number} 页 标题：{slide.title}")
    print(f"正文：{slide.text_raw}")
    print(f"备注：{slide.notes}")
    print("-" * 50)
