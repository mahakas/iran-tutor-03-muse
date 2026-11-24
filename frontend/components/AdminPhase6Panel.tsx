"use client";

import { useEffect, useState } from "react";
import { toFaDigits } from "@/lib/phase6";

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

type LivingRow = {
  id: number;
  book_id: number;
  chapter_number: number;
  chapter_title: string;
  content_hash: string;
  model_name: string | null;
  hit_count: number;
  block_count: number;
  rejected: Array<{ kind: string; reason: string }>;
  created_at: string | null;
};

type AudioRow = {
  id: number;
  cache_key: string;
  voice: string;
  model_name: string;
  text_chars: number;
  byte_size: number;
  hit_count: number;
  book_id: number | null;
  created_at: string | null;
};

/** Glass box for Phase 6: Living Book cache with rejection reasons, and the TTS audio cache. */
export default function AdminPhase6Panel({ authHeaders, onUnauthorized }: Props) {
  const [living, setLiving] = useState<LivingRow[]>([]);
  const [audio, setAudio] = useState<AudioRow[]>([]);
  const [audioBytes, setAudioBytes] = useState(0);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, b] = await Promise.all([
        fetch("/api/v1/admin/phase6/living-book", { cache: "no-store", credentials: "same-origin", headers: authHeaders }),
        fetch("/api/v1/admin/phase6/audio-cache", { cache: "no-store", credentials: "same-origin", headers: authHeaders }),
      ]);
      if (a.status === 401 || a.status === 403 || b.status === 401 || b.status === 403) {
        onUnauthorized();
        return;
      }
      if (!a.ok || !b.ok) {
        if (!cancelled) setMessage("بارگذاری گزارش‌ها ممکن نشد.");
        return;
      }
      const la = (await a.json()) as { items: LivingRow[] };
      const lb = (await b.json()) as { items: AudioRow[]; total_bytes: number };
      if (!cancelled) {
        setLiving(la.items);
        setAudio(lb.items);
        setAudioBytes(lb.total_bytes);
      }
    })();
    return () => {
      cancelled = true;
    };
    // authHeaders identity is memoized by the parent page.
  }, [authHeaders, onUnauthorized]);

  return (
    <section className="glass-panel" dir="rtl" lang="fa" aria-label="گزارش مطالعهٔ غنی">
      <h2>کتاب‌های زنده (حافظهٔ مشترک)</h2>
      {message && <p role="alert">{message}</p>}
      <table className="admin-table">
        <thead>
          <tr>
            <th>کتاب</th>
            <th>فصل</th>
            <th>بلوک‌های پذیرفته</th>
            <th>دفعات استفاده</th>
            <th>ردشده‌ها (دلیل)</th>
            <th>مدل</th>
          </tr>
        </thead>
        <tbody>
          {living.map((row) => (
            <tr key={row.id}>
              <td>{toFaDigits(row.book_id)}</td>
              <td>{toFaDigits(row.chapter_number)} · {row.chapter_title}</td>
              <td>{toFaDigits(row.block_count)}</td>
              <td>{toFaDigits(row.hit_count)}</td>
              <td>
                {row.rejected.length === 0
                  ? "—"
                  : row.rejected.map((r, i) => (
                      <div key={i} dir="ltr">{r.kind}: {r.reason}</div>
                    ))}
              </td>
              <td dir="ltr">{row.model_name ?? "—"}</td>
            </tr>
          ))}
          {living.length === 0 && (
            <tr><td colSpan={6}>هنوز کتاب زنده‌ای ساخته نشده است.</td></tr>
          )}
        </tbody>
      </table>

      <h2>حافظهٔ صوت (TTS)</h2>
      <p>مجموع حجم: {toFaDigits(Math.round(audioBytes / 1024))} کیلوبایت · ورودی‌ها: {toFaDigits(audio.length)}</p>
      <table className="admin-table">
        <thead>
          <tr>
            <th>کلید</th>
            <th>صدا</th>
            <th>مدل</th>
            <th>نویسه</th>
            <th>دفعات استفاده</th>
          </tr>
        </thead>
        <tbody>
          {audio.map((row) => (
            <tr key={row.id}>
              <td dir="ltr">{row.cache_key}</td>
              <td dir="ltr">{row.voice}</td>
              <td dir="ltr">{row.model_name || "—"}</td>
              <td>{toFaDigits(row.text_chars)}</td>
              <td>{toFaDigits(row.hit_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
