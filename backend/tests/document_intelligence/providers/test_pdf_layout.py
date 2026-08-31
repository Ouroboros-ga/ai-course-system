"""Tests for box-aware pdfplumber layout analysis.

Reproduces the three evidence-quality defects reported on converted slide
decks: (1) parallel text boxes interleaving into one line, (2) wrapped code
split into visual-line fragments, (3) standalone formula residue.  Uses a
lightweight fake pdfplumber page so expectations stay deterministic.
"""
from __future__ import annotations

from app.platform.document_intelligence.providers.pdf_layout import (
    extract_page_blocks,
)


def word(text, x0, x1, top, bottom, size=20, font="NotoSansCJKjp-Bold-VKana"):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": bottom,
            "size": size, "fontname": font}


class FakePage:
    def __init__(self, words, width=720.0, height=540.0):
        self._words = words
        self.width = width
        self.height = height

    def extract_words(self, **_kwargs):
        return list(self._words)


class TestParallelBoxesStaySeparate:
    """Left bullet column + right annotation box must not interleave."""

    def test_columns_do_not_merge_into_one_line(self):
        page = FakePage([
            word("函数原型中的参数，", 55, 300, 300, 320),
            word("其作用域始于", 55, 240, 324, 344),
            word("width, length", 438, 560, 316, 336),
            word("的作用域仅在", 438, 540, 340, 360),
        ])
        blocks = extract_page_blocks(page)

        texts = [blk["text"] for blk in blocks]
        left = next(t for t in texts if "函数原型" in t)
        right = next(t for t in texts if "width" in t)
        # each column's lines flow within its own block
        assert "其作用域始于" in left
        assert "的作用域仅在" in right
        assert "width" not in left and "函数原型" not in right

    def test_box_code_and_text_never_share_a_block(self):
        page = FakePage([
            word("块作用域也称局部作用域。当声明出现在程序块内时，", 55, 640, 100, 124, size=24),
            word("该标示符的作用域从声明点开始，到块结束处为止。", 55, 640, 128, 152, size=24),
            word("void fun()", 178, 300, 200, 220),
            word("{", 178, 190, 224, 244),
            word("int b;", 178, 240, 248, 268),
            word("cin>>b;", 178, 280, 272, 292),
            word("}", 178, 190, 296, 316),
        ])
        blocks = extract_page_blocks(page)

        code = [blk for blk in blocks if blk["block_type"] == "code"]
        assert len(code) == 1
        assert "void fun()" in code[0]["text"]
        assert "cin>>b;" in code[0]["text"]
        # CJK body paragraph must not leak into the code block
        assert "块作用域" not in code[0]["text"]

        text = [blk for blk in blocks if blk["block_type"] == "paragraph"]
        assert text and "块作用域" in text[0]["text"]
        assert "void fun()" not in text[0]["text"]


class TestCodeBoxIntegrity:
    """A code region must survive as one block with preserved line breaks."""

    def test_wrapped_code_lines_merge_with_newlines(self):
        page = FakePage([
            word("#include <iostream>", 178, 380, 128, 148),
            word("// 声明函数", 178, 300, 152, 172),
            word("double Area(double width, double length);", 178, 615, 176, 196),
            word("void main(){", 178, 320, 224, 244),
        ])
        blocks = extract_page_blocks(page)

        code = [blk for blk in blocks if blk["block_type"] == "code"]
        assert len(code) == 1
        assert code[0]["text"].split("\n") == [
            "#include <iostream>",
            "// 声明函数",
            "double Area(double width, double length);",
            "void main(){",
        ]

    def test_narrow_brace_line_joins_code_box(self):
        page = FakePage([
            word("void main()", 178, 300, 360, 380),
            word("{", 181, 190, 384, 404),
            word("f ( ) ;", 91, 140, 432, 452),
            word("}", 73, 82, 456, 476),
        ])
        blocks = extract_page_blocks(page)

        code = [blk for blk in blocks if blk["block_type"] == "code"]
        assert len(code) == 1
        assert code[0]["text"].count("\n") == 3

    def test_cjk_wrap_tail_glues_to_code_line(self):
        page = FakePage([
            word("double Area(double width ， double length);// width 并", 91, 705, 420, 440),
            word("无重复定义", 109, 219, 448, 468),
            word("Length=10;// 错： length 无定义", 91, 429, 480, 500),
        ])
        blocks = extract_page_blocks(page)

        code = [blk for blk in blocks if blk["block_type"] == "code"]
        assert len(code) == 1
        lines = code[0]["text"].split("\n")
        assert lines[0].endswith("并无重复定义")
        assert "Length=10" in lines[1]

    def test_side_by_side_code_columns_stay_isolated(self):
        page = FakePage([
            word("// item1.cpp", 73, 194, 239, 259),
            word("# include<iostream>", 73, 271, 263, 283),
            word("using namespace std ;", 73, 291, 287, 307),
            word("// item2.cpp", 397, 518, 244, 264),
            word("# include<iostream>", 397, 595, 273, 293),
            word("using namespace std ;", 397, 615, 302, 322),
        ])
        blocks = extract_page_blocks(page)

        code = [blk for blk in blocks if blk["block_type"] == "code"]
        assert len(code) == 2
        left, right = code
        assert "item1" in left["text"] and "item2" not in left["text"]
        assert "item2" in right["text"] and "item1" not in right["text"]


class TestParagraphIntegrity:
    """Wrapped sentences merge; CJK joins without injected spaces."""

    def test_wrapped_sentence_becomes_one_paragraph(self):
        page = FakePage([
            word("作用域讨论的是标识符在程序中的有效范围；可见性是标识符是否", 14, 680, 100, 124, size=22),
            word("可以引用的问题。", 13, 189, 132, 156, size=22),
        ])
        blocks = extract_page_blocks(page)

        paras = [blk for blk in blocks if blk["block_type"] == "paragraph"]
        assert len(paras) == 1
        assert paras[0]["text"] == "作用域讨论的是标识符在程序中的有效范围；可见性是标识符是否可以引用的问题。"

    def test_bullet_lines_split_into_separate_paragraphs(self):
        page = FakePage([
            word("• 函数原型中的参数，其作用域始于\"(\"，结束于\")\"。", 55, 407, 300, 324, size=22),
            word("• 例如，设有下列原型声明：", 55, 341, 356, 380, size=22),
        ])
        blocks = extract_page_blocks(page)

        paras = [blk for blk in blocks if blk["block_type"] == "paragraph"]
        assert len(paras) == 2
        assert paras[0]["text"].startswith("• 函数原型")
        assert paras[1]["text"].startswith("• 例如")

    def test_cjk_words_join_without_spaces(self):
        page = FakePage([
            word("当", 55, 77, 100, 124, size=24),
            word("标示符的声明出现在由一对花括号所括起来的一段程序块", 55, 580, 100, 124, size=24),
            word("内时，该标示符的作用域从声明点开始。", 55, 430, 128, 152, size=24),
        ])
        blocks = extract_page_blocks(page)

        paras = [blk for blk in blocks if blk["block_type"] == "paragraph"]
        assert len(paras) == 1
        assert "当标示符的声明" in paras[0]["text"]
        assert "开始。内时" not in paras[0]["text"]  # reading order kept


class TestNoiseAndFormula:
    """Slide furniture filtered; formula residue absorbed, not standalone."""

    def test_running_header_and_cover_signature_filtered(self):
        page = FakePage([
            word("C++ 程序设计 第五章 C++ 程序结构 沈阳航空工业学院 李照奎", 79, 636, 20, 44, size=20,
                 font="NotoSansCJKjp-Regular-VKana"),
            word("块作用域", 19, 120, 72, 100, size=24),
            word("块作用域也称局部作用域。", 55, 640, 120, 144, size=24),
        ])
        blocks = extract_page_blocks(page)

        joined = "\n".join(blk["text"] for blk in blocks)
        assert "李照奎" not in joined

    def test_formula_residue_absorbed_into_paragraph(self):
        page = FakePage([
            word("两个形参的作用域如下推导：", 55, 340, 200, 224, size=24),
            word("width*length", 55, 190, 230, 254, size=24),
        ])
        blocks = extract_page_blocks(page)

        paras = [blk for blk in blocks if blk["block_type"] == "paragraph"]
        standalone = [blk for blk in paras if blk["text"] == "width*length"]
        assert not standalone
        assert any("推导：" in blk["text"] and "width*length" in blk["text"] for blk in paras)

    def test_slide_title_promoted_to_heading(self):
        page = FakePage([
            word("块作用域 ( 局部作用域 )", 19, 280, 72, 110, size=28),
            word("块作用域也称局部作用域。当声明出现在程序块内时，", 55, 640, 140, 168, size=24),
            word("该作用域的范围具有局部性。", 55, 400, 172, 200, size=24),
        ])
        blocks = extract_page_blocks(page)

        headings = [blk for blk in blocks if blk["block_type"] == "heading"]
        assert len(headings) == 1
        assert headings[0]["text"] == "块作用域 ( 局部作用域 )"
        assert headings[0]["heading_level"] == 1

    def test_empty_page_yields_no_blocks(self):
        assert extract_page_blocks(FakePage([])) == []


class TestSpacedTitleAndSymbolResidue:
    """Regressions found on real decks: letter-spaced titles and math-glyph
    diagram labels that survive as orphan blocks."""

    def test_letter_spaced_title_stays_whole(self):
        # course3 p3 geometry: 40pt title, 41pt letter-space gap before 论
        page = FakePage([
            word("第一章绪", 203, 383, 65, 105, size=40),
            word("论", 424, 464, 65, 105, size=40),
            word("本章介绍绪论的基本概念和意义。", 100, 600, 160, 180, size=20),
            word("绪论部分包括研究背景。", 100, 500, 190, 210, size=20),
        ])
        blocks = extract_page_blocks(page)

        headings = [blk for blk in blocks if blk["block_type"] == "heading"]
        assert len(headings) == 1
        assert headings[0]["text"] == "第一章绪论"

    def test_math_glyph_residue_dropped_real_equation_kept(self):
        page = FakePage([
            word("制冷系数定义如下。", 55, 300, 100, 120, size=20),
            word("𝑄 = 𝑄 + 𝑊(𝑄)", 60, 300, 200, 220, size=18),
            word("𝑘", 400, 415, 300, 315, size=14),
            word("= 12.29", 60, 130, 400, 415, size=14),
            word("COP=Q/W", 400, 560, 440, 460, size=14),
        ])
        blocks = extract_page_blocks(page)

        texts = [blk["text"] for blk in blocks]
        assert "𝑘" not in texts
        assert "= 12.29" not in texts
        assert "𝑄 = 𝑄 + 𝑊(𝑄)" in texts
        assert "COP=Q/W" in texts
