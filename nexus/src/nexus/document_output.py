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
    # F6：原生数学区（$…$）是合法 LaTeX，内容不受裸字符检查约束；
    # 先剥离（数学存在性由调用方 math_spans 记录），只查正文转义。
    stripped = re.sub(r"\$[^$\n]+\$", "", stripped)
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


# ---------------------------------------------------------------------------
# F6：一份冻结内容，多格式正式输出（Markdown / Word / LaTeX / PDF）
# ---------------------------------------------------------------------------
# - freeze_document：同一快照（hash＋引用/图表/数值清单）供三格式消费，
#   不让模型分别重写三遍；转换不改写事实。
# - 引擎：pandoc 优先（严格白名单参数，无 shell/filter/宏/外网），缺席或
#   失败时回退标准库实现；每格式如实记录 engine（绝不谎称 pandoc）。
# - 数学：pandoc 路径为原生 OMML（math_native=True）；标准库路径为可编辑
#   文本 run（math_editable=True、可编辑、非截图），math_native=False。
# - PDF：仅当本机工具链真实编译出 main.pdf 才交付字节；缺工具链如实
#   TOOLCHAIN_MISSING（partial，不伪装预览）。

DOCUMENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "experiment_report": {
        "version": "tpl-experiment/1",
        "reference_docx": "builtin-minimal/1",
        "tex_template": "ctexart-xelatex/1",
        "scope": "实验报告：中英混排、表格、公式、图题、引用",
    },
    "research_review": {
        "version": "tpl-review/1",
        "reference_docx": "builtin-minimal/1",
        "tex_template": "ctexart-xelatex/1",
        "scope": "研究综述：中英混排、表格、公式、图题、引用",
    },
    "tech_doc": {
        "version": "tpl-techdoc/1",
        "reference_docx": "builtin-minimal/1",
        "tex_template": "ctexart-xelatex/1",
        "scope": "技术说明：中英混排、表格、公式、图题、引用",
    },
}

SUPPORTED_FORMATS = ("markdown", "word", "latex", "pdf")

_MATH_RE = re.compile(r"\$(.+?)\$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_CITE_RE = re.compile(r"\[@([A-Za-z0-9_\-:]+)\]")
_FENCE_COUNT_RE = re.compile(r"^```", re.MULTILINE)


class DocumentRenderError(Exception):
    """文档渲染域失败：携带机器可读 code（fail-closed 语义）。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def normalize_markdown(md: str) -> str:
    """冻结归一化（换行统一＋行尾空格清理＋末尾单空行；纯函数）。"""
    text = (md or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


def freeze_document(*, markdown: str, title: str = "",
                    template: str = "tech_doc",
                    source: dict[str, Any] | None = None) -> dict[str, Any]:
    """冻结一份文档内容（纯函数，可单测）。

    返回 FrozenDocument{version/document_id/title/template/template_version/
    content_hash/markdown/inventory}；三种格式只读此快照。
    """
    import hashlib as _hashlib

    if template not in DOCUMENT_TEMPLATES:
        raise DocumentRenderError("TEMPLATE_UNKNOWN", f"未知模板：{template}")
    normalized = normalize_markdown(markdown)
    if not normalized.strip():
        raise DocumentRenderError("DOCUMENT_EMPTY", "文档内容为空，不得冻结。")
    if len(normalized.encode("utf-8")) > 512 * 1024:
        raise DocumentRenderError("DOCUMENT_TOO_LARGE", "文档超 512KB 上限。")
    blocks = parse_markdown_blocks(normalized)
    math_spans = _MATH_RE.findall(normalized)[:50]
    figures = [{"alt": alt[:120], "src": src[:500]}
               for alt, src in _IMAGE_RE.findall(normalized)][:50]
    links = [{"text": text[:120], "href": href[:500]}
             for text, href in _LINK_RE.findall(normalized)
             if not href.startswith("!")][:100]
    citations = sorted(set(_CITE_RE.findall(normalized)))[:100]
    tables = sum(1 for b in blocks if b.get("kind") == "table")
    code_blocks = sum(1 for b in blocks if b.get("kind") == "code")
    content_hash = _hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "version": "frozen-document/1",
        "document_id": f"doc-{content_hash[:12]}",
        "title": (title or "").strip()[:120],
        "template": template,
        "template_version": DOCUMENT_TEMPLATES[template]["version"],
        "content_hash": content_hash,
        "markdown": normalized,
        "inventory": {
            "tables": tables,
            "code_blocks": code_blocks,
            "math_spans": len(math_spans),
            "math_sample": [m[:120] for m in math_spans[:5]],
            "figures": figures,
            "links": links,
            "citations": citations,
            "blocks": len(blocks),
        },
        "source": dict(source or {}),
    }


def select_engine() -> str:
    """渲染引擎选择（诚实记录用；pandoc 存在即优先，否则标准库）。"""
    if shutil.which("pandoc"):
        return "pandoc"
    return "stdlib/1"


def _mask_math_for_stdlib(md: str) -> tuple[str, list[str]]:
    """把 $…$ 遮罩为行内代码段（标准库路径：可编辑文本 run，非截图）。

    返回 (masked, spans)；调用方渲染后无需还原（代码 run 即承载体）。
    """
    spans: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"`{match.group(1)}`"

    return _MATH_RE.sub(_hold, md or ""), spans


def _mask_math_for_tex(md: str) -> tuple[str, list[str]]:
    """把 $…$ 遮罩为占位符（tex 路径：躲过整体转义，渲染后还原原生数学）。"""
    spans: list[str] = []

    def _hold(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"ZZMATH{len(spans) - 1}ZZ"

    return _MATH_RE.sub(_hold, md or ""), spans


def markdown_to_docx_bytes_stdlib(md: str, title: str = "") -> tuple[bytes, dict[str, Any]]:
    """标准库 docx 渲染（含数学可编辑承载；返回字节＋数学诊断）。"""
    masked, spans = _mask_math_for_stdlib(md)
    data = markdown_to_docx_bytes(masked, title=title)
    check = validate_docx_bytes(data)
    check["checks"]["math_editable"] = True
    check["checks"]["math_native"] = False
    check["checks"]["math_spans"] = len(spans)
    return data, check


def markdown_to_latex_stdlib(md: str, title: str = "") -> tuple[str, dict[str, Any]]:
    """标准库 tex 渲染（数学还原为原生 $…$；返回文本＋数学诊断）。"""
    masked, spans = _mask_math_for_tex(md)
    tex = markdown_to_latex(masked, title=title)
    for index, original in enumerate(spans):
        tex = tex.replace(f"ZZMATH{index}ZZ", original)
    check = verify_latex(tex)
    check["checks"]["math_editable"] = True
    check["checks"]["math_native"] = False
    check["checks"]["math_spans"] = len(spans)
    return tex, check


def _pandoc_convert(md: str, title: str, to: str,
                    template: str) -> tuple[bytes, bool]:
    """pandoc 严格调用（无 shell、无 filter、无 pdf-engine；返回字节＋是否原生数学）。

    失败抛 DocumentRenderError（PANDOC_FAILED / PANDOC_TIMEOUT），调用方
    据此回退标准库并如实记录，不得谎称 pandoc。
    """
    import shlex as _shlex

    if not shutil.which("pandoc"):
        raise DocumentRenderError("PANDOC_MISSING", "本机无 pandoc。")
    safe_title = (title or "")[:120]
    if to == "docx":
        args = ["pandoc", "--from", "markdown", "--to", "docx",
                "--standalone", "--metadata", f"title={safe_title}"]
        math_native = True  # docx writer math 为 OMML
    elif to == "latex":
        args = ["pandoc", "--from", "markdown", "--to", "latex",
                "--standalone", "--listings",
                "--metadata", f"title={safe_title}"]
        math_native = True
    else:  # pragma: no cover - 调用方限定 to 取值
        raise DocumentRenderError("FORMAT_UNKNOWN", f"未知 pandoc 目标：{to}")
    _ = (_shlex, template)  # 模板只用内置版本标识，不拼路径（防路径逃逸）
    try:
        completed = subprocess.run(
            args, input=(md or "").encode("utf-8"), capture_output=True,
            timeout=60)
    except subprocess.TimeoutExpired as error:
        raise DocumentRenderError("PANDOC_TIMEOUT", "pandoc 渲染超时（60s）。") from error
    except Exception as error:  # noqa: BLE001
        raise DocumentRenderError(
            "PANDOC_FAILED",
            f"pandoc 调用失败（{type(error).__name__}）。") from error
    if completed.returncode != 0:
        raise DocumentRenderError(
            "PANDOC_FAILED",
            f"pandoc 返回非零（{(completed.stderr or b'')[:200]!r}）。")
    if not completed.stdout:
        raise DocumentRenderError("PANDOC_FAILED", "pandoc 输出为空。")
    return bytes(completed.stdout), math_native


def render_format(*, frozen: dict[str, Any], fmt: str) -> dict[str, Any]:
    """渲染单个格式（纯函数＋受控子进程；返回 per-format 结果字典）。

    返回 {"format","status","engine","engine_fallback","artifact_type",
    "bytes"|"text","checks","detail"}；status ∈ succeeded/failed。
    """
    if fmt not in SUPPORTED_FORMATS:
        raise DocumentRenderError("FORMAT_UNKNOWN", f"不支持的格式：{fmt}")
    title = str(frozen.get("title") or "")
    template = str(frozen.get("template") or "tech_doc")
    markdown = str(frozen.get("markdown") or "")
    if fmt == "markdown":
        return {"format": "markdown", "status": "succeeded",
                "engine": "none", "engine_fallback": "",
                "artifact_type": "markdown", "text": markdown,
                "checks": {"ok": True}, "detail": "冻结原文直出"}
    engine = ""
    fallback = ""
    math_editable = True
    math_native = False
    try:
        if select_engine() == "pandoc" and fmt in ("word", "latex"):
            try:
                raw, math_native = _pandoc_convert(
                    markdown, title, "docx" if fmt == "word" else "latex",
                    template)
                engine = "pandoc"
            except DocumentRenderError as error:
                fallback = error.code
                raise
            if fmt == "word":
                check = validate_docx_bytes(raw)
                check["checks"]["math_editable"] = True
                check["checks"]["math_native"] = bool(math_native)
                if not check.get("ok"):
                    return {"format": "word", "status": "failed",
                            "engine": engine, "engine_fallback": fallback,
                            "artifact_type": "word", "bytes": b"",
                            "checks": check, "detail": "pandoc 产物结构自检失败"}
                return {"format": "word", "status": "succeeded",
                        "engine": engine, "engine_fallback": fallback,
                        "artifact_type": "word", "bytes": raw,
                        "checks": check, "detail": "pandoc 原生转换（含 OMML 数学）"}
            check = verify_latex(raw.decode("utf-8", errors="replace"))
            check["checks"]["math_editable"] = True
            check["checks"]["math_native"] = bool(math_native)
            if not check.get("ok"):
                return {"format": "latex", "status": "failed",
                        "engine": engine, "engine_fallback": fallback,
                        "artifact_type": "latex", "text": "",
                        "checks": check, "detail": "pandoc 产物结构自检失败"}
            return {"format": "latex", "status": "succeeded",
                    "engine": engine, "engine_fallback": fallback,
                    "artifact_type": "latex",
                    "text": raw.decode("utf-8", errors="replace"),
                    "checks": check, "detail": "pandoc 原生转换"}
    except DocumentRenderError:
        pass  # 回退标准库（fallback 已记录）
    if fmt == "word":
        raw, check = markdown_to_docx_bytes_stdlib(markdown, title=title)
        engine = "stdlib/1"
        if not check.get("ok"):
            return {"format": "word", "status": "failed", "engine": engine,
                    "engine_fallback": fallback, "artifact_type": "word",
                    "bytes": b"", "checks": check,
                    "detail": "标准库产物结构自检失败"}
        return {"format": "word", "status": "succeeded", "engine": engine,
                "engine_fallback": fallback, "artifact_type": "word",
                "bytes": raw, "checks": check,
                "detail": "标准库渲染（数学为可编辑文本 run，非 OMML）"
                          + (f"；{fallback} 后回退" if fallback else "")}
    if fmt == "latex":
        tex, check = markdown_to_latex_stdlib(markdown, title=title)
        engine = "stdlib/1"
        if not check.get("ok"):
            return {"format": "latex", "status": "failed", "engine": engine,
                    "engine_fallback": fallback, "artifact_type": "latex",
                    "text": "", "checks": check,
                    "detail": "标准库产物结构自检失败"}
        return {"format": "latex", "status": "succeeded", "engine": engine,
                "engine_fallback": fallback, "artifact_type": "latex",
                "text": tex, "checks": check,
                "detail": "标准库渲染（数学为原生 $…$）"
                          + (f"；{fallback} 后回退" if fallback else "")}
    # pdf：仅当本机工具链真实编译出 main.pdf 才交付字节。
    _ = (math_editable, math_native)
    compiled = compile_latex_pdf(markdown_to_latex_stdlib(markdown, title=title)[0])
    if not compiled.get("compiled"):
        return {"format": "pdf", "status": "failed", "engine": "toolchain",
                "engine_fallback": "", "artifact_type": "pdf", "bytes": b"",
                "checks": {"ok": False, "code": compiled.get("code", "")},
                "detail": str(compiled.get("detail") or "")}
    return {"format": "pdf", "status": "succeeded", "engine": "toolchain",
            "engine_fallback": "", "artifact_type": "pdf",
            "bytes": compiled.get("pdf_bytes") or b"",
            "checks": {"ok": True, "code": "COMPILED"},
            "detail": "工具链编译成功（main.pdf 真实字节）"}


def compile_latex_pdf(tex: str) -> dict[str, Any]:
    """编译 tex 并带回 PDF 字节（缺工具链如实 TOOLCHAIN_MISSING）。

    与 try_compile_latex 不同：成功时返回 pdf_bytes（上限 8MB，超限即
    COMPILE_TOO_LARGE）；临时目录内 PDF 保留到读取后由系统回收——返回
    前已读入内存，不存在“删了还称已交付”。
    """
    import os as _os

    latexmk = shutil.which("latexmk")
    engine = shutil.which("xelatex") or shutil.which("pdflatex")
    if latexmk is not None and engine is not None:
        # latexmk 自动处理引用/目录的多轮编译；-no-shell-escape 透传。
        cmd = [latexmk, "-xelatex" if "xelatex" in (engine or "") else "-pdf",
               "-interaction=nonstopmode", "-halt-on-error",
               "-no-shell-escape", "main.tex"]
        engine_name = f"latexmk+{engine.split('/')[-1]}"
    elif engine is None:
        return {"compiled": False, "code": "TOOLCHAIN_MISSING",
                "detail": "本机无 xelatex/pdflatex；PDF 未生成（partial 保留其余格式）。"}
    else:
        cmd = [engine, "-interaction=nonstopmode", "-halt-on-error",
               "-no-shell-escape", "main.tex"]
        engine_name = engine.split("/")[-1]
    try:
        with tempfile.TemporaryDirectory(prefix="f6-tex-") as tmp:
            with open(f"{tmp}/main.tex", "w", encoding="utf-8") as handle:
                handle.write(tex or "")
            completed = subprocess.run(
                cmd, cwd=tmp, capture_output=True, text=True, timeout=180)
            pdf_path = f"{tmp}/main.pdf"
            if completed.returncode == 0 and _os.path.exists(pdf_path):
                with open(pdf_path, "rb") as handle:
                    pdf_bytes = handle.read()
                if len(pdf_bytes) > 8 * 1024 * 1024:
                    return {"compiled": False, "code": "COMPILE_TOO_LARGE",
                            "detail": "PDF 超 8MB 上限，未交付。"}
                return {"compiled": True, "code": "COMPILED",
                        "detail": f"工具链编译成功（{engine_name}，main.pdf 真实字节）。",
                        "pdf_bytes": pdf_bytes}
            return {"compiled": False, "code": "COMPILE_FAILED",
                    "detail": f"编译器（{engine_name}）返回非零或缺 main.pdf。",
                    "log_tail": (completed.stdout or "")[-2000:]}
    except subprocess.TimeoutExpired:
        return {"compiled": False, "code": "COMPILE_TIMEOUT",
                "detail": "编译超时（180s），未产出结论。"}
    except Exception as error:  # noqa: BLE001
        return {"compiled": False, "code": "COMPILE_UNAVAILABLE",
                "detail": f"编译不可用（{type(error).__name__}）。"}


def build_document_formats(*, frozen: dict[str, Any],
                           formats: list[str]) -> dict[str, Any]:
    """由冻结快照构建多格式（每格式独立状态；返回 overall＋per-format）。

    overall ∈ succeeded（全成）/ partial（部分成）/ failed（全败）；
    成功格式产物保留，失败格式可单独重试。转换不改写事实（同一快照）。
    """
    wanted: list[str] = []
    for fmt in formats or []:
        cleaned = str(fmt or "").strip().lower()
        if cleaned and cleaned not in wanted:
            wanted.append(cleaned)
    for cleaned in wanted:
        if cleaned not in SUPPORTED_FORMATS:
            raise DocumentRenderError("FORMAT_UNKNOWN", f"不支持的格式：{cleaned}")
    if not wanted:
        raise DocumentRenderError("FORMAT_EMPTY", "未指定任何格式。")
    per_format: dict[str, Any] = {}
    for fmt in wanted:
        try:
            per_format[fmt] = render_format(frozen=frozen, fmt=fmt)
        except DocumentRenderError as error:
            per_format[fmt] = {"format": fmt, "status": "failed",
                               "engine": "none", "engine_fallback": "",
                               "artifact_type": fmt, "bytes": b"", "text": "",
                               "checks": {"ok": False},
                               "detail": f"{error.code}：{error}"}
    succeeded = [k for k, v in per_format.items() if v.get("status") == "succeeded"]
    if len(succeeded) == len(wanted):
        overall = "succeeded"
    elif succeeded:
        overall = "partial"
    else:
        overall = "failed"
    return {"status": overall, "formats": per_format,
            "document_id": str(frozen.get("document_id") or ""),
            "content_hash": str(frozen.get("content_hash") or ""),
            "template": str(frozen.get("template") or "")}
