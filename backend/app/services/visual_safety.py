"""Phase 6 visual safety: server-side sanitizers for AI-generated diagrams.

Every SVG or Mermaid string produced by a model is treated as hostile:

- ``sanitize_svg`` parses the markup with ``defusedxml`` (no DTD/entity expansion) and
  rebuilds it from an element and attribute allowlist. Scripts, ``foreignObject``,
  event handlers, ``style`` blocks, external or ``javascript:`` references and
  ``use``/``image`` elements are dropped. The output is plain SVG markup.
- ``validate_mermaid`` accepts only a short list of diagram types and rejects any
  HTML, click/callback directives, init directives and URLs.

The browser applies a second layer (DOMPurify, Mermaid ``securityLevel: "strict"``).
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

SVG_NS = "http://www.w3.org/2000/svg"
MAX_SVG_BYTES = 60_000
MAX_MERMAID_CHARS = 4_000

SVG_ELEMENTS: frozenset[str] = frozenset(
    {
        "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
        "text", "tspan", "title", "desc", "defs", "marker", "linearGradient",
        "radialGradient", "stop",
    }
)

SVG_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height",
        "d", "points", "fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap",
        "stroke-linejoin", "opacity", "fill-opacity", "stroke-opacity", "transform", "viewBox",
        "preserveAspectRatio", "font-size", "font-family", "font-weight", "text-anchor",
        "dominant-baseline", "dx", "dy", "offset", "stop-color", "stop-opacity", "direction",
        "marker-end", "marker-start", "marker-mid", "markerWidth", "markerHeight", "refX",
        "refY", "orient", "gradientUnits", "gradientTransform", "version", "xmlns",
    }
)

_INTERNAL_URL_RE = re.compile(r"^url\(#[A-Za-z0-9_\-]{1,64}\)$")
_UNSAFE_VALUE_RE = re.compile(r"javascript:|expression\(|@import|<|-moz-binding|data:", re.IGNORECASE)
_PAINT_ATTRS = frozenset({"fill", "stroke"})
_URL_ATTRS = frozenset({"marker-end", "marker-start", "marker-mid"})

MERMAID_TYPES: tuple[str, ...] = ("flowchart", "graph", "mindmap", "timeline")
_MERMAID_FORBIDDEN_RE = re.compile(
    r"<|%%\{|\bclick\b|javascript:|\bcall\b|\bhref\b|\bon[a-z]+\s*=|\bdata:|\bsrc\s*=|\bstyle\s+\S+\s+url\(",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class UnsafeVisualError(ValueError):
    """Raised when a model output cannot be made safe."""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _safe_attribute_value(name: str, value: str) -> str | None:
    value = value.strip()
    if len(value) > 300 or _UNSAFE_VALUE_RE.search(value):
        return None
    if name in _URL_ATTRS:
        return value if _INTERNAL_URL_RE.match(value) else None
    if name in _PAINT_ATTRS and "url(" in value.lower():
        return value if _INTERNAL_URL_RE.match(value) else None
    return value


def _clean_element(element: ET.Element) -> ET.Element | None:
    name = _local_name(element.tag)
    if name not in SVG_ELEMENTS:
        return None
    clean = ET.Element(name)
    for attr, value in element.attrib.items():
        local = _local_name(attr)
        if local not in SVG_ATTRIBUTES or local == "xmlns":
            continue
        safe_value = _safe_attribute_value(local, value)
        if safe_value is not None:
            clean.set(local, safe_value)
    if element.text and name in {"text", "tspan", "title", "desc"}:
        text = _UNSAFE_VALUE_RE.sub("", element.text)
        clean.text = text[:500]
    for child in list(element):
        cleaned = _clean_element(child)
        if cleaned is not None:
            clean.append(cleaned)
    return clean


def sanitize_svg(raw: str) -> str:
    """Return safe SVG markup or raise :class:`UnsafeVisualError`."""
    if not isinstance(raw, str) or not raw.strip():
        raise UnsafeVisualError("svg is empty")
    if len(raw.encode("utf-8")) > MAX_SVG_BYTES:
        raise UnsafeVisualError("svg is too large")
    try:
        root = SafeET.fromstring(raw.strip())
    except (ET.ParseError, DefusedXmlException, ValueError) as error:
        raise UnsafeVisualError("svg is not well-formed or contains forbidden XML") from error
    if _local_name(root.tag) != "svg":
        raise UnsafeVisualError("root element must be svg")
    clean_root = _clean_element(root)
    if clean_root is None:  # pragma: no cover - root name already checked
        raise UnsafeVisualError("svg root rejected")
    clean_root.set("xmlns", SVG_NS)
    if not any(_local_name(child.tag) in {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "g"} for child in root.iter()):
        raise UnsafeVisualError("svg has no drawable content")
    return ET.tostring(clean_root, encoding="unicode")


def validate_mermaid(source: Any) -> str:
    """Return normalized Mermaid source or raise :class:`UnsafeVisualError`."""
    if not isinstance(source, str):
        raise UnsafeVisualError("mermaid source must be text")
    text = _CONTROL_RE.sub("", source).strip()
    if not text:
        raise UnsafeVisualError("mermaid source is empty")
    if len(text) > MAX_MERMAID_CHARS:
        raise UnsafeVisualError("mermaid source is too long")
    if _MERMAID_FORBIDDEN_RE.search(text):
        raise UnsafeVisualError("mermaid source contains forbidden directives or markup")
    first = next((line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("%%")), "")
    keyword = first.split()[0].lower() if first else ""
    if keyword not in MERMAID_TYPES:
        raise UnsafeVisualError("mermaid diagram type is not allowed")
    return text


def sanitize_block_content(block_type: str, content: str) -> str:
    """Sanitize one learning block's content by type (used on every write)."""
    if block_type == "diagram_svg":
        return sanitize_svg(content)
    if block_type == "diagram_mermaid":
        return validate_mermaid(content)
    return content


__all__ = [
    "MERMAID_TYPES",
    "UnsafeVisualError",
    "sanitize_block_content",
    "sanitize_svg",
    "validate_mermaid",
]
