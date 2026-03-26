#!/usr/bin/env python3
"""
通用文档处理器 (解耦版)
支持 PDF, DOCX, XLSX, 图片, 音频 (需要 asr 扩展)
支持 CPU / GPU 一键切换
支持 Windows / Linux 跨平台路径
请先运行
```bash
uv run docling-tools models download
```
"""

import logging
import os
import json
import platform
from pathlib import Path
from typing import Any, Optional, Union

if True:
    # 配置日志
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)
    # ==========================================
    # 核心修复：配置 HuggingFace 国内镜像源
    # ==========================================
    # 必须在导入 docling 或下载模型前设置
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    logger.info("⚙️ 已配置 HuggingFace 镜像源: hf-mirror.com")

import torch
# Docling 核心库导入
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
# ==========================================
# 类型检查与可选依赖处理
# ==========================================
try:
    # noinspection PyUnusedImports
    from docling.datamodel.pipeline_options import AsrPipelineOptions
    # noinspection PyUnusedImports
    from docling.document_converter import AudioFormatOption

    AUDIO_SUPPORT: bool = True
except ImportError:
    AUDIO_SUPPORT = False
    logging.warning("未安装 audio 支持。请运行: uv add 'docling[asr]' 来启用语音功能。")

# ==========================================
# 核心逻辑：设备选择与环境配置
# ==========================================
def resolve_device(device_preference: str = "cpu") -> str:
    """
    解析并设置运行设备.
    返回: "cuda" 或 "cpu"
    """
    device_preference = device_preference.lower()

    # 1. 强制 CPU 模式 (必须在导入 docling 或加载模型前设置)
    if device_preference == "cpu":
        # 1. 禁用 CUDA，让 torch 看不到显卡
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        # 2. 禁用 MPS (Mac 加速)，确保回退到 CPU
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
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


class Markdown(str):
    """Just for type hint"""
    pass


class Doc:
    """
    文档对象类
    封装解析结果，提供多种格式的导出方法
    """
    default_save_cnt: list[int] = [0]
    def __init__(self, file_path: Path, parsed_document: Any) -> None:
        """
        初始化文档对象

        Args:
            file_path: 原始文件路径
            parsed_document: Docling 解析后的内部文档对象
        """
        self.file_path = file_path
        self._doc = parsed_document

    def get_default_output_path(self, suffix: str="") -> Path:
        self.default_save_cnt[0] += 1
        return self.file_path.parent / f"output_{self.default_save_cnt[0]}.{suffix}"

    def save_as_md(self, output_path: Path | str | None = None) -> Markdown:
        """
        保存为 Markdown 文件

        Args:
            output_path: 指定输出路径，默认为源文件同目录下同名 .md 文件

        Returns:
            Markdown 文本
        """
        content = self._doc.export_to_markdown()

        resolved_output_path: Path
        if output_path is None:
            resolved_output_path = self.get_default_output_path("md")
        else:
            resolved_output_path = Path(output_path)

        resolved_output_path.write_text(content, encoding="utf-8")
        logger.info(f"✓ [MD] 已保存: {resolved_output_path}")
        return Markdown(content)

    def save_as_json(self, output_path: Path | str | None = None) -> dict[str, Any]:
        """
        保存为 JSON 文件

        Args:
            output_path: 指定输出路径，默认为源文件同目录下同名 .json 文件

        Returns:
            解析后的字典数据
        """
        # Docling 导出为字典
        content_dict: dict[str, Any] = self._doc.export_to_dict()

        resolved_output_path: Path
        if output_path is None:
            resolved_output_path = self.get_default_output_path("json")
        else:
            resolved_output_path = Path(output_path)

        with open(resolved_output_path, "w", encoding="utf-8") as f:
            json.dump(content_dict, f, ensure_ascii=False, indent=2)

        logger.info(f"✓ [JSON] 已保存: {resolved_output_path}")
        return content_dict

    @property
    def text(self) -> str:
        """获取纯文本内容 (Markdown 格式)"""
        return self._doc.export_to_markdown()


# ==========================================
# 处理器类
# ==========================================
class DocProcessor:
    """
    通用文档处理器类
    封装了 Docling 的强大功能，支持 CPU/GPU 切换
    """
    def __init__(
        self,
        artifacts_path: Optional[Union[str, Path]] = None,
        device: str = "cpu",
    ) -> None:
        """
        初始化处理器

        Args:
            artifacts_path: 模型缓存路径。默认为 None，自动使用用户目录下的 ~/.cache/docling/models
            device: 运行设备
        """
        # 跨平台路径处理
        if artifacts_path is None:
            # Path.home() 自动适配 Windows/Linux
            self.artifacts_path = Path.home() / ".cache" / "docling" / "models"
        else:
            self.artifacts_path = Path(artifacts_path)

        # 确保目录存在
        # if not self.artifacts_path.exists():
        #     logger.info(f"模型目录不存在，正在创建: {self.artifacts_path}")
        #     self.artifacts_path.mkdir(parents=True, exist_ok=True)

        # 解析并锁定设备配置
        self.device = resolve_device(device)

        # 配置 PDF 处理选项
        pipeline_options = PdfPipelineOptions(
            # artifacts_path=str(self.artifacts_path),  # 确保传入字符串
            do_table_structure=True,  # 启用表格识别
            do_ocr=False,  # 启用 OCR
        )

        # 初始化转换器
        format_options: dict[InputFormat, Any] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }

        # 如果支持音频，添加音频选项
        if AUDIO_SUPPORT:
            # ASR (语音识别) 通常也可以利用 GPU
            format_options[InputFormat.AUDIO] = AudioFormatOption(
                pipeline_options=AsrPipelineOptions()
            )

        self.converter = DocumentConverter(format_options=format_options)

    def parse_file(self, file_path: Path | str) -> Doc:
        """
        解析单个文件并返回 Doc 对象

        Args:
            file_path: 文件路径

        Returns:
            Doc 对象

        Raises:
            FileNotFoundError: 文件不存在时抛出
        """
        resolved_path = Path(file_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"文件不存在: {resolved_path}")

        logger.info(f"正在解析: {resolved_path.name} [Device: {self.device.upper()}]")

        # 执行核心解析
        result = self.converter.convert(str(resolved_path))

        # 返回封装后的 Doc 对象
        return Doc(file_path=resolved_path, parsed_document=result.document)


# ============================================
# 使用示例
# ============================================
if __name__ == "__main__":
    # 模拟导入测试文件路径 (实际使用时请替换为真实路径)
    from wm import DOCX_PATH, PDF_PATH, XLSX_PATH

    # ==========================================
    # 初始化处理器
    # ==========================================
    # 不传 artifacts_path，让它自动使用系统用户目录 (修复 Windows 报错的关键)
    processor = DocProcessor(device="cpu")

    print("=" * 60)
    print(f"系统: {platform.system()} | 设备模式: {processor.device.upper()}")
    print(f"模型路径: {processor.artifacts_path}")
    print("支持的格式: PDF, DOCX, XLSX, PPTX, PNG, JPG, HTML, MD")
    if AUDIO_SUPPORT:
        print("语音支持: 已启用 (MP3, WAV, FLAC 等)")
    print("=" * 60)

    # 模拟转换循环
    test_files = (PDF_PATH, DOCX_PATH, XLSX_PATH)

    for idx, path in enumerate(test_files):
        if path.exists():
            print(f"\n[{idx + 1}] Converting {path.suffix.upper()}:")
            try:
                doc = processor.parse_file(path)
                # 保存文件
                doc.save_as_md()
                doc.save_as_json()
                print(f"预览 (前100字): {doc.text[:100]}...\n")
            except Exception as e:
                print(f"Error: {e}")
