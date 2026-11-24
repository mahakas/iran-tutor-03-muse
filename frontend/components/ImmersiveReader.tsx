"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, ChevronLeft, ChevronRight, Layers, ListTree, MessageSquare, Sparkles } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import {
  findPdfPageIndex,
  parseCitation,
  phase5ErrorMessage,
  splitCitations,
  toPersianDigits,
  type ImmersiveOverview,
  type ImmersivePageDetail,
  type SourceFigure,
} from "@/lib/phase5";
import FigureThumb from "@/components/FigureThumb";

type ChatTurn = { role: "user" | "assistant"; content: string; sources?: Array<Record<string, unknown>> };

type Props = { bookId: number; initialPageIndex?: number };

const ACTIONS: Array<{ key: "ask" | "summarize" | "explain" | "flashcard"; label: string; icon: typeof Sparkles }> = [
  { key: "ask", label: "از معلم بپرس", icon: MessageSquare },
  { key: "summarize", label: "خلاصه کن", icon: Sparkles },
  { key: "flashcard", label: "تبدیل به فلش‌کارت", icon: Layers },
];

export default function ImmersiveReader({ bookId, initialPageIndex }: Props) {
  const { authFetch } = useAppContext();
  const initialPageBookRef = useRef<number | null>(null);
  const [overview, setOverview] = useState<ImmersiveOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(1);
  const [detail, setDetail] = useState<ImmersivePageDetail | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [selection, setSelection] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<"toc" | "figures">("toc");
  const [mobilePane, setMobilePane] = useState<"page" | "chat">("page");
  const contentRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      // Defer the reset one microtask: effects run after paint and microtasks run before
      // the next paint, so switching books still never paints stale content — the reset
      // is just not synchronous inside the effect (React 19 cascading-render rule).
      await Promise.resolve();
      if (cancelled) return;
      setOverview(null);
      setDetail(null);
      setImageUrl(null);
      setPageIndex(1);
      setError(null);
      const res = await authFetch(`/api/v1/immersive/books/${bookId}`);
      const payload = await res.json().catch(() => null);
      if (cancelled) return;
      if (!res.ok) {
        setError(phase5ErrorMessage(payload, "کتاب در دسترس نیست."));
        return;
      }
      const nextOverview = payload as ImmersiveOverview;
      setOverview(nextOverview);
      // Deep link: apply initialPageIndex only once, on overview load, when it
      // names a real page; otherwise fall back to the first page. Later user
      // navigation is never overridden (guarded by the ref).
      if (initialPageBookRef.current !== bookId) {
        initialPageBookRef.current = bookId;
        const initial =
          initialPageIndex !== undefined &&
          nextOverview.pages.some((page) => page.pdf_page_index === initialPageIndex)
            ? initialPageIndex
            : nextOverview.pages[0]?.pdf_page_index ?? 1;
        // The API's pdf_page_index is one-based and may not start at 1 when
        // only a selected range of the original PDF was ingested.
        setPageIndex(initial);
      } else {
        setPageIndex(nextOverview.pages[0]?.pdf_page_index ?? 1);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch, bookId, initialPageIndex]);

  // Load page details and the page image (authenticated fetch -> object URL).
  useEffect(() => {
    if (!overview) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    void (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setDetail(null);
      setImageUrl(null);
      const [detailRes, imageRes] = await Promise.all([
        authFetch(`/api/v1/immersive/books/${bookId}/pages/${pageIndex}`),
        authFetch(`/api/v1/immersive/books/${bookId}/pages/${pageIndex}/image`),
      ]);
      if (cancelled) return;
      if (detailRes.ok) setDetail((await detailRes.json()) as ImmersivePageDetail);
      else setDetail(null);
      if (imageRes.ok) {
        objectUrl = URL.createObjectURL(await imageRes.blob());
        if (!cancelled) setImageUrl(objectUrl);
      } else {
        setImageUrl(null);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [authFetch, bookId, overview, pageIndex]);

  const pages = useMemo(() => overview?.pages ?? [], [overview]);
  const pageCount = pages.length;
  const pagePosition = pages.findIndex((page) => page.pdf_page_index === pageIndex);

  const goToPage = useCallback(
    (index: number) => {
      if (!pages.some((page) => page.pdf_page_index === index)) return;
      setPageIndex(index);
      setSelection("");
      setNotice(null);
      contentRef.current?.scrollTo({ top: 0 });
    },
    [pages],
  );

  const navigateToCitation = useCallback(
    (raw: string) => {
      const parsed = parseCitation(raw);
      if (!parsed) return;
      const target = findPdfPageIndex(pages, parsed.printedPage, parsed.chapter);
      if (target === null) {
        setNotice(`صفحهٔ ${toPersianDigits(parsed.printedPage)} این کتاب در دسترس نیست.`);
        return;
      }
      goToPage(target);
    },
    [goToPage, pages],
  );

  const captureSelection = () => {
    const text = typeof window !== "undefined" ? window.getSelection()?.toString().trim() ?? "" : "";
    setSelection(text.slice(0, 6000));
  };

  const askTutor = useCallback(
    async (query: string) => {
      if (!overview || !query.trim()) return;
      setBusy(true);
      setTurns((prev) => [...prev, { role: "user", content: query }]);
      try {
        const res = await authFetch("/api/v1/tutor/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query,
            book_id: bookId,
            grade_number: overview.grade_number ?? 1,
            major_code: overview.major_code,
            mode: "tutor",
            top_k: 5,
          }),
        });
        const payload = await res.json().catch(() => null);
        if (!res.ok) {
          setTurns((prev) => [...prev, { role: "assistant", content: phase5ErrorMessage(payload, "پاسخ دریافت نشد.") }]);
          return;
        }
        setTurns((prev) => [
          ...prev,
          {
            role: "assistant",
            content: String((payload as { answer?: string }).answer ?? ""),
            sources: ((payload as { sources?: Array<Record<string, unknown>> }).sources ?? []) as Array<
              Record<string, unknown>
            >,
          },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [authFetch, bookId, overview],
  );

  const runAssist = useCallback(
    async (action: "summarize" | "explain") => {
      setBusy(true);
      try {
        const res = await authFetch(`/api/v1/immersive/books/${bookId}/assist`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, pdf_page_index: pageIndex, selection: selection || null }),
        });
        const payload = await res.json().catch(() => null);
        if (!res.ok) {
          setTurns((prev) => [...prev, { role: "assistant", content: phase5ErrorMessage(payload, "خطا در پردازش.") }]);
          return;
        }
        const data = payload as { answer: string; citation: string };
        setTurns((prev) => [
          ...prev,
          { role: "assistant", content: `${data.answer}\n\nمنبع: «${data.citation}»` },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [authFetch, bookId, pageIndex, selection],
  );

  const makeFlashcards = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const res = await authFetch("/api/v1/flashcards/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "book",
          book_id: bookId,
          page_start: pageIndex,
          page_end: pageIndex,
          count: 5,
          new_deck_title: `${overview?.title ?? "کتاب"} - صفحه ${toPersianDigits(detail?.printed_page_number ?? pageIndex)}`,
        }),
      });
      const payload = await res.json().catch(() => null);
      setNotice(
        res.ok
          ? "فلش‌کارت‌های این صفحه ساخته شد و در فلش‌کارت‌ها ذخیره شد."
          : phase5ErrorMessage(payload, "ساخت فلش‌کارت انجام نشد."),
      );
    } finally {
      setBusy(false);
    }
  }, [authFetch, bookId, detail, overview, pageIndex]);

  const onAction = (key: (typeof ACTIONS)[number]["key"]) => {
    if (key === "ask") {
      const query = selection ? `دربارهٔ این متن توضیح بده:\n${selection}` : `توضیح صفحهٔ ${toPersianDigits(detail?.printed_page_number ?? pageIndex + 1)} را بده.`;
      void askTutor(query);
    } else if (key === "summarize") void runAssist("summarize");
    else void makeFlashcards();
  };

  const figureList: SourceFigure[] = detail?.figures ?? [];
  const currentPrinted = detail?.printed_page_number ?? pages[pagePosition]?.printed_page_number ?? pageIndex;
  const chapterList = useMemo(() => overview?.chapters ?? [], [overview]);

  if (error) {
    return <div className="glass-panel" style={{ padding: 24 }}>{error}</div>;
  }
  if (!overview) {
    return <div className="glass-panel" style={{ padding: 24 }}>در حال بارگذاری کتاب…</div>;
  }

  return (
    <div dir="rtl" className="immersive-layout" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr)", gap: 16, alignItems: "start" }}>
      {/* Mobile-only pane switcher (hidden on tablet and desktop by CSS) */}
      <div className="immersive-tabs" role="tablist" aria-label="نمای مطالعه" style={{ display: "none", gridColumn: "1 / -1" }}>
        <button type="button" role="tab" aria-selected={mobilePane === "page"} onClick={() => setMobilePane("page")}>
          صفحه کتاب
        </button>
        <button type="button" role="tab" aria-selected={mobilePane === "chat"} onClick={() => setMobilePane("chat")}>
          گفت‌وگو با معلم
        </button>
      </div>
      {/* Viewer side (right in RTL): TOC, page image, page text, figures */}
      <section className="glass-panel immersive-pane" data-pane="page" data-active={mobilePane === "page" ? "true" : "false"} style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
        <header style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "space-between", flexWrap: "wrap" }}>
          <strong>{overview.title}</strong>
          <span style={{ fontSize: 13, opacity: 0.8 }}>
            صفحهٔ {toPersianDigits(currentPrinted)} · {toPersianDigits(pagePosition + 1)} / {toPersianDigits(pageCount)} (فایل)
          </span>
        </header>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              const next = pages[pagePosition + 1];
              if (next) goToPage(next.pdf_page_index);
            }}
            disabled={pagePosition < 0 || pagePosition >= pageCount - 1}
            aria-label="صفحهٔ بعد"
          >
            <ChevronRight size={16} /> بعدی
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              const previous = pages[pagePosition - 1];
              if (previous) goToPage(previous.pdf_page_index);
            }}
            disabled={pagePosition <= 0}
            aria-label="صفحهٔ قبل"
          >
            قبلی <ChevronLeft size={16} />
          </button>
          {notice ? <span role="status" style={{ fontSize: 13 }}>{notice}</span> : null}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "180px minmax(0,1fr)", gap: 12 }}>
          <aside style={{ maxHeight: 620, overflowY: "auto" }}>
            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              <button type="button" className={tab === "toc" ? "btn-primary" : "btn-ghost"} onClick={() => setTab("toc")}>
                <ListTree size={14} /> فهرست
              </button>
              <button type="button" className={tab === "figures" ? "btn-primary" : "btn-ghost"} onClick={() => setTab("figures")}>
                شکل‌ها{figureList.length > 0 ? ` (${toPersianDigits(figureList.length)})` : ""}
              </button>
            </div>
            {tab === "toc" ? (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
                {chapterList.map((chapter) => (
                  <li key={chapter.chapter_number}>
                    <button type="button" className="btn-ghost" style={{ width: "100%", justifyContent: "flex-start" }} onClick={() => goToPage(chapter.page_start)}>
                      فصل {toPersianDigits(chapter.chapter_number)}: {chapter.chapter_title}
                      <span style={{ fontSize: 11, opacity: 0.7 }}>
                        {" "}
                        (ص {toPersianDigits(chapter.printed_start ?? "-")})
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
                {figureList.length === 0 ? <li style={{ fontSize: 13 }}>شکلی برای این صفحه ثبت نشده است.</li> : null}
                {figureList.map((figure) => (
                  <li key={figure.id} style={{ fontSize: 13 }}>
                    <button type="button" className="btn-ghost" onClick={() => goToPage(figure.pdf_page_index)}>
                      {figure.figure_label ?? "شکل"}: {figure.caption ?? ""}
                    </button>
                    <FigureThumb bookId={bookId} figure={figure} />
                  </li>
                ))}
              </ul>
            )}
          </aside>
          <div style={{ minWidth: 0 }}>
            {imageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl} alt={`صفحهٔ ${currentPrinted ?? pageIndex + 1} کتاب`} style={{ width: "100%", borderRadius: 8, border: "1px solid rgba(0,0,0,0.1)" }} />
            ) : (
              <div style={{ padding: 16, fontSize: 13 }}>تصویر این صفحه در دسترس نیست.</div>
            )}
          </div>
        </div>
        {figureList.length > 0 && (
          <section aria-label="شکل‌های این صفحه" style={{ display: "grid", gap: 8 }}>
            <strong style={{ fontSize: 13 }}>شکل‌های این صفحه</strong>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8 }}>
              {figureList.map((figure) => (
                <FigureThumb key={figure.id} bookId={bookId} figure={figure} />
              ))}
            </div>
          </section>
        )}
        <div
          ref={contentRef}
          onMouseUp={captureSelection}
          onKeyUp={captureSelection}
          style={{ maxHeight: 360, overflowY: "auto", padding: 8, borderTop: "1px solid rgba(0,0,0,0.08)" }}
        >
          {detail ? <MathContent content={detail.markdown_content} /> : null}
        </div>
        {selection ? (
          <div style={{ fontSize: 12, opacity: 0.85 }}>متن انتخاب‌شده: «{selection.slice(0, 120)}»</div>
        ) : (
          <div style={{ fontSize: 12, opacity: 0.7 }}>برای کار روی بخشی از متن، آن را انتخاب کنید؛ در غیر این صورت کل صفحه استفاده می‌شود.</div>
        )}
      </section>

      {/* Chat side (left in RTL): grounded tutor */}
      <section className="glass-panel immersive-pane" data-pane="chat" data-active={mobilePane === "chat" ? "true" : "false"} style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {ACTIONS.map((action) => {
            const Icon = action.icon;
            return (
              <button key={action.key} type="button" className="btn-ghost" disabled={busy} onClick={() => onAction(action.key)}>
                <Icon size={14} /> {action.label}
              </button>
            );
          })}
          <button type="button" className="btn-ghost" disabled={busy} onClick={() => void runAssist("explain")}>
            <BookOpen size={14} /> توضیح بده
          </button>
        </div>
        <div style={{ display: "grid", gap: 10, maxHeight: 520, overflowY: "auto" }}>
          {turns.length === 0 ? <div style={{ fontSize: 13, opacity: 0.8 }}>سؤال خود را دربارهٔ این کتاب بپرسید. پاسخ‌ها فقط بر اساس متن کتاب است.</div> : null}
          {turns.map((turn, idx) => (
            <div key={idx} style={{ padding: 10, borderRadius: 10, background: turn.role === "user" ? "rgba(0,0,0,0.04)" : "rgba(0,120,255,0.06)" }}>
              <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>{turn.role === "user" ? "شما" : "معلم"}</div>
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.9 }}>
                {splitCitations(turn.content).map((part, i) =>
                  part.kind === "cite" ? (
                    <button
                      key={i}
                      type="button"
                      onClick={() => navigateToCitation(part.value)}
                      style={{ color: "#1d4ed8", textDecoration: "underline", background: "none", border: 0, padding: 0, cursor: "pointer", font: "inherit" }}
                      title="رفتن به صفحه در نمایشگر"
                    >
                      «{part.value}»
                    </button>
                  ) : (
                    <span key={i}>{part.value}</span>
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const value = question.trim();
            if (!value) return;
            setQuestion("");
            void askTutor(value);
          }}
          style={{ display: "flex", gap: 8 }}
        >
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="سؤال خود را بنویسید…"
            aria-label="سؤال از معلم"
            style={{ flex: 1, minWidth: 0 }}
          />
          <button type="submit" className="btn-primary" disabled={busy || !question.trim()}>
            ارسال
          </button>
        </form>
      </section>
    </div>
  );
}
