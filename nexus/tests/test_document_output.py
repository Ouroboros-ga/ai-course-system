"""SR6 正式输出：Markdown→docx/tex 确定性转换（纯函数，不经 LLM）。

行为契约：
- 支持子集即 T6 报告实际形状（h1-h3/段落/粗斜体/行内代码/代码围栏/
  无序有序列表/管道表格/分隔线/引用）；子集外降级正文，不丢行；
- .docx 为真正可编辑二进制（zip 完整＋必需部件＋document 可解析＋
  段落非空）， roundtrip 结构自检；
- .tex 自包含（ctexart＋xelatex 注释），结构＋转义＋括号三重自检；
  编译只在工具链存在时尝试（禁 shell-escape），缺席如实
  TOOLCHAIN_MISSING；
- 转换不改写事实：标题/命令/数字原文保留（抽查）。

全调用真实业务代码；无网络、无容器、无 LLM。
"""

from nexus import document_output as doc_module


SAMPLE_MD = """# 自主实验报告 · apv_1

**结论：执行成功 · 指标 not_evaluated · 干净验证 not_run**（确定性拼装）

- 目标：配置并试跑
- 仓库：https://github.com/example/r@deadbeef1234

## 做了什么

1. `pip install -r requirements.txt`（exit=0）
2. `python train.py`（exit=0）

## 修了什么

本次运行没有记录到失败的尝试。

```bash
pip install fakepkg
python train.py
```

| 指标 | 实测 | 期望 |
|---|---|---|
| val_loss | 1.89 | 1.88 |

> 引用：运行成功只表示命令跑通。

---
"""


def test_parse_covers_report_shapes():
    blocks = doc_module.parse_markdown_blocks(SAMPLE_MD)
    kinds = [b["kind"] for b in blocks]
    for expected in ("h1", "para", "ul", "h2", "ol", "code", "table",
                     "quote", "hr"):
        assert expected in kinds, kinds
    table = next(b for b in blocks if b["kind"] == "table")
    assert table["header"][0] == "指标"
    assert table["rows"][0][0] == "val_loss"


def test_inline_styles():
    segments = doc_module.inline_runs("a **b** *c* `d` e")
    assert ("bold", "b") in segments
    assert ("italic", "c") in segments
    assert ("code", "d") in segments
    assert "".join(seg for _, seg in segments) == "a b c d e"


def test_docx_roundtrip_valid_and_factual():
    import io
    import zipfile

    data = doc_module.markdown_to_docx_bytes(SAMPLE_MD, title="自主实验报告")
    assert data[:2] == b"PK"
    assert len(data) > 2000
    result = doc_module.validate_docx_bytes(data)
    assert result["ok"] is True, result
    assert result["checks"]["tables"] >= 1
    assert result["checks"]["paragraphs"] > 10
    # 事实保留：document.xml 文本层含命令与数字原文（zip 经压缩，须先解包查）。
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        document = zf.read("word/document.xml").decode("utf-8")
    assert "pip install fakepkg" in document
    assert "1.89" in document
    assert "deadbeef1234" in document


def test_docx_rejects_garbage():
    assert doc_module.validate_docx_bytes(b"not a zip").get("ok") is False
    assert doc_module.validate_docx_bytes(b"").get("ok") is False


def test_latex_structure_and_escape():
    tex = doc_module.markdown_to_latex(SAMPLE_MD, title="自主实验报告")
    assert "% !TEX program = xelatex" in tex.split("\n", 1)[0]
    assert "\\documentclass[UTF8]{ctexart}" in tex
    assert "\\section{" in tex and "\\end{document}" in tex
    assert "\\begin{lstlisting}" in tex and "\\begin{tabular}" in tex
    result = doc_module.verify_latex(tex)
    assert result["ok"] is True, result
    # 事实保留：转义后命令仍可读（下划线转义不断词）。
    assert "requirements" in tex and "fakepkg" in tex


def test_latex_escape_units():
    assert doc_module.latex_escape("a_b%c&d") == "a\\_b\\%c\\&d"
    assert doc_module.latex_escape("中文 ok") == "中文 ok"


def test_verify_latex_still_catches_real_problems():
    # 校验器不是摆设：裸特殊字符与失衡括号必须判失败。
    assert doc_module.verify_latex("plain a_b text")["ok"] is False
    assert doc_module.verify_latex("\\begin{document}\n{unclosed\n\\end{document}")["ok"] is False


def test_build_formats_combines_report_and_recipe():
    built = doc_module.build_formats("# 报告\n\n正文", "pip install x", "自主实验报告 · abc")
    assert built["derived_from"] == "experiment-report/1"
    assert built["checks"]["docx"]["ok"] is True
    assert built["checks"]["tex"]["ok"] is True
    compile_info = built["checks"]["compile"]
    # 本机无工具链时如实缺席（不断言编译成功）；有则必须给出明确结论。
    assert compile_info["code"] in ("TOOLCHAIN_MISSING", "COMPILED",
                                    "COMPILE_FAILED", "COMPILE_TIMEOUT",
                                    "COMPILE_UNAVAILABLE")
    assert len(built["docx_bytes"]) > 2000
    assert "附录" in built["tex"]
