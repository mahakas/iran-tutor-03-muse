/**
 * Normalize common LaTeX delimiters (`\(...\)` and `\[...\]`) into `$...$` / `$$...$$`
 * outside fenced code blocks so remark-math + rehype-katex render them reliably.
 */
export function normalizeLatexMarkdown(markdown: string): string {
  if (!markdown) return "";
  return markdown
    .split(/(```[\s\S]*?```|`[^`\n]+`)/g)
    .map((segment, idx) => {
      if (idx % 2 === 1) return segment;
      return segment
        .replace(/\\\[([\s\S]*?)\\\]/g, (_match, inner: string) => `\n$$\n${inner.trim()}\n$$\n`)
        .replace(/\\\(([\s\S]*?)\\\)/g, (_match, inner: string) => `$${inner.trim()}$`);
    })
    .join("");
}
