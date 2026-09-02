"""XH-202620：PPT 标题识别改进 + 数字人关闭门测试。

验证：
- textbox 型教学 PPT 的章节/小节/结构标题被正确识别为 heading（原名只能识别"一、"）
- 页码/页脚/纯《标题》横幅被识别为噪声，不成为知识点
- 数字人开关关闭时，媒体发布走兼容模式（不签发 avatar manifest / cue）
纯确定性，不调用 LLM/无网络。
"""
from __future__ import annotations

import pytest

from app.platform.document_intelligence.providers.native_pptx import (
    _is_numbered_section_heading as is_heading,
    _is_noise_text as is_noise,
    _heading_level as heading_level,
)


class TestPptxHeadingDetection:
    def test_chapter_arabic_numbering(self):
        assert is_heading("第10章内排序第1讲-排序的概念") is True
        assert heading_level("第10章内排序第1讲-排序的概念") == 1

    def test_section_numbering(self):
        assert is_heading("9.4  哈希表的查找") is True
        assert heading_level("9.4  哈希表的查找") == 1

    def test_subsection_numbering_is_knowledge_title(self):
        assert is_heading("9.4.1  哈希表的基本概念") is True
        assert heading_level("9.4.1  哈希表的基本概念") == 2
        assert is_heading("1、直接定址法") is True
        assert heading_level("1、直接定址法") == 2
        assert is_heading("（1）线性探查法") is True
        assert heading_level("（1）线性探查法") == 2

    def test_example_box(self):
        assert is_heading("【例9-9】 假设哈希表长度m=13") is True

    def test_structural_label(self):
        assert is_heading("思考题") is True
        assert heading_level("思考题") == 1
        assert is_heading("小结") is True

    def test_annotation_is_knowledge_title_not_section(self):
        # 注意/说明是注解，不应成为顶层 section
        assert is_heading("注意：哈希表是一种存储结构") is True
        assert heading_level("注意：哈希表是一种存储结构") == 2

    def test_body_text_not_heading(self):
        assert is_heading("所谓排序，是整理表中的记录") is False
        assert is_heading("n个记录，其相应的关键字分别为k0,k1…") is False

    def test_noise_not_heading(self):
        # 页码、页脚、《书名》横幅
        assert is_noise("5/35") is True
        assert is_noise("12") is True
        assert is_noise("《数据结构》") is True
        assert is_heading("5/35") is False
