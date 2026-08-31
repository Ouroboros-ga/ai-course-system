from dataclasses import dataclass

from app.platform.document_intelligence.canonical.block_noise import (
    classify_noise_blocks,
    detect_noise_block_ids,
    filter_noise_blocks,
    is_cover_signature_line,
    is_furniture_line,
)


@dataclass
class FakeBlock:
    block_id: str
    text: str
    page_or_slide: int


HEADER_TEXT = "C++ 程序设计 第五章 C++ 程序结构 沈阳航空工业学院 李照奎"


def test_running_header_detected_across_pages():
    blocks = [
        FakeBlock(f"blk_header_{page}", HEADER_TEXT, page)
        for page in range(1, 8)
    ] + [
        FakeBlock("blk_body_1", "作用域是一个标识符在程序正文中有效的区域。作用域开始于标示符的声明处。", 1),
        FakeBlock("blk_body_2", "函数原型中的参数，其作用域始于函数声明，结束于函数声明结尾。", 3),
    ]
    noise = detect_noise_block_ids(blocks)
    assert all(f"blk_header_{page}" in noise for page in range(1, 8))
    assert "blk_body_1" not in noise
    assert "blk_body_2" not in noise


def test_cover_signature_line_single_occurrence_detected():
    blocks = [FakeBlock("blk_cover", HEADER_TEXT, 1)]
    assert detect_noise_block_ids(blocks) == {"blk_cover"}


def test_furniture_lines_detected():
    for text in ("3", "第 12 页", "2026-08-31", "2026年8月31日", "user@example.com", "https://example.com/a"):
        assert is_furniture_line(text), text
    assert not is_furniture_line("C++ 属于函数驱动机制，从 main 函数开始启动。")


def test_cover_signature_rules_do_not_hit_real_sentences():
    assert is_cover_signature_line(HEADER_TEXT)
    # Sentence punctuation or no trailing name => real content stays.
    assert not is_cover_signature_line("本课程介绍 C++ 程序设计的基本概念与方法。")
    assert not is_cover_signature_line("作用域讨论的是标识符在程序中的有效范围")
    assert not is_cover_signature_line("大学期间应打好程序设计基础" * 20)


def test_short_teaching_titles_survive():
    blocks = [
        FakeBlock("blk_kp", "程序结构：", 1),
        FakeBlock("blk_body", "使程序得以运行的框架组织便是程序结构。", 1),
        FakeBlock("blk_body2", "具有更好的可读性和可维护性。", 1),
    ]
    assert detect_noise_block_ids(blocks) == set()


def test_filter_noise_blocks_preserves_order():
    blocks = [
        FakeBlock("blk_a", "正文第一段，介绍作用域的概念。", 1),
        FakeBlock("blk_h", HEADER_TEXT, 1),
        FakeBlock("blk_b", "正文第二段，介绍可见性的概念。", 2),
    ]
    kept = filter_noise_blocks(blocks)
    assert [b.block_id for b in kept] == ["blk_a", "blk_b"]


def test_empty_and_missing_text_ignored():
    blocks = [FakeBlock("blk_empty", "", 1), FakeBlock("blk_space", "   ", 2)]
    assert detect_noise_block_ids(blocks) == set()


def test_reason_coded_gate_rejects_non_educational_fragments():
    blocks = [
        FakeBlock("blk_roman", "VI", 6),
        FakeBlock("blk_pua", "\uf06c P3", 3),
        FakeBlock("blk_promo", "┃算法训练营：海量图解+竞赛刷题", 1),
        FakeBlock("blk_symbol", "= 12.29", 9),
        FakeBlock("blk_figure", "图 2-28", 10),
    ]

    assert classify_noise_blocks(blocks) == {
        "blk_roman": "roman_page_marker",
        "blk_pua": "private_use_fragment",
        "blk_promo": "decorative_promotion",
        "blk_symbol": "symbol_residue",
        "blk_figure": "bare_figure_label",
    }


def test_reason_coded_gate_preserves_teaching_content_code_and_real_formulas():
    @dataclass
    class TypedBlock(FakeBlock):
        block_type: str = "text"

    blocks = [
        TypedBlock("blk_title", "栈", 1),
        TypedBlock("blk_bullet", "\uf06c 作用域定义", 2),
        TypedBlock("blk_bullet_api", "\uf06c API", 2),
        TypedBlock("blk_formula", "𝑄 = 𝑄 + 𝑊(𝑄)", 3),
        TypedBlock("blk_formula_ascii", "COP=Q/W", 3),
        TypedBlock("blk_code", "i++", 4, block_type="code"),
    ]

    assert classify_noise_blocks(blocks) == {}
