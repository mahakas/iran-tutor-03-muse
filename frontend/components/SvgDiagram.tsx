"use client";

import { useSyncExternalStore } from "react";
import { sanitizeSvg } from "@/lib/safeVisual";

const noopSubscribe = () => () => {};

/**
 * Inline SVG from a learning block. Sanitized in the browser right before insertion;
 * nothing is rendered during server render, so no unsanitized markup can leave the server.
 */
export default function SvgDiagram({ svg }: { svg: string }) {
  // Server snapshot is null, so nothing is emitted during SSR; the browser snapshot is sanitized.
  const clean = useSyncExternalStore(
    noopSubscribe,
    () => sanitizeSvg(svg),
    () => null as string | null
  );

  if (clean === null) return null;
  if (!clean) {
    return <p className="lb-caption">این نمودار از بررسی ایمنی نگذشت و نمایش داده نمی‌شود.</p>;
  }
  return (
    <div
      className="lb-svg"
      dir="ltr"
      // Sanitized by DOMPurify + allowlist in `sanitizeSvg` immediately above.
      dangerouslySetInnerHTML={{ __html: clean }}
    />
  );
}
