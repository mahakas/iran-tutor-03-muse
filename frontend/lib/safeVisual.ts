/**
 * Phase 6 browser-side visual safety (second layer after the backend sanitizer).
 *
 * - `sanitizeSvg`: DOMPurify with the SVG profile, plus an explicit allowlist of
 *   elements, no `style`, and only in-document `url(#id)` / `#id` references.
 *   Without a DOM (server render) it returns "" so nothing unsafe is ever emitted.
 * - `isSafeMermaidSource`: mirrors the backend `validate_mermaid` rules.
 * - `renderMermaid`: Mermaid with `securityLevel: "strict"`, HTML labels disabled,
 *   loaded lazily in the browser only; output is sanitized again before insertion.
 */
import DOMPurify from "dompurify";

const SVG_FORBID_TAGS = [
  "script", "foreignObject", "style", "use", "image", "animate", "set",
  "animateMotion", "animateTransform", "iframe", "object", "embed", "a", "link", "meta",
];

const SVG_FORBID_ATTR = ["style", "href", "xlink:href", "src", "srcset", "formaction", "action"];

const MERMAID_TYPES = ["flowchart", "graph", "mindmap", "timeline"] as const;
const MERMAID_FORBIDDEN =
  /<|%%\{|\bclick\b|javascript:|\bcall\b|\bhref\b|\bon[a-z]+\s*=|\bdata:|\bsrc\s*=|\bstyle\s+\S+\s+url\(/i;
const MAX_MERMAID_CHARS = 4000;
const INTERNAL_URL = /^url\(#[A-Za-z0-9_-]{1,64}\)$/;
const INTERNAL_HREF = /^#[A-Za-z0-9_-]{1,64}$/;

let hooksInstalled = false;

function installHooks() {
  if (hooksInstalled || !DOMPurify.isSupported) return;
  hooksInstalled = true;
  DOMPurify.addHook("uponSanitizeAttribute", (_node, data) => {
    const name = data.attrName.toLowerCase();
    if (name === "marker-end" || name === "marker-start" || name === "marker-mid" || name === "fill" || name === "stroke") {
      if (!INTERNAL_URL.test(data.attrValue.trim()) && name.startsWith("marker")) {
        data.keepAttr = false;
      }
      if (/url\(/i.test(data.attrValue) && !INTERNAL_URL.test(data.attrValue.trim())) {
        data.keepAttr = false;
      }
    }
    if (/javascript:|data:|expression\(|@import/i.test(data.attrValue)) {
      data.keepAttr = false;
    }
    if (name.startsWith("on")) {
      data.keepAttr = false;
    }
  });
}

/** Sanitize an SVG string for inline rendering. Returns "" when no DOM is available. */
export function sanitizeSvg(svg: string): string {
  if (!DOMPurify.isSupported || typeof svg !== "string" || !svg.trim()) return "";
  installHooks();
  const clean = DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: false },
    FORBID_TAGS: SVG_FORBID_TAGS,
    FORBID_ATTR: SVG_FORBID_ATTR,
    ALLOW_DATA_ATTR: false,
    RETURN_TRUSTED_TYPE: false,
  }) as unknown as string;
  // Keep the result only if it is a single SVG root; anything else is dropped.
  if (!/^<svg[\s>]/i.test(clean.trim())) return "";
  return clean;
}

/** Same rules as backend `validate_mermaid` (returns false instead of throwing). */
export function isSafeMermaidSource(source: unknown): source is string {
  if (typeof source !== "string") return false;
  const text = source.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "").trim();
  if (!text || text.length > MAX_MERMAID_CHARS) return false;
  if (MERMAID_FORBIDDEN.test(text)) return false;
  const first = text
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("%%"));
  const keyword = first ? first.split(/\s+/)[0].toLowerCase() : "";
  return (MERMAID_TYPES as readonly string[]).includes(keyword);
}

/** Render Mermaid in the browser only; rejects anything the guard does not accept. */
export async function renderMermaid(source: string, id: string): Promise<string> {
  if (typeof window === "undefined") throw new Error("mermaid renders in the browser only");
  if (!isSafeMermaidSource(source)) throw new Error("unsafe mermaid source");
  const mermaid = (await import("mermaid")).default;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: "neutral",
    maxTextSize: MAX_MERMAID_CHARS,
    maxEdges: 200,
    flowchart: { htmlLabels: false },
  });
  const safeId = `mmd-${id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40) || "x"}`;
  const { svg } = await mermaid.render(safeId, source);
  const clean = sanitizeSvg(svg);
  if (!clean) throw new Error("mermaid output rejected");
  return clean;
}
