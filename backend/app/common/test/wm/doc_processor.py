#!/usr/bin/env python3
"""
通用文档处理器
支持 PDF, DOCX, XLSX, 图片, 音频 (需要 asr 扩展)
"""

import logging
from pathlib import Path
from typing import Optional, Union

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

# Docling 核心库
from docling.document_converter import DocumentConverter, PdfFormatOption

# 音频处理相关 (可选)
try:
    from docling.datamodel.pipeline_options import AsrPipelineOptions
    from docling.document_converter import AudioFormatOption

    AUDIO_SUPPORT: bool = True

except ImportError:
    AUDIO_SUPPORT = False
    logging.warning("未安装 audio 支持。请运行: uv add 'docling[asr]' 来启用语音功能。")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Markdown(str):
    """自定义 Markdown 类型，方便类型提示和 IDE 识别"""

    pass


class UniversalDocProcessor:
    """
    通用文档处理器类
    封装了 Docling 的强大功能，提供统一的转换接口
    """

    def __init__(self, artifacts_path: str = "/home/will_m/.cache/docling/models"):
        """
        初始化处理器

        Args:
            artifacts_path: 模型缓存路径，默认是你已下载的路径
        """
        self.artifacts_path = artifacts_path

        # 配置 PDF 处理选项 (启用 GPU 加速的 Layout 和 Table 模型)
        pipeline_options = PdfPipelineOptions(
            artifacts_path=self.artifacts_path,
            do_table_structure=True,  # 启用表格识别
            do_ocr=True,  # 启用 OCR (对扫描件有效)
        )

        # 初始化转换器
        # 我们只为 PDF 指定特殊选项，其他格式使用默认配置即可
        format_options: dict[InputFormat, PdfFormatOption | AudioFormatOption] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        # 如果支持音频，添加音频选项
        if AUDIO_SUPPORT:
            format_options[InputFormat.AUDIO] = AudioFormatOption(
                pipeline_options=AsrPipelineOptions()
            )

        self.converter = DocumentConverter(format_options=format_options)  # ty:ignore[invalid-argument-type]

    def convert(
        self,
        file_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        save_file: bool = True,
    ) -> Markdown:
        """
        转换文档为 Markdown

        Args:
            file_path: 输入文件路径 (支持 PDF, DOCX, XLSX, PNG, JPG, MP3, WAV 等)
            output_path: 输出 Markdown 文件路径 (可选)
            save_file: 是否保存为文件 (默认 True)

        Returns:
            Markdown 文本
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(f"正在处理: {file_path.name}")

        # 执行转换 (Docling 会自动识别格式)
        result = self.converter.convert(str(file_path))

        # 导出为 Markdown
        markdown_content = result.document.export_to_markdown()

        # 处理输出路径
        if output_path is None:
            output_path = file_path.with_suffix(".md")
        else:
            output_path = Path(output_path)

        # 保存文件
        if save_file:
            output_path.write_text(markdown_content, encoding="utf-8")
            logger.info(f"✓ 已保存: {output_path}")

        return Markdown(markdown_content)

    def convert_batch(
        self, file_paths: list[Union[str, Path]], output_dir: Union[str, Path]
    ) -> list[Markdown]:
        """
        批量转换文档

        Args:
            file_paths: 文件路径列表
            output_dir: 输出目录

        Returns:
            Markdown 文本列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for file_path in file_paths:
            try:
                file_path = Path(file_path)
                output_file = output_dir / f"{file_path.stem}.md"
                markdown = self.convert(file_path, output_file)
                results.append(markdown)
            except Exception as e:
                logger.error(f"处理失败 {file_path}: {e}")
                results.append(Markdown(""))  # 失败时返回空字符串

        return results


# ============================================
# 使用示例
# ============================================
if __name__ == "__main__":
    from . import (
        DOCX_PATH,
        PDF_PATH,
        XLSX_PATH,
    )

    # 初始化处理器
    processor = UniversalDocProcessor()

    print("=" * 60)
    print("支持的格式: PDF, DOCX, XLSX, PPTX, PNG, JPG, HTML, MD")
    if AUDIO_SUPPORT:
        print("语音支持: 已启用 (MP3, WAV, FLAC 等)")
    print("=" * 60)

    for idx, path in enumerate(
        (
            DOCX_PATH,
            PDF_PATH,
            XLSX_PATH,
        )
    ):
        if path.exists():
            print(f"\n[{idx + 1}] Converting {path.suffix.upper()}:")
            md = processor.convert(path)
            print(f"预览 (前100字): {md[:100]}...\n")
