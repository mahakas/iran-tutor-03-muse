"""Parsers for structured textbook uploads: Markdown (.md), JSON (.json), and HTML (.html)."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any, Literal

DocumentFormat = Literal["pdf", "markdown", "json", "html"]

SUPPORTED_EXTENSIONS: dict[str, DocumentFormat] = {
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
}

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PAGE_MARKER_RE = re.compile(
    r"(?:<!--\s*(?:page|صفحه)\s*:?\s*([^>]*?)-->|\f)",
    re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
_CHAPTER_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,3}\s+(?:فصل\s*([۰-۹٠-٩\d]+)\s*[:：\-ـ]?\s*)?(.+?)\s*$",
    re.MULTILINE,
)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HTML_PAGE_SPLIT_RE = re.compile(
    r"(?:<!--\s*(?:page|صفحه)\s*:?\s*([۰-۹٠-٩\d]+)\s*-->|<hr[^>]*class=[\"'][^\"']*page-break[^\"']*[\"'][^>]*>|<div[^>]*style=[\"'][^\"']*page-break-(?:before|after)\s*:\s*always[^\"']*[\"'][^>]*>(?:</div>)?)",
    re.IGNORECASE,
)


@dataclass
class ParsedPage:
    page_index: int
    printed_page_number: int | None = None
    chapter_number: int | None = None
    chapter_title: str | None = None
    markdown_content: str = ""
    visual_elements: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def detect_document_format(filename: str | None, content_type: str | None = None) -> DocumentFormat:
    """Resolve upload format from file extension or MIME content type."""
    if filename:
        suffix = Path(filename.strip()).suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS:
            return SUPPORTED_EXTENSIONS[suffix]
    mime = (content_type or "").split(";")[0].strip().lower()
    mime_map: dict[str, DocumentFormat] = {
        "application/pdf": "pdf",
        "text/markdown": "markdown",
        "text/x-markdown": "markdown",
        "application/json": "json",
        "text/json": "json",
        "text/html": "html",
        "application/xhtml+xml": "html",
    }
    if mime in mime_map:
        return mime_map[mime]
    raise ValueError("فرمت فایل پشتیبانی نمی‌شود. فرمت‌های مجاز: PDF، Markdown (.md)، JSON (.json) و HTML (.html)")


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().translate(_PERSIAN_DIGITS)
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def _unbalanced_dollars(markdown: str) -> str | None:
    unescaped = re.sub(r"\\\$", "", markdown)
    if unescaped.count("$") % 2 != 0:
        return "unbalanced $ delimiters in markdown"
    return None


def _extract_chapter_info(
    markdown: str,
    *,
    default_number: int | None = None,
    default_title: str | None = None,
) -> tuple[int | None, str | None]:
    match = _CHAPTER_HEADING_RE.search(markdown)
    if not match:
        return default_number, default_title
    chap_num = _to_int(match.group(1)) if match.group(1) else default_number
    chap_title = match.group(2).strip() if match.group(2) and match.group(2).strip() else default_title
    return chap_num, chap_title


def _chunk_long_markdown(text: str, max_chars: int = 3800) -> list[str]:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []

    # Prefer splitting right before top-level/second-level headings when available.
    sections = re.split(r"(?m)(?=^#{1,2}\s+)", cleaned)
    chunks: list[str] = []
    current = ""
    for section in sections:
        part = section.strip()
        if not part:
            continue
        if len(part) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            paragraphs = re.split(r"\n{2,}", part)
            buf = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if buf and len(buf) + len(para) + 2 > max_chars:
                    chunks.append(buf.strip())
                    buf = para
                else:
                    buf = f"{buf}\n\n{para}" if buf else para
            if buf:
                chunks.append(buf.strip())
            continue
        if current and len(current) + len(part) + 2 > max_chars:
            chunks.append(current.strip())
            current = part
        else:
            current = f"{current}\n\n{part}" if current else part
    if current:
        chunks.append(current.strip())
    return chunks


def _decode_utf8(raw_bytes: bytes, label: str) -> str:
    if not raw_bytes:
        raise ValueError(f"فایل {label} خالی است.")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"فایل {label} باید با کدگذاری UTF-8 ذخیره شده باشد.") from exc
    if not text.strip():
        raise ValueError(f"فایل {label} خالی است.")
    return text


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, text[match.end() :]


def _md_visuals(markdown: str) -> list[dict[str, str]]:
    visuals: list[dict[str, str]] = []
    for alt, src in _MD_IMAGE_RE.findall(markdown):
        desc = alt.strip() or src.strip()
        if desc:
            visuals.append(
                {
                    "label": alt.strip() or "تصویر",
                    "type": "image",
                    "scientific_description": desc,
                }
            )
    return visuals


def _parse_page_marker(raw_marker: str | None) -> tuple[int | None, int | None]:
    if not raw_marker:
        return None, None
    text = raw_marker.strip()
    simple = _to_int(text)
    if simple is not None:
        return simple, None
    printed_match = re.search(r"printed\s*=\s*([۰-۹٠-٩\d]+)", text, re.IGNORECASE)
    chapter_match = re.search(r"chapter\s*=\s*([۰-۹٠-٩\d]+)", text, re.IGNORECASE)
    printed_val = _to_int(printed_match.group(1)) if printed_match else None
    chapter_val = _to_int(chapter_match.group(1)) if chapter_match else None
    return printed_val, chapter_val


def parse_markdown_document(raw_bytes: bytes) -> list[ParsedPage]:
    """Parse a Markdown textbook file into one or more normalized `ParsedPage` entries."""
    raw_text = _decode_utf8(raw_bytes, "Markdown")
    meta, body = _parse_frontmatter(raw_text)
    body = body.strip()
    if not body:
        raise ValueError("فایل Markdown محتوای متنی ندارد.")

    carry_num = _to_int(meta.get("chapter_number") or meta.get("chapter"))
    carry_title = meta.get("chapter_title") or meta.get("title") or None
    base_printed = _to_int(meta.get("printed_page_number") or meta.get("page"))

    raw_segments: list[tuple[int | None, int | None, str]] = []
    if _PAGE_MARKER_RE.search(body):
        # Split while capturing optional explicit page numbers / metadata from markers.
        tokens = _PAGE_MARKER_RE.split(body)
        # tokens alternates: [text0, group1_or_None, text1, group2_or_None, ...]
        pending_printed: int | None = base_printed
        pending_chapter: int | None = carry_num
        for i in range(0, len(tokens), 2):
            seg = tokens[i].strip()
            if seg:
                raw_segments.append((pending_printed, pending_chapter, seg))
            if i + 1 < len(tokens):
                marker_printed, marker_chapter = _parse_page_marker(tokens[i + 1])
                pending_printed = marker_printed
                if marker_chapter is not None:
                    pending_chapter = marker_chapter
    else:
        chunks = _chunk_long_markdown(body)
        for idx, chunk in enumerate(chunks):
            printed = (base_printed + idx) if base_printed is not None else None
            raw_segments.append((printed, carry_num, chunk))

    if not raw_segments:
        raise ValueError("هیچ بخش متنی قابل‌استخراجی در فایل Markdown یافت نشد.")

    pages: list[ParsedPage] = []
    for idx, (printed_num, marker_chap, md_text) in enumerate(raw_segments, start=1):
        chap_num, chap_title = _extract_chapter_info(
            md_text,
            default_number=marker_chap if marker_chap is not None else carry_num,
            default_title=carry_title,
        )
        carry_num = chap_num
        carry_title = chap_title
        warnings: list[str] = []
        dollar_warn = _unbalanced_dollars(md_text)
        if dollar_warn:
            warnings.append(dollar_warn)
        pages.append(
            ParsedPage(
                page_index=idx,
                printed_page_number=printed_num,
                chapter_number=chap_num,
                chapter_title=chap_title,
                markdown_content=md_text,
                visual_elements=_md_visuals(md_text),
                warnings=warnings,
            )
        )
    return pages


def _normalize_visuals(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            desc = str(item.get("scientific_description") or item.get("description") or "").strip()
            label = str(item.get("label") or "شکل").strip()
            kind = str(item.get("type") or "figure").strip()
            if desc or label:
                result.append(
                    {
                        "label": label,
                        "type": kind,
                        "scientific_description": desc or label,
                    }
                )
        elif isinstance(item, str) and item.strip():
            result.append(
                {"label": "شکل", "type": "figure", "scientific_description": item.strip()}
            )
    return result


def _extract_json_item_text(item: dict[str, Any]) -> str:
    for key in ("markdown_content", "markdown", "content", "text", "body"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for list_key in ("sections", "paragraphs", "blocks"):
        seq = item.get(list_key)
        if isinstance(seq, list):
            parts: list[str] = []
            for entry in seq:
                if isinstance(entry, str) and entry.strip():
                    parts.append(entry.strip())
                elif isinstance(entry, dict):
                    heading = str(entry.get("title") or entry.get("heading") or "").strip()
                    body = str(
                        entry.get("markdown_content")
                        or entry.get("markdown")
                        or entry.get("content")
                        or entry.get("text")
                        or ""
                    ).strip()
                    if heading and body:
                        parts.append(f"## {heading}\n\n{body}")
                    elif body:
                        parts.append(body)
                    elif heading:
                        parts.append(f"## {heading}")
            if parts:
                return "\n\n".join(parts)
    return ""


def _dict_to_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, val in data.items():
        if val is None or val == "" or val == [] or val == {}:
            continue
        if isinstance(val, (str, int, float, bool)):
            lines.append(f"## {key}\n\n{val}")
        elif isinstance(val, list):
            rendered = "\n".join(
                f"- {json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x}"
                for x in val
            )
            if rendered:
                lines.append(f"## {key}\n\n{rendered}")
        elif isinstance(val, dict):
            nested = "\n".join(f"- **{k}**: {v}" for k, v in val.items() if v is not None)
            if nested:
                lines.append(f"## {key}\n\n{nested}")
    return "\n\n".join(lines)


def parse_json_document(raw_bytes: bytes) -> list[ParsedPage]:
    """Parse a JSON textbook file into normalized `ParsedPage` entries."""
    raw_text = _decode_utf8(raw_bytes, "JSON")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"فایل JSON معتبر نیست: {exc.msg}") from exc

    top_chap_num: int | None = None
    top_chap_title: str | None = None
    items: list[Any]

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        top_chap_num = _to_int(data.get("chapter_number") or data.get("chapter"))
        raw_top_title = data.get("chapter_title") or data.get("title")
        top_chap_title = str(raw_top_title).strip() if isinstance(raw_top_title, str) and raw_top_title.strip() else None

        if isinstance(data.get("pages"), list):
            items = data["pages"]
        elif isinstance(data.get("chapters"), list):
            items = data["chapters"]
        elif isinstance(data.get("lessons"), list):
            items = data["lessons"]
        elif _extract_json_item_text(data):
            items = [data]
        else:
            fallback_md = _dict_to_markdown(data)
            items = [{"markdown_content": fallback_md}] if fallback_md else []
    else:
        raise ValueError("ساختار JSON باید آرایه‌ای از صفحات یا یک شیء JSON باشد.")

    pages: list[ParsedPage] = []
    used_indices: set[int] = set()
    carry_num = top_chap_num
    carry_title = top_chap_title

    for seq_idx, item in enumerate(items, start=1):
        if isinstance(item, str):
            md_text = item.strip()
            if not md_text:
                continue
            printed_num = None
            explicit_idx = seq_idx
            chap_num, chap_title = _extract_chapter_info(
                md_text, default_number=carry_num, default_title=carry_title
            )
            visuals = _md_visuals(md_text)
        elif isinstance(item, dict):
            md_text = _extract_json_item_text(item)
            if not md_text:
                continue
            printed_num = _to_int(
                item.get("printed_page_number")
                or item.get("page_number")
                or item.get("printed_page")
                or item.get("page")
            )
            candidate_idx = _to_int(
                item.get("pdf_page_index") or item.get("page_index") or item.get("index")
            )
            explicit_idx = (
                candidate_idx
                if candidate_idx is not None and candidate_idx > 0 and candidate_idx not in used_indices
                else len(pages) + 1
            )
            raw_chap_num = _to_int(item.get("chapter_number") or item.get("chapter"))
            raw_chap_title = (
                item.get("chapter_title")
                or item.get("chapter_name")
                or item.get("title")
                or item.get("heading")
            )
            chap_num, chap_title = _extract_chapter_info(
                md_text,
                default_number=raw_chap_num if raw_chap_num is not None else carry_num,
                default_title=(
                    str(raw_chap_title).strip()
                    if isinstance(raw_chap_title, str) and raw_chap_title.strip()
                    else carry_title
                ),
            )
            if raw_chap_num is not None:
                chap_num = raw_chap_num
            if isinstance(raw_chap_title, str) and raw_chap_title.strip():
                chap_title = raw_chap_title.strip()
            visuals = _normalize_visuals(item.get("visual_elements")) or _md_visuals(md_text)
        else:
            continue

        while explicit_idx in used_indices:
            explicit_idx += 1
        used_indices.add(explicit_idx)
        carry_num = chap_num
        carry_title = chap_title
        warnings: list[str] = []
        dollar_warn = _unbalanced_dollars(md_text)
        if dollar_warn:
            warnings.append(dollar_warn)
        pages.append(
            ParsedPage(
                page_index=explicit_idx,
                printed_page_number=printed_num,
                chapter_number=chap_num,
                chapter_title=chap_title,
                markdown_content=md_text,
                visual_elements=visuals,
                warnings=warnings,
            )
        )

    if not pages:
        raise ValueError("هیچ صفحهٔ دارای محتوای متنی در فایل JSON یافت نشد.")
    return pages


class _HtmlToMarkdownParser(HTMLParser):
    """Lightweight HTML -> Markdown converter preserving headings, lists, tables, and math."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.visuals: list[dict[str, str]] = []
        self.doc_title: str = ""
        self._skip_depth = 0
        self._in_title = False
        self._in_math_script = False
        self._math_display = False
        self._math_buf: list[str] = []
        self._in_pre = False
        self._list_stack: list[tuple[str, int]] = []
        self._in_tr = False
        self._table_rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._cell_buf: list[str] | None = None

    def _emit(self, text: str) -> None:
        if self._cell_buf is not None:
            self._cell_buf.append(text)
        else:
            self.parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if t == "script":
            stype = attr_map.get("type", "").lower()
            if stype.startswith("math/tex"):
                self._in_math_script = True
                self._math_display = "mode=display" in stype
                self._math_buf = []
                return
            self._skip_depth += 1
            return

        if t in {"style", "noscript", "template", "svg"}:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if t == "title":
            self._in_title = True
            return

        if t in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(t[1])
            self._emit(f"\n\n{'#' * level} ")
        elif t in {"p", "div", "section", "article", "header", "main", "blockquote"}:
            self._emit("\n\n> " if t == "blockquote" else "\n\n")
        elif t == "br":
            self._emit("\n")
        elif t == "hr":
            self._emit("\n\n---\n\n")
        elif t == "ul":
            self._list_stack.append(("ul", 0))
            self._emit("\n")
        elif t == "ol":
            self._list_stack.append(("ol", 0))
            self._emit("\n")
        elif t == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1][0] == "ol":
                kind, num = self._list_stack[-1]
                num += 1
                self._list_stack[-1] = (kind, num)
                self._emit(f"\n{indent}{num}. ")
            else:
                self._emit(f"\n{indent}- ")
        elif t in {"strong", "b"}:
            self._emit("**")
        elif t in {"em", "i"}:
            self._emit("*")
        elif t == "pre":
            self._in_pre = True
            self._emit("\n\n```\n")
        elif t == "code" and not self._in_pre:
            self._emit("`")
        elif t == "table":
            self._table_rows = []
        elif t == "tr":
            self._in_tr = True
            self._current_row = []
        elif t in {"th", "td"} and self._in_tr:
            self._cell_buf = []
        elif t == "img":
            alt = attr_map.get("alt", "").strip()
            title = attr_map.get("title", "").strip()
            desc = alt or title
            if desc:
                self.visuals.append(
                    {"label": alt or "تصویر", "type": "image", "scientific_description": desc}
                )
                self._emit(f"\n\n[تصویر: {desc}]\n\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "script" and self._in_math_script:
            expr = "".join(self._math_buf).strip()
            if expr:
                self._emit(f"\n$$\n{expr}\n$$\n" if self._math_display else f"${expr}$")
            self._in_math_script = False
            self._math_buf = []
            return

        if t in {"script", "style", "noscript", "template", "svg"}:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return

        if self._skip_depth > 0:
            return

        if t == "title":
            self._in_title = False
            return

        if t in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section", "article", "blockquote"}:
            self._emit("\n\n")
        elif t in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._emit("\n\n")
        elif t in {"strong", "b"}:
            self._emit("**")
        elif t in {"em", "i"}:
            self._emit("*")
        elif t == "pre":
            self._in_pre = False
            self._emit("\n```\n\n")
        elif t == "code" and not self._in_pre:
            self._emit("`")
        elif t in {"th", "td"} and self._cell_buf is not None:
            cell = " ".join("".join(self._cell_buf).split())
            self._current_row.append(cell)
            self._cell_buf = None
        elif t == "tr" and self._in_tr:
            if any(self._current_row):
                self._table_rows.append(self._current_row)
            self._in_tr = False
            self._current_row = []
        elif t == "table":
            if self._table_rows:
                cols = max(len(r) for r in self._table_rows)
                padded = [r + [""] * (cols - len(r)) for r in self._table_rows]
                lines = ["| " + " | ".join(padded[0]) + " |", "| " + " | ".join(["---"] * cols) + " |"]
                for row in padded[1:]:
                    lines.append("| " + " | ".join(row) + " |")
                self._emit("\n\n" + "\n".join(lines) + "\n\n")
            self._table_rows = []

    def handle_data(self, data: str) -> None:
        if self._in_math_script:
            self._math_buf.append(data)
            return
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.doc_title += data
            return
        if self._in_pre:
            self._emit(data)
        else:
            collapsed = re.sub(r"[ \t\r\n]+", " ", data)
            if collapsed:
                self._emit(collapsed)

    def markdown(self) -> str:
        raw = "".join(self.parts)
        lines = [line.rstrip() for line in raw.splitlines()]
        normalized = "\n".join(lines)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()


def _html_fragment_to_markdown(fragment: str) -> tuple[str, str, list[dict[str, str]]]:
    parser = _HtmlToMarkdownParser()
    parser.feed(fragment)
    parser.close()
    return parser.markdown(), parser.doc_title.strip(), parser.visuals


def parse_html_document(raw_bytes: bytes) -> list[ParsedPage]:
    """Parse an HTML textbook file into normalized `ParsedPage` entries."""
    raw_html = _decode_utf8(raw_bytes, "HTML")

    raw_segments: list[tuple[int | None, str, list[dict[str, str]], str]] = []
    if _HTML_PAGE_SPLIT_RE.search(raw_html):
        tokens = _HTML_PAGE_SPLIT_RE.split(raw_html)
        pending_printed: int | None = None
        fallback_title = ""
        for i in range(0, len(tokens), 2):
            frag = tokens[i].strip()
            if frag:
                md_text, doc_title, visuals = _html_fragment_to_markdown(frag)
                if doc_title and not fallback_title:
                    fallback_title = doc_title
                if md_text:
                    raw_segments.append((pending_printed, md_text, visuals, doc_title or fallback_title))
            if i + 1 < len(tokens):
                pending_printed = _to_int(tokens[i + 1])
    else:
        md_text, doc_title, visuals = _html_fragment_to_markdown(raw_html)
        if md_text:
            chunks = _chunk_long_markdown(md_text)
            for idx, chunk in enumerate(chunks):
                raw_segments.append((None, chunk, visuals if idx == 0 else [], doc_title))

    if not raw_segments:
        raise ValueError("هیچ محتوای متنی قابل‌استخراجی در فایل HTML یافت نشد.")

    carry_num: int | None = None
    carry_title: str | None = None
    pages: list[ParsedPage] = []
    for idx, (printed_num, md_text, visuals, doc_title) in enumerate(raw_segments, start=1):
        chap_num, chap_title = _extract_chapter_info(
            md_text,
            default_number=carry_num,
            default_title=carry_title or (doc_title or None),
        )
        carry_num = chap_num
        carry_title = chap_title
        warnings: list[str] = []
        dollar_warn = _unbalanced_dollars(md_text)
        if dollar_warn:
            warnings.append(dollar_warn)
        pages.append(
            ParsedPage(
                page_index=idx,
                printed_page_number=printed_num,
                chapter_number=chap_num,
                chapter_title=chap_title,
                markdown_content=md_text,
                visual_elements=visuals,
                warnings=warnings,
            )
        )
    return pages


def parse_structured_document(raw_bytes: bytes, *, fmt: Literal["markdown", "json", "html"]) -> list[ParsedPage]:
    """Dispatch structured document parsing for `.md`, `.json`, or `.html` uploads."""
    if fmt == "markdown":
        return parse_markdown_document(raw_bytes)
    if fmt == "json":
        return parse_json_document(raw_bytes)
    if fmt == "html":
        return parse_html_document(raw_bytes)
    raise ValueError(f"unsupported structured format: {fmt}")
