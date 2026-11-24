"use client";

import { useEffect, useState } from "react";
import { ImageOff, ZoomIn } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import ImageLightbox from "@/components/ImageLightbox";
import type { SourceFigure } from "@/lib/phase5";

type Props = { bookId: number; figure: SourceFigure };

/**
 * Source figure with loader, caption and lightbox. Uses the student-scoped figure endpoint
 * (auth required), so the image is fetched with the bearer token and shown as an object URL.
 */
export default function FigureThumb({ bookId, figure }: Props) {
  const { authFetch } = useAppContext();
  const [src, setSrc] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [open, setOpen] = useState(false);
  const label = `${figure.figure_label ?? "شکل"}${figure.caption ? `: ${figure.caption}` : ""}`;

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    // Each figure mounts with status "loading" (list keys by figure id), so no reset here.
    (async () => {
      try {
        const res = await authFetch(`/api/v1/curriculum/books/${bookId}/figures/${figure.id}/image`);
        if (!res.ok) throw new Error("figure");
        objectUrl = URL.createObjectURL(await res.blob());
        if (cancelled) return;
        setSrc(objectUrl);
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [authFetch, bookId, figure.id]);

  return (
    <figure className="figure-thumb">
      {status === "loading" ? <span className="skeleton figure-thumb-skeleton" aria-hidden="true" /> : null}
      {status === "error" ? (
        <div className="figure-thumb-error">
          <ImageOff size={18} aria-hidden="true" /> تصویر این شکل در دسترس نیست.
        </div>
      ) : null}
      {status === "ready" && src ? (
        <button type="button" className="figure-thumb-button" onClick={() => setOpen(true)} aria-label={`بزرگ‌نمایی ${label}`}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={label} className="figure-thumb-img" />
          <span className="figure-thumb-zoom"><ZoomIn size={14} aria-hidden="true" /></span>
        </button>
      ) : null}
      <figcaption className="figure-thumb-caption">
        {figure.figure_label ?? "شکل"}
        {figure.caption ? ` — ${figure.caption}` : ""}
      </figcaption>
      {open && src ? (
        <ImageLightbox src={src} alt={label} caption={figure.caption} onClose={() => setOpen(false)} />
      ) : null}
    </figure>
  );
}
