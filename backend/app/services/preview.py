"""Visual preview generator: self-contained RTL HTML with KaTeX + marked.js.

Used by both the CLI (scripts/test_ingest.py) and the API preview endpoint.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Any


def model_tag(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", model)

CDN = {
    "vazirmatn": "https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;700&display=swap",
    "katex_css": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css",
    "katex_js": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js",
    "auto_render": "https://cdn.jsdelivr.net/npm/katex@0.16.11/contrib/auto-render.min.js",
    "marked": "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
}


def _b64(path: str | Path | None) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.is_file():
        return ""
    return base64.b64encode(file_path.read_bytes()).decode("ascii")


def _escape(text: str | None) -> str:
    return html.escape(text or "")


def _badge(label: str, value: str | None, tone: str = "neutral") -> str:
    return (
        f'<span class="badge {tone}"><b>{_escape(label)}</b> {_escape(value) if value is not None else "—"}</span>'
    )


def _warnings_block(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{_escape(w)}</li>" for w in warnings)
    return f'<ul class="warnings">{items}</ul>'


def _visuals_block(visual_elements: list[dict[str, str]]) -> str:
    if not visual_elements:
        return ""
    boxes = []
    for el in visual_elements:
        boxes.append(
            f'<div class="vbox">'
            f'<span class="vlabel">{_escape(el.get("label", ""))}</span> '
            f'<span class="vtype">{_escape(el.get("type", ""))}</span>'
            f'<div class="vdesc">{_escape(el.get("scientific_description", ""))}</div>'
            f"</div>"
        )
    return f'<div class="visuals">{ "".join(boxes) }</div>'


def _md_container(page: dict[str, Any], model_key: str) -> str:
    markdown = page.get("markdown", "")
    return (
        f'<textarea class="md-source" data-model="{model_key}" style="display:none">'
        f"{_escape(markdown)}</textarea>"
        f'<div class="md-body" data-model="{model_key}"></div>'
    )


def _image_block(image_path: str | Path | None, page_idx: Any) -> str:
    if not image_path:
        return '<div class="imgwrap img-missing">منبع متنی/ساختاریافته (بدون تصویر PDF)</div>'
    encoded = _b64(image_path)
    if not encoded:
        return '<div class="imgwrap img-missing">تصویر صفحه موجود نیست</div>'
    return f'<div class="imgwrap"><img src="data:image/png;base64,{encoded}" alt="page {_escape(str(page_idx))}"></div>'


def _page_card_single(page: dict[str, Any], model_key: str) -> str:
    status = page.get("status", "unknown")
    tone = "red" if status == "failed" else ("amber" if status == "needs_review" else "green")
    badges = (
        _badge("PDF صفحه", str(page.get("pdf_page_index"))),
        _badge("صفحهٔ چاپی", str(page.get("printed_page_number")) if page.get("printed_page_number") is not None else None),
        _badge("فصل", str(page.get("chapter_number")) if page.get("chapter_number") is not None else None),
        _badge("عنوان فصل", page.get("chapter_title")),
        _badge("وضعیت", status, tone),
        _badge("مدل", page.get("model")),
        _badge("ویرایش انسانی", "بله" if page.get("edited_by_human") else "خیر"),
    )
    return (
        f'<article class="page">'
        f'<div class="left">'
        f'{_image_block(page.get("image_path"), page.get("pdf_page_index"))}'
        f"</div>"
        f'<div class="right">'
        f'<div class="badges">{"".join(badges)}</div>'
        f'{_warnings_block(page.get("warnings", []))}'
        f'{_md_container(page, model_key)}'
        f'{_visuals_block(page.get("visual_elements", []))}'
        f"</div>"
        f"</article>"
    )


def _summary_table(summary: dict[str, dict[str, Any]], names: dict[str, str]) -> str:
    rows = []
    for key, totals in summary.items():
        errors_id = f"kx_err_{key}"
        rows.append(
            f"<tr>"
            f"<td>{_escape(names.get(key, key))}</td>"
            f'<td>{totals.get("tokens", 0)}</td>'
            f'<td>{totals.get("latency", 0):.2f}</td>'
            f'<td>{totals.get("warnings", 0)}</td>'
            f'<td id="{errors_id}">0</td>'
            f"</tr>"
        )
    return (
        '<table class="summary"><thead>'
        '<tr><th>مدل</th><th>توکن</th><th>زمان تخمینی (s)</th><th>هشدار</th><th>خطای KaTeX</th></tr>'
        "</thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _compare_card(page_idx: int, image_b64: str, models: list[tuple[str, str, dict[str, Any]]]) -> str:
    left = (
        f'<div class="imgwrap"><img src="data:image/png;base64,{image_b64}" alt="page {page_idx}"></div>'
        if image_b64
        else '<div class="imgwrap img-missing">تصویر صفحه موجود نیست</div>'
    )
    cols = [f'<div class="cmp-left">{left}</div>']
    for key, model_name, page in models:
        status = page.get("status", "unknown")
        tone = "red" if status == "failed" else ("amber" if status == "needs_review" else "green")
        badges = (
            _badge("صفحهٔ چاپی", str(page.get("printed_page_number")) if page.get("printed_page_number") is not None else None),
            _badge("فصل", str(page.get("chapter_number")) if page.get("chapter_number") is not None else None),
            _badge("وضعیت", status, tone),
        )
        cols.append(
            f'<div class="cmp-model"><h4>{_escape(model_name)}</h4>'
            f'<div class="badges">{"".join(badges)}</div>'
            f'{_warnings_block(page.get("warnings", []))}'
            f'{_md_container(page, key)}'
            f'{_visuals_block(page.get("visual_elements", []))}'
            f"</div>"
        )
    return f'<article class="page cmp">' + "".join(cols) + "</article>"


_JS = r"""
const kxErrors = {};
function scan(markdown, modelKey, el) {
  if (!el) return;
  try {
    var parsed = marked.parse(markdown);
    el.innerHTML = parsed;
  } catch (e) { el.textContent = markdown; }
  if (window.renderMathInElement) {
    var opts = {
      delimiters: [
        {left:"$$", right:"$$", display:true},
        {left:"\\[", right:"\\]", display:true},
        {left:"$", right:"$", display:false},
        {left:"\\(", right:"\\)", display:false}
      ],
      throwOnError: false,
      errorCallback: function () {
        kxErrors[modelKey] = (kxErrors[modelKey] || 0) + 1;
        try { document.getElementById('kx_err_'+modelKey).textContent = kxErrors[modelKey]; } catch(e){}
      }
    };
    try { renderMathInElement(el, opts); } catch (e) {}
  }
  var total = 0;
  for (var k in kxErrors) total += kxErrors[k];
  var c = document.getElementById('katex-error-count');
  if (c) c.textContent = total;
}
document.addEventListener('DOMContentLoaded', function () {
  var sources = document.querySelectorAll('textarea.md-source');
  sources.forEach(function (t) {
    var target = t.nextElementSibling;
    if (!target || !target.classList.contains('md-body')) {
      target = t.parentElement ? t.parentElement.querySelector('.md-body') : null;
    }
    scan(t.value, t.getAttribute('data-model'), target);
  });
});
"""


def _head(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<link rel="stylesheet" href="{CDN['vazirmatn']}">
<link rel="stylesheet" href="{CDN['katex_css']}">
<style>
:root {{ --bg:#faf9f7; --card:#ffffff; --ink:#1f2933; --muted:#6b7280; --line:#e5e7eb; --red:#dc2626; --amber:#d97706; --green:#059669; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:'Vazirmatn',system-ui,sans-serif; background:var(--bg); color:var(--ink); }}
header {{ position:sticky; top:0; background:var(--card); border-bottom:1px solid var(--line); padding:12px 20px; display:flex; align-items:center; gap:16px; z-index:10; }}
header h1 {{ font-size:18px; margin:0; }}
.errcount {{ margin-inline-start:auto; background:#fef2f2; color:var(--red); border:1px solid #fecaca; padding:4px 12px; border-radius:999px; font-weight:700; }}
main {{ max-width:1280px; margin:0 auto; padding:20px; }}
.page {{ display:grid; grid-template-columns:minmax(0,42fr) minmax(0,58fr); gap:18px; background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:22px; }}
.page.cmp {{ grid-template-columns:minmax(0,34fr) minmax(0,33fr) minmax(0,33fr); }}
.imgwrap {{ background:#fff; border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
.imgwrap.img-missing {{ display:grid; place-items:center; min-height:220px; color:var(--muted); font-size:13px; background:#f9fafb; }}
.imgwrap img {{ width:100%; height:auto; display:block; }}
.right {{ min-width:0; }}
.badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
.badge {{ font-size:12px; background:#f3f4f6; border:1px solid var(--line); border-radius:999px; padding:2px 10px; }}
.badge.green {{ background:#ecfdf5; color:var(--green); border-color:#a7f3d0; }}
.badge.amber {{ background:#fffbeb; color:var(--amber); border-color:#fde68a; }}
.badge.red {{ background:#fef2f2; color:var(--red); border-color:#fecaca; }}
.warnings {{ color:var(--red); font-size:13px; margin:8px 0; }}
.md-body {{ direction:rtl; line-height:1.9; font-size:15px; overflow-wrap:anywhere; }}
.md-body .katex {{ direction:ltr; unicode-bidi:isolate; }}
.md-body .katex-error {{ color:var(--red) !important; }}
.visuals {{ margin-top:10px; display:flex; flex-wrap:wrap; gap:8px; }}
.vbox {{ border:1px dashed #c4b5fd; background:#faf5ff; border-radius:10px; padding:8px 12px; max-width:100%; }}
.vlabel {{ font-weight:700; color:#6d28d9; }}
.vtype {{ font-size:12px; color:var(--muted); }}
.vdesc {{ font-size:13px; margin-top:4px; }}
.summary {{ width:100%; border-collapse:collapse; margin-bottom:20px; background:var(--card); }}
.summary th,.summary td {{ border:1px solid var(--line); padding:8px 12px; text-align:center; font-size:14px; }}
.summary th {{ background:#f9fafb; }}
.cmp-model {{ min-width:0; border-right:1px solid var(--line); padding-inline-start:14px; }}
h4 {{ margin:0 0 8px; font-size:15px; }}
</style>
</head>
<body>
<header>
  <h1>{_escape(title)}</h1>
  <span class="errcount">خطای KaTeX: <span id="katex-error-count">0</span></span>
</header>
<main>
"""


def _tail() -> str:
    return f"""</main>
<script src="{CDN['katex_js']}"></script>
<script src="{CDN['auto_render']}"></script>
<script src="{CDN['marked']}"></script>
<script>{_JS}</script>
</body>
</html>
"""


def render_single_preview(
    book_id: str | int, tag: str, pages: list[dict[str, Any]], out_path: Path
) -> Path:
    model_key = tag
    cards = "".join(_page_card_single(p, model_key) for p in pages)
    html_doc = _head(f"پیش‌نمایش {tag} — کتاب {book_id}") + cards + _tail()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def render_compare_preview(
    book_id: str | int,
    model_a: str,
    model_b: str,
    pages_a: list[dict[str, Any]],
    pages_b: list[dict[str, Any]],
    summary: dict[str, dict[str, Any]],
    out_path: Path,
) -> Path:
    key_a, key_b = model_tag(model_a), model_tag(model_b)
    image_map = {p["pdf_page_index"]: _b64(p["image_path"]) for p in pages_a}
    cards = []
    for idx in sorted(image_map):
        a = next((p for p in pages_a if p["pdf_page_index"] == idx), {})
        b = next((p for p in pages_b if p["pdf_page_index"] == idx), {})
        cards.append(
            _compare_card(idx, image_map[idx], [(key_a, model_a, a), (key_b, model_b, b)])
        )
    html_doc = (
        _head(f"مقایسهٔ استخراج — کتاب {book_id}")
        + _summary_table(summary, {key_a: model_a, key_b: model_b})
        + "".join(cards)
        + _tail()
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
