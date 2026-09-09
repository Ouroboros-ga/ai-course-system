"""SR6 正式输出：冻结报告 Markdown → .docx / .tex（确定性转换，不经 LLM）。

- 输入是 T6 已冻结内容（`experiment-report/1` 的报告/配方 Markdown，
  服务端拼装文本，非模型自由输出）；本模块只做格式映射，不改写事实、
  不补数据、不编造缺失章节。
- Word：标准库 zipfile＋XML 手工组装最小合法 OOXML（段落/标题/列表/
  表格/代码块/引用），零新依赖；输出为真正可编辑 .docx 二进制（经
  validate Docx 结构自检；Word/WPS 可打开编辑）。
- LaTeX：ctexart＋xelatex 模板（中文正文可编译设计），代码块进
  lstlisting，表格进 tabular；verify 做结构＋转义＋括号三重自检；
  工具链存在时才尝试编译（禁 shell-escape），缺工具链如实
  TOOLCHAIN_MISSING，不伪装编译成功。
- 支持的 Markdown 子集即 T6 报告实际使用的形状（h1-h3/段落/粗斜体/
  行内代码/代码围栏/无序有序列表/管道表格/分隔线/引用）；子集外
  语法原样落为正文，不丢弃。
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

FORMATS_CONTENT_VERSION = "experiment-report/1"
DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document")

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W}


def _esc_xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# Markdown 子集解析（块＋行内）
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_UL_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`\n]+)`")


def _split_cells(line: str) -> list[str]:
    cleaned = line.strip()
    if cleaned.startswith("|"):
        cleaned = cleaned[1:]
    if cleaned.endswith("|"):
        cleaned = cleaned[:-1]
    return [cell.strip() for cell in cleaned.split("|")]


def parse_markdown_blocks(md: str) -> list[dict[str, Any]]:
    """Markdown 子集 → 块序列（heading/para/code/ul/ol/table/hr/quote）。

    纯函数；子集外语法降级为 para，不抛异常、不丢行。
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict[str, Any]] = []
    i = 0
    para_buf: list[str] = []

    def _flush_para() -> None:
        if para_buf:
            blocks.append({"kind": "para", "text": " ".join(para_buf).strip()})
            para_buf.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence is not None:
            _flush_para()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 吞掉结束围栏（缺失则自然结束，不抛错）
            blocks.append({"kind": "code", "text": "\n".join(code_lines)})
            continue
        heading = _HEADING_RE.match(line)
        if heading is not None:
            _flush_para()
            blocks.append({"kind": f"h{len(heading.group(1))}",
                           "text": heading.group(2).strip()})
            i += 1
            continue
        if _HR_RE.match(line):
            _flush_para()
            blocks.append({"kind": "hr"})
            i += 1
            continue
        quote = _QUOTE_RE.match(line)
        if quote is not None:
            _flush_para()
            quote_buf = [quote.group(1)]
            i += 1
            while i < len(lines):
                more = _QUOTE_RE.match(lines[i])
                if more is None:
                    break
                quote_buf.append(more.group(1))
                i += 1
            blocks.append({"kind": "quote",
                           "text": " ".join(quote_buf).strip()})
            continue
        ul = _UL_RE.match(line)
        if ul is not None:
            _flush_para()
            items = [ul.group(1).strip()]
            i += 1
            while i < len(lines):
                more = _UL_RE.match(lines[i])
                if more is None:
                    break
                items.append(more.group(1).strip())
                i += 1
            blocks.append({"kind": "ul", "items": items})
            continue
        ol = _OL_RE.match(line)
        if ol is not None:
            _flush_para()
            items = [ol.group(1).strip()]
            i += 1
            while i < len(lines):
                more = _OL_RE.match(lines[i])
                if more is None:
                    break
                items.append(more.group(1).strip())
                i += 1
            blocks.append({"kind": "ol", "items": items})
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            _flush_para()
            header = _split_cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_cells(lines[i]))
                i += 1
            width = max([len(header)] + [len(r) for r in rows] + [1])
            blocks.append({
                "kind": "table", "width": width,
                "header": (header + [""] * width)[:width],
                "rows": [(r + [""] * width)[:width] for r in rows],
            })
            continue
        if not line.strip():
            _flush_para()
            i += 1
            continue
        para_buf.append(line.strip())
        i += 1
    _flush_para()
    return blocks


def _restore_segments(chunk: str, code_marks: list[str]) -> list[tuple[str, str]]:
    """把 \x00N\x00 占位符还原为 code 段，其余为 plain（合并相邻同类）。"""
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    idx_buf: list[str] = []
    in_code = False

    def _flush_buf() -> None:
        if buf:
            text = "".join(buf)
            if segments and segments[-1][0] == "plain":
                segments[-1] = ("plain", segments[-1][1] + text)
            else:
                segments.append(("plain", text))
            buf.clear()

    for ch in chunk:
        if ch == "\x00" and not in_code:
            _flush_buf()
            in_code = True
            idx_buf = []
        elif ch == "\x00" and in_code:
            try:
                segments.append(("code", code_marks[int("".join(idx_buf))]))
            except (ValueError, IndexError):
                pass
            in_code = False
        elif in_code:
            idx_buf.append(ch)
        else:
            buf.append(ch)
    _flush_buf()
    return segments


def inline_runs(text: str) -> list[tuple[str, str]]:
    """行内 → [(style, segment)]；style ∈ plain/bold/italic/code（公开入口）。"""
    code_marks: list[str] = []

    def _code_hold(match: re.Match[str]) -> str:
        code_marks.append(match.group(1))
        return f"\x00{len(code_marks) - 1}\x00"

    masked = _CODE_RE.sub(_code_hold, text or "")
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _BOLD_RE.finditer(masked):
        if match.start() > pos:
            segments.extend(_inline_italic(masked[pos:match.start()], code_marks))
        for style, seg in _restore_segments(match.group(1), code_marks):
            segments.append(("bold" if style == "plain" else style, seg))
        pos = match.end()
    if pos < len(masked):
        segments.extend(_inline_italic(masked[pos:], code_marks))
    return [(style, seg) for style, seg in segments if seg]


def _inline_italic(chunk: str, code_marks: list[str]) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    pos = 0
    for match in _ITALIC_RE.finditer(chunk):
        if match.start() > pos:
            segments.extend(_restore_segments(chunk[pos:match.start()], code_marks))
        for style, seg in _restore_segments(match.group(1), code_marks):
            segments.append(("italic" if style == "plain" else style, seg))
        pos = match.end()
    if pos < len(chunk):
        segments.extend(_restore_segments(chunk[pos:], code_marks))
    return segments


# ---------------------------------------------------------------------------
# .docx 组装（标准库）
# ---------------------------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="100"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:style><w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360"/><w:spacing w:before="80" w:after="80"/></w:pPr><w:rPr><w:i/><w:color w:val="595959"/></w:rPr></w:style></w:styles>"""

_NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="\\u2022"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>"""

_CORE_PROPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>CodeNexus</dc:creator></cp:coreProperties>"""

_APP_PROPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>CodeNexus SR6</Application></Properties>"""


def _w_runs(segments: list[tuple[str, str]], mono: bool = False) -> str:
    out: list[str] = []
    for style, seg in segments:
        props: list[str] = []
        if style == "bold":
            props.append("<w:b/>")
        if style == "italic":
            props.append("<w:i/>")
        if style == "code" or mono:
            props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" '
                         'w:eastAsia="Consolas" w:cs="Consolas"/>')
            props.append("<w:sz w:val=\"20\"/><w:szCs w:val=\"20\"/>")
            props.append('<w:shd w:fill="F2F2F2" w:val="clear"/>')
        # 保留行首尾空格（Word 默认吞掉）：xml:space。
        out.append(f"<w:r><w:rPr>{''.join(props)}</w:rPr>"
                   f"<w:t xml:space=\"preserve\">{_esc_xml(seg)}</w:t></w:r>")
    return "".join(out)


def _w_para(runs_xml: str, style: str | None = None,
            num_id: str | None = None) -> str:
    ppr = ""
    if style is not None or num_id is not None:
        inner = ""
        if style is not None:
            inner += f"<w:pStyle w:val=\"{style}\"/>"
        if num_id is not None:
            inner += (f"<w:numPr><w:ilvl w:val=\"0\"/>"
                      f"<w:numId w:val=\"{num_id}\"/></w:numPr>")
        ppr = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{ppr}{runs_xml}</w:p>"


def _w_table(header: list[str], rows: list[list[str]]) -> str:
    def _row(cells: list[str], bold: bool) -> str:
        tcs = "".join(
            f"<w:tc><w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
            f"{_w_para(_w_runs([(('bold' if bold else 'plain'), c)]))}</w:tc>"
            for c in cells)
        return f"<w:tr>{tcs}</w:tr>"

    borders = "".join(
        f"<w:{edge} w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"BFBFBF\"/>"
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"))
    return (f"<w:tbl><w:tblPr><w:tblW w:w=\"0\" w:type=\"auto\"/>"
            f"<w:tblBorders>{borders}</w:tblBorders></w:tblPr>"
            f"<w:tblGrid>{''.join('<w:gridCol w:w=\"2400\"/>' for _ in header)}</w:tblGrid>"
            f"{_row(header, True)}{''.join(_row(r, False) for r in rows)}</w:tbl>")


def _blocks_to_docx_xml(blocks: list[dict[str, Any]]) -> str:
    body: list[str] = []
    for block in blocks:
        kind = block.get("kind")
        if kind in ("h1", "h2", "h3"):
            body.append(_w_para(
                _w_runs(inline_runs(str(block.get("text") or ""))),
                style=f"Heading{kind[1]}"))
        elif kind == "code":
            for line in str(block.get("text") or "").split("\n"):
                body.append(_w_para(
                    _w_runs([("plain", line or " ")], mono=True)))
        elif kind == "ul":
            for item in block.get("items") or []:
                body.append(_w_para(_w_runs(inline_runs(item)),
                                    style="ListParagraph", num_id="1"))
        elif kind == "ol":
            for item in block.get("items") or []:
                body.append(_w_para(_w_runs(inline_runs(item)),
                                    style="ListParagraph", num_id="2"))
        elif kind == "table":
            body.append(_w_table(block.get("header") or [],
                                 block.get("rows") or []))
        elif kind == "quote":
            body.append(_w_para(_w_runs(inline_runs(str(block.get("text") or ""))),
                                style="Quote"))
        elif kind == "hr":
            body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" '
                        'w:sz="6" w:space="8" w:color="BFBFBF"/></w:pBdr>'
                        "</w:pPr></w:p>")
        else:
            text = str(block.get("text") or "")
            if text:
                body.append(_w_para(_w_runs(inline_runs(text))))
    body.append('<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" '
                'w:left="1800"/></w:sectPr></w:pPr></w:p>')
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
            f"<w:document xmlns:w=\"{_W}\"><w:body>{''.join(body)}</w:body></w:document>")


def markdown_to_docx_bytes(md: str, title: str = "") -> bytes:
    """Markdown 子集 → 合法 .docx 二进制（纯函数，可单测）。"""
    document_xml = _blocks_to_docx_xml(parse_markdown_blocks(md))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("word/_rels/document.rels", _DOC_RELS)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", _STYLES)
        zf.writestr("word/numbering.xml", _NUMBERING)
        zf.writestr("docProps/core.xml",
                    _CORE_PROPS.format(title=_esc_xml((title or "")[:120])))
        zf.writestr("docProps/app.xml", _APP_PROPS)
    return buf.getvalue()


def validate_docx_bytes(data: bytes) -> dict[str, Any]:
    """校验 .docx 结构（zip 完整＋必需部件＋document.xml 可解析）。

    纯函数，不抛异常；返回 {"ok", "checks", "detail"}。
    """
    checks: dict[str, Any] = {}
    if not isinstance(data, bytes) or len(data) < 100:
        return {"ok": False, "checks": checks, "detail": "空或过小，非 docx"}
    try:
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, "r") as zf:
            bad = zf.testzip()
            checks["zip_integrity"] = bad is None
            names = set(zf.namelist())
            required = {"[Content_Types].xml", "_rels/.rels",
                        "word/document.xml", "word/styles.xml",
                        "word/numbering.xml"}
            checks["required_parts"] = required <= names
            try:
                root = ET.fromstring(zf.read("word/document.xml"))
                paras = root.findall(".//w:p", _NS)
                tables = root.findall(".//w:tbl", _NS)
                checks["paragraphs"] = len(paras)
                checks["tables"] = len(tables)
                checks["document_parse"] = True
            except ET.ParseError:
                checks["document_parse"] = False
    except zipfile.BadZipFile:
        return {"ok": False, "checks": checks, "detail": "zip 损坏"}
    ok = bool(checks.get("zip_integrity") and checks.get("required_parts")
              and checks.get("document_parse")
              and int(checks.get("paragraphs", 0)) > 0)
    return {"ok": ok, "checks": checks,
            "detail": "结构自检通过" if ok else "结构自检失败"}


# ---------------------------------------------------------------------------
# .tex 生成与校验
# ---------------------------------------------------------------------------

_TEX_SPECIALS = {"\\": r"\textbackslash{}",
                 "&": r"\&", "%": r"\%", "$": r"\$",
                 "#": r"\#", "_": r"\_", "{": r"\{",
                 "}": r"\}", "~": r"\textasciitilde{}",
                 "^": r"\textasciicircum{}"}


def latex_escape(text: str) -> str:
    """LaTeX 特殊字符转义（CJK 原样保留）。"""
    return "".join(_TEX_SPECIALS.get(ch, ch) for ch in (text or ""))


def _tex_inline(text: str) -> str:
    """行内 → LaTeX（先整体转义，再套粗斜体命令，最后还原代码段）。

    顺序即正确性：转义不碰 `*` 标记与占位符，命令参数因此天然已转义，
    不存在二次转义。
    """
    code_marks: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        code_marks.append(match.group(1))
        return f"\x00{len(code_marks) - 1}\x00"

    masked = _CODE_RE.sub(_hold, text or "")
    escaped = latex_escape(masked)
    escaped = _BOLD_RE.sub(r"\\textbf{\1}", escaped)
    escaped = _ITALIC_RE.sub(r"\\textit{\1}", escaped)

    out: list[str] = []
    buf: list[str] = []
    idx: list[str] = []
    in_code = False

    def _flush() -> None:
        if buf:
            out.append("".join(buf))
            buf.clear()

    for ch in escaped:
        if ch == "\x00" and not in_code:
            _flush()
            in_code = True
            idx = []
        elif ch == "\x00" and in_code:
            try:
                out.append("\\texttt{" + latex_escape(code_marks[int("".join(idx))]) + "}")
            except (ValueError, IndexError):
                pass
            in_code = False
        elif in_code:
            idx.append(ch)
        else:
            buf.append(ch)
    _flush()
    return "".join(out)


def markdown_to_latex(md: str, title: str = "") -> str:
    """Markdown 子集 → 自包含 main.tex（ctexart＋xelatex，可编译设计）。"""
    blocks = parse_markdown_blocks(md)
    body: list[str] = []
    for block in blocks:
        kind = block.get("kind")
        if kind == "h1":
            body.append(f"\\section{{{_tex_inline(str(block.get('text') or ''))}}}")
        elif kind == "h2":
            body.append(f"\\subsection{{{_tex_inline(str(block.get('text') or ''))}}}")
        elif kind == "h3":
            body.append(f"\\subsubsection{{{_tex_inline(str(block.get('text') or ''))}}}")
        elif kind == "code":
            body.append("\\begin{lstlisting}")
            body.append(str(block.get("text") or ""))
            body.append("\\end{lstlisting}")
        elif kind == "ul":
            body.append("\\begin{itemize}")
            body.extend(f"\\item {_tex_inline(i)}" for i in block.get("items") or [])
            body.append("\\end{itemize}")
        elif kind == "ol":
            body.append("\\begin{enumerate}")
            body.extend(f"\\item {_tex_inline(i)}" for i in block.get("items") or [])
            body.append("\\end{enumerate}")
        elif kind == "table":
            header = block.get("header") or []
            rows = block.get("rows") or []
            cols = "l" * max(1, len(header))
            body.append(f"\\begin{{tabular}}{{{cols}}}")
            body.append("\\hline")
            body.append(" & ".join(latex_escape(c) for c in header) + r" \\")
            body.append("\\hline")
            for row in rows:
                body.append(" & ".join(latex_escape(c) for c in row) + r" \\")
            body.append("\\hline")
            body.append("\\end{tabular}")
        elif kind == "quote":
            body.append("\\begin{quote}")
            body.append(_tex_inline(str(block.get("text") or "")))
            body.append("\\end{quote}")
        elif kind == "hr":
            body.append("\\par\\noindent\\rule{\\textwidth}{0.4pt}\\par")
        else:
            text = str(block.get("text") or "")
            if text:
                body.append(_tex_inline(text))
                body.append("")
    return "\n".join([
        "% !TEX program = xelatex",
        "% 由 CodeNexus SR6 确定性生成（experiment-report/1 冻结内容），请用",
        "% TeX Live (xelatex) 编译：xelatex -interaction=nonstopmode main.tex",
        "\\documentclass[UTF8]{ctexart}",
        "\\usepackage{listings,xcolor,hyperref,longtable}",
        "\\lstset{basicstyle=\\ttfamily\\small,breaklines=true,"
        "frame=single,backgroundcolor=\\color{black!5}}",
        f"\\title{{{latex_escape(title or '自主实验报告')}}}",
        "\\author{CodeNexus}",
        "\\date{\\today}",
        "\\begin{document}",
        "\\maketitle",
        *body,
        "\\end{document}",
        "",
    ])


def verify_latex(tex: str) -> dict[str, Any]:
    """校验 .tex 结构＋转义＋括号（纯函数，不調编译器）。

    返回 {"ok", "checks", "detail"}；ok 为三重自检全过。
    """
    checks: dict[str, Any] = {}
    source = tex or ""
    checks["has_documentclass"] = "\\documentclass" in source
    checks["has_begin_end"] = ("\\begin{document}" in source
                               and "\\end{document}" in source)
    checks["has_xelatex_magic"] = "xelatex" in source.split("\n", 4)[0]
    # 去掉 lstlisting 块后再查：裸特殊字符与括号平衡。整行注释（% 开头）
    # 是合法 LaTeX，先剔除，不计入裸字符检查。
    stripped = re.sub(r"\\begin\{lstlisting\}.*?\\end\{lstlisting\}",
                      "", source, flags=re.DOTALL)
    stripped = "\n".join(
        line for line in stripped.split("\n")
        if not re.match(r"^\s*%", line))
    # tabular 的 & 列分隔与 \\ 行结束是合法结构：只在该环境内剔除分隔符，
    # 单元格文本保留，继续接受转义检查（转义失败仍会被揪出）。
    chunks = re.split(r"(\\begin\{tabular\}.*?\\end\{tabular\})",
                      stripped, flags=re.DOTALL)
    for index, chunk in enumerate(chunks):
        if chunk.startswith("\\begin{tabular}"):
            inner = re.sub(r"\\(begin|end)\{tabular\}.*", "", chunk)
            chunks[index] = inner.replace("\\hline", "").replace("&", " ")
    stripped = "".join(chunks)
    stripped_cmds = re.sub(r"\\[a-zA-Z]+", "", stripped)
    stripped_cmds = stripped_cmds.replace("\\\\", "").replace("\\%", "")
    stripped_cmds = re.sub(r"\\[^a-zA-Z]", "", stripped_cmds)
    checks["no_raw_specials"] = not bool(re.search(r"[&%$#_~^]", stripped_cmds))
    depth = 0
    balanced = True
    for ch in stripped_cmds:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                balanced = False
                break
    checks["braces_balanced"] = balanced and depth == 0
    ok = all(checks.values())
    return {"ok": bool(ok), "checks": checks,
            "detail": "结构自检通过" if ok else "结构自检失败"}


def try_compile_latex(tex: str) -> dict[str, Any]:
    """尝试用本机工具链编译（仅当 xelatex/pdflatex 存在；禁 shell-escape）。

    缺工具链 → {"compiled": False, "code": "TOOLCHAIN_MISSING"}（如实缺席，
    不伪装失败）；编译错 → {"compiled": False, "code": "COMPILE_FAILED",
    "log_tail": …}；成功 → {"compiled": True, ...}。
    输入为服务端自拼装文本，非用户任意命令；仍禁 shell 转义与网络。
    """
    engine = shutil.which("xelatex") or shutil.which("pdflatex")
    if engine is None:
        return {"compiled": False, "code": "TOOLCHAIN_MISSING",
                "detail": "本机无 xelatex/pdflatex；.tex 已做结构自检，编译待工具链环境。"}
    try:
        with tempfile.TemporaryDirectory(prefix="sr6-tex-") as tmp:
            with open(f"{tmp}/main.tex", "w", encoding="utf-8") as f:
                f.write(tex or "")
            completed = subprocess.run(
                [engine, "-interaction=nonstopmode", "-halt-on-error",
                 "-no-shell-escape", "main.tex"],
                cwd=tmp, capture_output=True, text=True, timeout=180)
            import os

            pdf_ok = os.path.exists(f"{tmp}/main.pdf")
            log = (completed.stdout or "")[-2000:]
            if completed.returncode == 0 and pdf_ok:
                return {"compiled": True, "code": "COMPILED",
                        "detail": "工具链编译成功（main.pdf 已产出）。"}
            return {"compiled": False, "code": "COMPILE_FAILED",
                    "detail": "编译器返回非零或缺 main.pdf。",
                    "log_tail": log}
    except subprocess.TimeoutExpired:
        return {"compiled": False, "code": "COMPILE_TIMEOUT",
                "detail": "编译超时（180s），未产出结论。"}
    except Exception as error:  # noqa: BLE001 - 编译环境异常如实返回
        return {"compiled": False, "code": "COMPILE_UNAVAILABLE",
                "detail": f"编译不可用（{type(error).__name__}）。"}


def build_formats(report_md: str, recipe_md: str,
                  title_base: str) -> dict[str, Any]:
    """由冻结报告＋配方 Markdown 构建正式格式产物（纯函数，可单测）。

    返回 {"docx_bytes", "tex", "checks": {"docx": …, "tex": …, "compile": …}}；
    Word 为单文档（报告＋分页＋配方附录），LaTeX 同理 main.tex。
    """
    combined = (
        f"{report_md.rstrip()}\n\n---\n\n"
        f"# 附录：实验配方\n\n{recipe_md.strip()}\n")
    title = (title_base or "自主实验报告").strip()[:100]
    docx_bytes = markdown_to_docx_bytes(combined, title=title)
    tex = markdown_to_latex(combined, title=title)
    return {
        "docx_bytes": docx_bytes,
        "tex": tex,
        "derived_from": FORMATS_CONTENT_VERSION,
        "checks": {
            "docx": validate_docx_bytes(docx_bytes),
            "tex": verify_latex(tex),
            "compile": try_compile_latex(tex),
        },
    }
