"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

type Props = {
  src: string;
  alt: string;
  caption?: string | null;
  onClose: () => void;
};

/** Full-screen image viewer: Escape or the close button dismisses it, focus returns to the opener. */
export default function ImageLightbox({ src, alt, caption, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="lightbox-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      onClick={onClose}
    >
      <figure className="lightbox-figure" onClick={(event) => event.stopPropagation()}>
        <button
          ref={closeRef}
          type="button"
          className="lightbox-close"
          aria-label="بستن تصویر"
          onClick={onClose}
        >
          <X size={20} />
        </button>
        {/* Authenticated object URL created by the caller; not a remote URL. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} className="lightbox-img" />
        {caption ? <figcaption className="lightbox-caption">{caption}</figcaption> : null}
      </figure>
    </div>
  );
}
