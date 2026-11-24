"use client";

import { useEffect, useState } from "react";
import { Volume2, Loader2 } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import { phase6ErrorMessage } from "@/lib/phase6";

type Props = {
  text: string;
  bookId?: number | null;
  label?: string;
};

/**
 * Selected-text read-aloud. The request goes to the backend TTS endpoint (capability
 * and quota gated, cached by content). The voice and provider are admin-only settings.
 */
export default function AudioButton({ text, bookId, label = "پخش صدا" }: Props) {
  const { authFetch } = useAppContext();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);

  const play = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/v1/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, book_id: bookId ?? null }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        setError(phase6ErrorMessage(payload, "پخش صدا ممکن نشد."));
        return;
      }
      const blob = await res.blob();
      const next = URL.createObjectURL(blob);
      if (url) URL.revokeObjectURL(url);
      setUrl(next);
      void new Audio(next).play();
    } catch {
      setError("پخش صدا ممکن نشد.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="audio-button" dir="rtl">
      <button type="button" className="btn-ghost" onClick={play} disabled={busy || !text.trim()} aria-label={label}>
        {busy ? <Loader2 size={15} className="spin" /> : <Volume2 size={15} />}
        <span>{label}</span>
      </button>
      {error && <span role="alert" className="lb-caption">{error}</span>}
    </span>
  );
}
