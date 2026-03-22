#!/usr/bin/env python3
"""
通用文档处理器
支持 PDF, DOCX, XLSX, 图片, 音频 (需要 asr 扩展)
支持 CPU / GPU 一键切换
"""

import logging
import os
import platform
from pathlib import Path
from typing import Optional, Union

import torch


# ==========================================
# 核心逻辑：设备选择与环境配置
# ==========================================
def resolve_device(device_preference: str = "auto") -> str:
    """
    解析并设置运行设备.
    返回: "cuda" 或 "cpu"
    """
    device_preference = device_preference.lower()

    # 1. 强制 CPU 模式 (必须在导入 docling 或加载模型前设置)
    if device_preference == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        logging.info("⚙️ 配置: 强制 CPU 模式 (已屏蔽 CUDA)")
        return "cpu"

    # 2. 自动检测或强制 GPU
    if device_preference == "cuda" or device_preference == "auto":
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            logging.info(f"🚀 配置: 使用 GPU 加速 ({device_name})")
            return "cuda"
        else:
            if device_preference == "cuda":
                logging.warning("⚠️ 警告: 强制 GPU 模式，但未检测到 GPU，回退到 CPU")
            else:
                logging.info("✅ 配置: 未检测到 GPU，使用 CPU")
            return "cpu"

    return "cpu"


# ==========================================
# Docling 核心库导入
# ==========================================
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
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
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class Markdown(str):
    """自定义 Markdown 类型，方便类型提示和 IDE 识别"""
    pass


class UniversalDocProcessor:
    """
    通用文档处理器类
    封装了 Docling 的强大功能，支持 CPU/GPU 切换
    """

    def __init__(
            self,
            artifacts_path: str = "/home/will_m/.cache/docling/models",
            device: str = "cpu"
    ):
        """
        初始化处理器

        Args:
            artifacts_path: 模型缓存路径
            device: 运行设备 ("auto", "cuda", "cpu")
        """
        self.artifacts_path = artifacts_path

        # 解析并锁定设备配置
        self.device = resolve_device(device)

        # 配置 PDF 处理选项
        pipeline_options = PdfPipelineOptions(
            artifacts_path=self.artifacts_path,
            do_table_structure=True,  # 启用表格识别
            do_ocr=True,  # 启用 OCR
        )

        # 注意：Docling 的 PdfPipelineOptions 在新版本中通常自动检测 torch 设备
        # 如果 resolve_device() 设置了 CUDA_VISIBLE_DEVICES=""，Docling 会自动回退到 CPU

        # 初始化转换器
        format_options: dict[InputFormat, PdfFormatOption | AudioFormatOption] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        # 如果支持音频，添加音频选项
        if AUDIO_SUPPORT:
            # ASR (语音识别) 通常也可以利用 GPU
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
        """
        转换文档为 Markdown
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(f"正在处理: {file_path.name} [Device: {self.device.upper()}]")

        # 执行转换
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
                results.append(Markdown(""))

        return results


# ============================================
# 使用示例
# ============================================
if __name__ == "__main__":
    # 模拟导入测试文件路径 (实际使用时请替换为真实路径)
    # from config import DOCX_PATH, PDF_PATH, XLSX_PATH

    # 为了演示，这里假设一些测试文件
    PDF_PATH = Path("test.pdf")
    DOCX_PATH = Path("test.docx")
    XLSX_PATH = Path("test.xlsx")

    # ==========================================
    # 使用环境变量控制: DOCLING_DEVICE=cpu / cuda
    # 或者直接在代码中指定 device 参数
    # ==========================================

    # 方式 1: 自动检测 (默认)
    # processor = UniversalDocProcessor()

    # 方式 2: 强制 CPU (用于调试或显存不足时)
    # processor = UniversalDocProcessor(device="cpu")

    # 方式 3: 强制 GPU (如果不存在会自动回退)
    processor = UniversalDocProcessor(device="cuda")

    print("=" * 60)
    print(f"系统: {platform.system()} | 设备模式: {processor.device.upper()}")
    print("支持的格式: PDF, DOCX, XLSX, PPTX, PNG, JPG, HTML, MD")
    if AUDIO_SUPPORT:
        print("语音支持: 已启用 (MP3, WAV, FLAC 等)")
    print("=" * 60)

    # 模拟转换循环
    test_files = [PDF_PATH, DOCX_PATH, XLSX_PATH]

    for idx, path in enumerate(test_files):
        if path.exists():
            print(f"\n[{idx + 1}] Converting {path.suffix.upper()}:")
            try:
                md = processor.convert(path)
                print(f"预览 (前100字): {md[:100]}...\n")
            except Exception as e:
                print(f"Error: {e}")
