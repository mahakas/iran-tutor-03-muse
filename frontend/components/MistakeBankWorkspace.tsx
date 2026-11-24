"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Layers, RotateCw } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import BookGradePicker from "@/components/BookGradePicker";
import {
  MISTAKE_ERROR_TAG_LABEL,
  MISTAKE_STATUS_LABEL,
  mistakeFilterQuery,
  phase5ErrorMessage,
  toPersianDigits,
  type MistakeErrorTag,
  type MistakeItem,
  type MistakeList,
  type MistakeStatus,
} from "@/lib/phase5";

type AnswerResult = { correct: boolean; correct_option: string; explanation: string | null; status: MistakeStatus };

const FILTERS: Array<{ key: MistakeStatus | "all"; label: string }> = [
  { key: "all", label: "همه" },
  { key: "unresolved", label: "حل‌نشده" },
  { key: "practiced", label: "در حال تمرین" },
  { key: "mastered", label: "تسلط‌یافته" },
];

const ERROR_TAG_FILTERS: Array<{ key: MistakeErrorTag | "all"; label: string }> = [
  { key: "all", label: "همهٔ خطاها" },
  { key: "wrong", label: MISTAKE_ERROR_TAG_LABEL.wrong },
  { key: "skipped", label: MISTAKE_ERROR_TAG_LABEL.skipped },
];

export default function MistakeBankWorkspace() {
  const { authFetch } = useAppContext();
  const [filter, setFilter] = useState<MistakeStatus | "all">("all");
  const [bookId, setBookId] = useState<number | null>(null);
  const [chapterNumber, setChapterNumber] = useState<number | null>(null);
  const [errorTag, setErrorTag] = useState<MistakeErrorTag | "all">("all");
  const [list, setList] = useState<MistakeList | null>(null);
  const [practice, setPractice] = useState<MistakeItem[] | null>(null);
  const [answers, setAnswers] = useState<Record<number, AnswerResult>>({});
  const [choice, setChoice] = useState<Record<number, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeErrorTag: MistakeErrorTag | null = errorTag === "all" ? null : errorTag;

  const load = useCallback(async () => {
    const query = mistakeFilterQuery({ status: filter, bookId, chapterNumber, errorTag: activeErrorTag });
    const res = await authFetch(`/api/v1/mistakes${query}`);
    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      setError(phase5ErrorMessage(payload, "بانک اشتباهات در دسترس نیست."));
      return;
    }
    setError(null);
    setList(payload as MistakeList);
  }, [authFetch, filter, bookId, chapterNumber, activeErrorTag]);

  useEffect(() => {
    // Defer one microtask: effects run after paint and microtasks run before the next
    // paint, so the load sequence is unchanged — it is just not synchronous inside the
    // effect (React 19 cascading-render rule; same inline-async shape as MasteryWorkspace).
    void (async () => {
      await Promise.resolve();
      await load();
    })();
  }, [load]);

  // Chapter options follow the currently loaded items (server-filtered data), so the
  // select only ever offers chapters that really exist in the student's mistake bank.
  const chapterOptions = useMemo(() => {
    const chapters = new Map<number, string>();
    for (const item of list?.items ?? []) {
      if (item.chapter_number !== null && !chapters.has(item.chapter_number)) {
        chapters.set(item.chapter_number, item.chapter_title ?? `فصل ${item.chapter_number}`);
      }
    }
    return [...chapters.entries()].sort((a, b) => a[0] - b[0]);
  }, [list]);

  const startPractice = async () => {
    const query = mistakeFilterQuery({ status: "all", bookId, chapterNumber, errorTag: activeErrorTag, practice: true });
    const res = await authFetch(`/api/v1/mistakes/practice-set${query}`);
    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      setNotice(phase5ErrorMessage(payload, "مجموعهٔ تمرین ساخته نشد."));
      return;
    }
    setAnswers({});
    setChoice({});
    setPractice((payload as { items: MistakeItem[] }).items ?? []);
  };

  const submitAnswer = async (item: MistakeItem) => {
    const selected = choice[item.id];
    if (!selected) return;
    const res = await authFetch(`/api/v1/mistakes/${item.id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice: selected }),
    });
    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      setNotice(phase5ErrorMessage(payload, "ثبت پاسخ انجام نشد."));
      return;
    }
    setAnswers((prev) => ({ ...prev, [item.id]: payload as AnswerResult }));
    void load();
  };

  const toFlashcard = async (item: MistakeItem) => {
    const res = await authFetch(`/api/v1/mistakes/${item.id}/flashcard`, { method: "POST" });
    const payload = await res.json().catch(() => null);
    setNotice(
      res.ok
        ? "این سؤال به فلش‌کارت‌ها اضافه شد."
        : phase5ErrorMessage(payload, "تبدیل به فلش‌کارت انجام نشد."),
    );
    if (res.ok) void load();
  };

  const hasScopeFilter = bookId !== null || chapterNumber !== null || activeErrorTag !== null;

  if (error) return <div className="glass-panel" style={{ padding: 24 }}>{error}</div>;
  if (!list) return <div className="glass-panel" style={{ padding: 24 }}>در حال بارگذاری…</div>;

  const renderItem = (item: MistakeItem, inPractice: boolean) => {
    const result = answers[item.id];
    return (
      <article key={item.id} className="glass-panel" style={{ padding: 16, display: "grid", gap: 10 }}>
        <header style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", fontSize: 13 }}>
          <span>
            {item.chapter_number ? `فصل ${toPersianDigits(item.chapter_number)}` : "بدون فصل"}
            {item.printed_page_number ? ` · صفحهٔ ${toPersianDigits(item.printed_page_number)}` : ""}
            {item.error_tag ? ` · ${MISTAKE_ERROR_TAG_LABEL[item.error_tag as MistakeErrorTag] ?? item.error_tag}` : ""}
          </span>
          <span>{MISTAKE_STATUS_LABEL[item.status]}</span>
        </header>
        <MathContent content={item.prompt} />
        <div style={{ display: "grid", gap: 6 }}>
          {Object.entries(item.choices).map(([key, text]) => (
            <label key={key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="radio"
                name={`mistake-${inPractice ? "practice-" : ""}${item.id}`}
                value={key}
                disabled={!inPractice || Boolean(result)}
                checked={choice[item.id] === key}
                onChange={() => setChoice((prev) => ({ ...prev, [item.id]: key }))}
              />
              <span>
                {key}. <MathContent content={text} />
              </span>
            </label>
          ))}
        </div>
        {inPractice && !result ? (
          <button type="button" className="btn-primary" disabled={!choice[item.id]} onClick={() => void submitAnswer(item)}>
            ثبت پاسخ
          </button>
        ) : null}
        {result ? (
          <div role="status" style={{ fontSize: 14, lineHeight: 1.9 }}>
            <strong>{result.correct ? "درست بود." : `نادرست؛ پاسخ صحیح: ${result.correct_option}`}</strong>
            {result.explanation ? <MathContent content={result.explanation} /> : null}
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          {item.flashcard_card_id ? (
            <>
              <span style={{ fontSize: 13 }}>در فلش‌کارت‌ها ثبت شده است.</span>
              <Link href="/flashcards" style={{ fontSize: 13 }}>مشاهدهٔ فلش‌کارت‌ها</Link>
            </>
          ) : (
            <button type="button" className="btn-ghost" onClick={() => void toFlashcard(item)}>
              <Layers size={14} /> ارسال به فلش‌کارت‌ها
            </button>
          )}
          {item.book_id ? (
            <Link href={`/study/${item.book_id}`} style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: 13 }}>
              <BookOpen size={14} /> منبع در کتاب
            </Link>
          ) : null}
        </div>
      </article>
    );
  };

  return (
    <div dir="rtl" style={{ display: "grid", gap: 16 }}>
      <div className="glass-panel" style={{ padding: 14, display: "grid", gap: 10 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <BookGradePicker
            value={bookId}
            onChange={(nextBookId) => {
              setBookId(nextBookId);
              setChapterNumber(null);
            }}
          />
          {chapterOptions.length ? (
            <label style={{ fontSize: 14 }}>
              فصل{" "}
              <select
                value={chapterNumber ?? ""}
                onChange={(event) => setChapterNumber(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">همهٔ فصل‌ها</option>
                {chapterOptions.map(([number, title]) => (
                  <option key={number} value={number}>
                    فصل {toPersianDigits(number)}{title ? ` — ${title}` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {FILTERS.map((f) => (
            <button key={f.key} type="button" className={filter === f.key ? "btn-primary" : "btn-ghost"} onClick={() => setFilter(f.key)}>
              {f.label}
              {f.key !== "all" && list.counts[f.key] !== undefined ? ` (${toPersianDigits(list.counts[f.key])})` : ""}
            </button>
          ))}
          <span aria-hidden style={{ opacity: 0.3 }}>|</span>
          {ERROR_TAG_FILTERS.map((f) => (
            <button key={f.key} type="button" className={errorTag === f.key ? "btn-primary" : "btn-ghost"} onClick={() => setErrorTag(f.key)}>
              {f.label}
            </button>
          ))}
          {hasScopeFilter ? (
            <button type="button" className="btn-ghost" onClick={() => { setBookId(null); setChapterNumber(null); setErrorTag("all"); }}>
              پاک‌کردن فیلترها
            </button>
          ) : null}
          <button type="button" className="btn-primary" onClick={() => void startPractice()}>
            <RotateCw size={14} /> تمرین دوباره
          </button>
        </div>
        {notice ? <span role="status" style={{ fontSize: 13 }}>{notice}</span> : null}
      </div>

      {practice ? (
        <section style={{ display: "grid", gap: 12 }}>
          <h3>تمرین اشتباهات</h3>
          {practice.length === 0 ? <div>سؤالی برای تمرین نیست.</div> : practice.map((item) => renderItem(item, true))}
        </section>
      ) : null}

      <section style={{ display: "grid", gap: 12 }}>
        <h3>
          بانک اشتباهات (
          {toPersianDigits(list.total)})
        </h3>
        {list.items.length === 0 ? (
          <div className="empty-state">
            <b>هنوز اشتباهی ثبت نشده است</b>
            <span>هر پاسخ اشتباه در آزمون، همین‌جا با توضیح و راهنما ذخیره می‌شود.</span>
          </div>
        ) : (
          list.items.map((item) => renderItem(item, false))
        )}
      </section>
    </div>
  );
}
