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

from docling.document_converter import DocumentConverter, PdfFormatOption

try:
    from docling.datamodel.pipeline_options import AsrPipelineOptions
    from docling.document_converter import AudioFormatOption

    AUDIO_SUPPORT: bool = True

except ImportError:
    AUDIO_SUPPORT = False
    logging.warning("未安装 audio 支持。请运行: uv add 'docling[asr]' 来启用语音功能。")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Markdown(str):
    pass


class UniversalDocProcessor:
    def __init__(self, artifacts_path: Optional[str] = None):
        self.artifacts_path = artifacts_path

        pipeline_options = PdfPipelineOptions(
            do_table_structure=True,
            do_ocr=True,
        )

        if self.artifacts_path:
            pipeline_options.artifacts_path = self.artifacts_path

        format_options: dict[InputFormat, PdfFormatOption | AudioFormatOption] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        if AUDIO_SUPPORT:
            format_options[InputFormat.AUDIO] = AudioFormatOption(
                pipeline_options=AsrPipelineOptions()
            )

        self.converter = DocumentConverter(format_options=format_options)

    def convert(
        self,
        file_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        save_file: bool = True,
    ) -> Markdown:
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(f"正在处理: {file_path.name}")

        result = self.converter.convert(str(file_path))

        markdown_content = result.document.export_to_markdown()

        if output_path is None:
            output_path = file_path.with_suffix(".md")
        else:
            output_path = Path(output_path)

        if save_file:
            output_path.write_text(markdown_content, encoding="utf-8")
            logger.info(f"已保存: {output_path}")

        return Markdown(markdown_content)

    def convert_batch(
        self, file_paths: list[Union[str, Path]], output_dir: Union[str, Path]
    ) -> list[Markdown]:
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
                results.append(Markdown(""))

        return results
