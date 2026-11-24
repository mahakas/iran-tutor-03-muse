"use client";

import Link from "next/link";
import { useState } from "react";
import { BookOpen } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import BookGradePicker from "@/components/BookGradePicker";
import LearningBlockRenderer from "@/components/LearningBlockRenderer";
import AudioButton from "@/components/AudioButton";
import { phase6ErrorMessage, toFaDigits, type LivingBookBlock, type LivingBookPayload } from "@/lib/phase6";

const SECTION_LABELS: Record<string, string> = {
  text_markdown: "مفاهیم کلیدی",
  callout_tip: "نکته‌ها و هشدارها",
  diagram_mermaid: "نمودارها",
  quiz_item: "آزمون کوتاه",
  flashcard_item: "فلش‌کارت‌ها",
};

const CHOICE_KEYS = ["A", "B", "C", "D"];

/** Adapt backend quiz metadata (`choices`, `correct_option`) to the typed QuizBlock contract. */
function toRenderable(block: LivingBookBlock): LivingBookBlock {
  if (block.type !== "quiz_item") return block;
  const choices = (block.metadata.choices ?? {}) as Record<string, unknown>;
  return {
    ...block,
    metadata: {
      ...block.metadata,
      options: CHOICE_KEYS.map((key) => String(choices[key] ?? "")),
      answer_index: CHOICE_KEYS.indexOf(String(block.metadata.correct_option ?? "")),
    },
  };
}

/**
 * One chapter compiled into an interactive study view. Only validated, page-grounded
 * items are shown; the rejected count is shown for transparency (reasons are in /admin).
 */
export default function LivingBookWorkspace() {
  const { authFetch } = useAppContext();
  const [bookId, setBookId] = useState<number | null>(null);
  const [chapter, setChapter] = useState("1");
  const [data, setData] = useState<LivingBookPayload | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!bookId) return setMessage("کتاب را انتخاب کنید.");
    const number = Number(chapter);
    if (!Number.isInteger(number) || number < 1 || number > 99) return setMessage("شمارهٔ فصل نامعتبر است.");
    setBusy(true);
    setMessage(null);
    try {
      const res = await authFetch(`/api/v1/living-book/${bookId}/chapters/${number}`);
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setData(null);
        return setMessage(phase6ErrorMessage(payload, "کتاب زنده ساخته نشد."));
      }
      setData(payload as LivingBookPayload);
    } finally {
      setBusy(false);
    }
  };

  const groups = new Map<string, LivingBookPayload["blocks"]>();
  for (const block of data?.blocks ?? []) {
    groups.set(block.type, [...(groups.get(block.type) ?? []), block]);
  }

  return (
    <div className="living-book" dir="rtl" lang="fa">
      <section className="glass-panel" aria-label="انتخاب فصل">
        <BookGradePicker value={bookId} onChange={setBookId} />
        <label>
          شمارهٔ فصل
          <input type="number" min={1} max={99} value={chapter} onChange={(e) => setChapter(e.target.value)} />
        </label>
        <button type="button" className="btn-primary" onClick={load} disabled={busy}>
          <BookOpen size={15} /> <span>{busy ? "در حال آماده‌سازی…" : "نمایش کتاب زنده"}</span>
        </button>
        {message && <p role="alert" className="lb-caption">{message}</p>}
      </section>

      {data && (
        <article className="glass-panel" aria-label="کتاب زنده">
          <header>
            <h2>{data.book_title} — فصل {toFaDigits(data.chapter_number)}: {data.chapter_title}</h2>
            <p className="lb-caption">
              صفحه‌های چاپی: {data.printed_pages.map((n) => toFaDigits(n)).join("، ")}
              {data.cache_hit ? " · از حافظهٔ مشترک" : " · تازه ساخته شد"}
              {data.rejected_count > 0 && ` · ${toFaDigits(data.rejected_count)} مورد به‌دلیل بررسی منبع کنار گذاشته شد`}
            </p>
          </header>
          {Array.from(groups.entries()).map(([key, blocks]) => (
            <section key={key} className="living-book-section">
              <h3>{SECTION_LABELS[key] ?? "بخش"}</h3>
              {blocks.map((block, index) => (
                <div key={`${key}-${index}`} className="living-book-item">
                  <LearningBlockRenderer blocks={[toRenderable(block)]} />
                  {typeof block.metadata.citation === "string" && (
                    <>
                      <p className="lb-caption">منبع: {block.metadata.citation}</p>
                      <Link href={`/study/${data.book_id}`} className="lb-caption">
                        مشاهده در مطالعهٔ کتاب
                      </Link>
                    </>
                  )}
                  {(block.type === "text_markdown" || block.type === "callout_tip") && (
                    <AudioButton text={block.content} bookId={data.book_id} label="پخش" />
                  )}
                </div>
              ))}
            </section>
          ))}
          {data.blocks.length === 0 && <p className="lb-caption">برای این فصل محتوای معتبری ساخته نشد.</p>}
        </article>
      )}
    </div>
  );
}
