"use client";

import { useEffect, useId, useState } from "react";
import { isSafeMermaidSource, renderMermaid } from "@/lib/safeVisual";

type Props = { source: string; caption?: string };

/**
 * Mermaid diagram rendered with `securityLevel: "strict"`. Unsafe or failing sources
 * are never rendered; the source is then shown as plain text (React escapes it).
 */
export default function MermaidDiagram({ source, caption }: Props) {
  const id = useId();
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const safe = isSafeMermaidSource(source);

  useEffect(() => {
    if (!safe) return;
    let cancelled = false;
    renderMermaid(source, id)
      .then((out) => {
        if (!cancelled) setSvg(out);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [source, id, safe]);

  return (
    <figure className="lb-diagram" dir="ltr">
      {caption && <figcaption className="lb-caption">{caption}</figcaption>}
      {svg && <div className="lb-svg" dangerouslySetInnerHTML={{ __html: svg }} />}
      {!svg && (
        <>
          {!safe && <p className="lb-caption">این نمودار از بررسی ایمنی نگذشت؛ کد آن به‌صورت متن نمایش داده می‌شود.</p>}
          {failed && <p className="lb-caption">نمایش نمودار ممکن نشد.</p>}
          {(!safe || failed) && <pre className="lb-code">{source}</pre>}
        </>
      )}
    </figure>
  );
}
