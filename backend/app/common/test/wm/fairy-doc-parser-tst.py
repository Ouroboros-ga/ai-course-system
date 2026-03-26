from magic_doc.docconv import DocConverter
from __init__ import *

FILE_PATH = DOC_PATH

# noinspection PyTypeChecker
converter = DocConverter(s3_config=None)  # 不使用 S3 配置时，默认处理本地文件

# 支持的文件类型：PPT/PPTX/DOC/DOCX/PDF
markdown_content, time_cost = converter.convert2md(str(FILE_PATH), conv_timeout=300)

print(f"耗时：{time_cost}")
print(f"Length: {len(markdown_content)}")
print("Markdown 内容：")
print(markdown_content)
