"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  FileSpreadsheet,
  Layers,
  Lightbulb,
  Maximize,
  Minimize,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  Shuffle,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { buildUserAuthHeaders, useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import { fetchMyCapabilities } from "@/lib/capabilities";
import {
  CARD_REPORT_REASONS,
  COUNT_PRESETS,
  DIFFICULTY_OPTIONS,
  MAX_FOCUS_PROMPT_CHARS,
  RATING_BUTTONS,
  flashcardErrorMessage,
  type DueQueue,
  type ExplainPayload,
  type Flashcard,
  type FlashcardDeck,
  type FlashcardDeckDetail,
  type StudyResult,
  type StudySessionPayload,
} from "@/lib/flashcards";
import type { BookOption } from "@/lib/types";

type View = "decks" | "deck" | "study";
type GradeRow = { number: number; title: string; has_major: boolean };
type MajorRow = { code: string; title: string };
type ExamRow = { id: string; title: string; status: string; book_title: string | null };

function todayLabel(): string {
  return new Date().toLocaleDateString("fa-IR");
}

function clampPosition(value: number, length: number): number {
  if (length <= 0) return 0;
  return Math.max(0, Math.min(value, length - 1));
}

/** Honest display of the deck's most recent real SM-2 review, in the Persian calendar. */
function formatLastReview(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("fa-IR");
}

type DeckFilter = "all" | "due" | "mastered" | "new";

const DECK_FILTERS: ReadonlyArray<{ key: DeckFilter; label: string }> = [
  { key: "all", label: "همه" },
  { key: "due", label: "برای مرور امروز" },
  { key: "new", label: "تازه (بدون مرور)" },
  { key: "mastered", label: "تسلط‌یافته" },
];

async function downloadBlobResponse(response: Response, filename: string) {
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function FlashcardsWorkspace() {
  const { authFetch, getActiveToken } = useAppContext();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("decks");
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [activeDeck, setActiveDeck] = useState<FlashcardDeckDetail | null>(null);
  const [dueCount, setDueCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newDeckTitle, setNewDeckTitle] = useState("");
  const [generateOpen, setGenerateOpen] = useState(false);
  const [libraryDecks, setLibraryDecks] = useState<FlashcardDeck[]>([]);
  // Library controls: client-side search + study-status filter over the real API list.
  const [deckSearch, setDeckSearch] = useState("");
  const [deckFilter, setDeckFilter] = useState<DeckFilter>("all");
  const [detailsCard, setDetailsCard] = useState<Flashcard | null>(null);
  // NotebookLM-style: the most recent unfinished study run, offered for resume.
  const [resume, setResume] = useState<StudySessionPayload | null>(null);
  const [activeSession, setActiveSession] = useState<StudySessionPayload | null>(null);

  // Legacy global due-queue study (SM-2 four-rating flow) — kept intact.
  const [queue, setQueue] = useState<Flashcard[]>([]);
  const [studyTotal, setStudyTotal] = useState(0);
  const [flippedLegacy, setFlippedLegacy] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);

  const loadDecks = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/decks");
    if (response.status === 403) {
      setEnabled(false);
      return;
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(flashcardErrorMessage(payload, "بارگذاری دسته‌ها ناموفق بود."));
    setDecks(payload as FlashcardDeck[]);
    setDueCount((payload as FlashcardDeck[]).reduce((sum, deck) => sum + deck.stats.due, 0));
  }, [authFetch]);

  const loadLibrary = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/library");
    if (response.ok) setLibraryDecks((await response.json()) as FlashcardDeck[]);
  }, [authFetch]);

  const loadResume = useCallback(async () => {
    const response = await authFetch("/api/v1/flashcards/study-sessions/active");
    if (!response.ok) return;
    const payload = (await response.json().catch(() => null)) as { session: StudySessionPayload | null } | null;
    setResume(payload?.session ?? null);
  }, [authFetch]);

  // Gate the whole page on the capability flag; the API also returns 403 when disabled.
  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const keys = await fetchMyCapabilities(buildUserAuthHeaders(getActiveToken()));
      if (cancelled) return;
      if (keys !== null && !keys.has("flashcards")) {
        setEnabled(false);
        return;
      }
      setEnabled(true);
      setLoading(true);
      try {
        await Promise.all([loadDecks(), loadLibrary(), loadResume()]);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "خطا در بارگذاری.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, [getActiveToken, loadDecks, loadLibrary, loadResume]);

  async function openDeck(deckId: number) {
    setError("");
    setNotice("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deckId}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "دسته یافت نشد."));
      return;
    }
    setActiveDeck(payload as FlashcardDeckDetail);
    setView("deck");
  }

  async function createStudySession(deckId: number, mode: "full" | "smart", cardIds?: number[]) {
    setError("");
    setNotice("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deckId}/study-sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cardIds ? { mode, card_ids: cardIds } : { mode }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setNotice(flashcardErrorMessage(payload, "شروع جلسهٔ مطالعه ناموفق بود."));
      return;
    }
    setActiveSession(payload as StudySessionPayload);
    setResume(payload as StudySessionPayload);
    setView("study");
  }

  async function resumeSession(stored: StudySessionPayload) {
    setError("");
    setNotice("");
    const response = await authFetch(`/api/v1/flashcards/study-sessions/${stored.id}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      // The session may have been finished on another device; refresh and continue.
      setResume(null);
      await loadDecks();
      setNotice("جلسهٔ ذخیره‌شده دیگر معتبر نیست؛ می‌توانید مطالعه را تازه شروع کنید.");
      return;
    }
    setActiveSession(payload as StudySessionPayload);
    setView("study");
  }

  function exitStudy() {
    setActiveSession(null);
    setView("decks");
    void (async () => {
      try {
        await Promise.all([loadDecks(), loadResume()]);
        if (activeDeck) await openDeck(activeDeck.id);
      } catch {
        /* keep the user on the decks view regardless */
      }
    })();
  }

  async function startLegacyStudy(deckId: number | null) {
    setError("");
    setNotice("");
    const response = await authFetch("/api/v1/flashcards/due?limit=200");
    const payload = (await response.json().catch(() => null)) as DueQueue | null;
    if (!response.ok || !payload) {
      setError("دریافت کارت‌های امروز ناموفق بود.");
      return;
    }
    const cards = deckId === null ? payload.cards : payload.cards.filter((card) => card.deck_id === deckId);
    if (!cards.length) {
      setNotice("برای امروز کارتی برای مرور وجود ندارد. آفرین!");
      return;
    }
    setQueue(cards);
    setStudyTotal(cards.length);
    setFlippedLegacy(false);
    setView("study");
  }

  async function rate(rating: 1 | 2 | 3 | 4) {
    const card = queue[0];
    if (!card || reviewBusy) return;
    setReviewBusy(true);
    setError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/${card.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(flashcardErrorMessage(payload, "ثبت مرور ناموفق بود."));
        return;
      }
      // Rating 1 (forgot) brings the card back later in this session.
      setQueue((prev) => {
        const [head, ...rest] = prev;
        return rating === 1 && head ? [...rest, head] : rest;
      });
      setFlippedLegacy(false);
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setReviewBusy(false);
    }
  }

  async function downloadAnki(deck: FlashcardDeck) {
    setError("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}/export/anki`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(flashcardErrorMessage(payload, "خروجی Anki ساخته نشد."));
      return;
    }
    await downloadBlobResponse(response, `darsyar-${deck.id}.apkg`);
  }

  async function downloadCsv(deck: FlashcardDeck) {
    setError("");
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}/export/csv`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(flashcardErrorMessage(payload, "دانلود CSV ناموفق بود."));
      return;
    }
    await downloadBlobResponse(response, `darsyar-deck-${deck.id}-flashcards.csv`);
  }

  async function createDeck() {
    const title = newDeckTitle.trim();
    if (!title) return;
    const response = await authFetch("/api/v1/flashcards/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "ساخت دسته ناموفق بود."));
      return;
    }
    setNewDeckTitle("");
    await loadDecks();
    await openDeck((payload as FlashcardDeck).id);
  }

  async function deleteDeck(deck: FlashcardDeck) {
    if (!window.confirm(`دستهٔ «${deck.title}» و همهٔ کارت‌هایش حذف شود؟`)) return;
    const response = await authFetch(`/api/v1/flashcards/decks/${deck.id}`, { method: "DELETE" });
    if (!response.ok) {
      setError("حذف دسته ناموفق بود.");
      return;
    }
    setActiveDeck(null);
    setView("decks");
    if (resume?.deck_id === deck.id) setResume(null);
    await loadDecks();
  }

  async function deleteCard(card: Flashcard) {
    if (!window.confirm("این کارت حذف شود؟ آمار مرور آن هم پاک می‌شود.")) return;
    const response = await authFetch(`/api/v1/flashcards/cards/${card.id}`, { method: "DELETE" });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      setError(flashcardErrorMessage(payload, "حذف کارت ناموفق بود."));
      return;
    }
    await openDeck(card.deck_id);
    await loadDecks();
  }

  async function copyLibraryDeck(deck: FlashcardDeck) {
    const response = await authFetch(`/api/v1/flashcards/library/${deck.id}/copy`, { method: "POST" });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(flashcardErrorMessage(payload, "افزودن دسته ناموفق بود."));
      return;
    }
    setNotice("دسته به فلش‌کارت‌های شما اضافه شد.");
    await loadDecks();
  }

  const currentLegacyCard = queue[0] ?? null;
  const legacyDone = studyTotal - queue.length;
  const legacyPercent = studyTotal ? Math.round((legacyDone / studyTotal) * 100) : 0;

  const deckCards = useMemo(() => activeDeck?.cards ?? [], [activeDeck]);

  // Library search/filter runs on the real API data only — never invents rows.
  const filteredDecks = useMemo(() => {
    const needle = deckSearch.trim().toLowerCase();
    return decks.filter((deck) => {
      if (needle && !deck.title.toLowerCase().includes(needle)) return false;
      if (deckFilter === "due") return deck.stats.due > 0;
      if (deckFilter === "new") return deck.stats.new > 0;
      if (deckFilter === "mastered") return deck.stats.mastered > 0;
      return true;
    });
  }, [decks, deckSearch, deckFilter]);

  if (enabled === false) {
    return (
      <section className="fc-panel fc-disabled" dir="rtl">
        <X size={22} />
        <h2>این قابلیت در حال حاضر غیرفعال است</h2>
        <p>فلش‌کارت‌ها توسط مدیر درسیار غیرفعال شده‌اند. بعداً دوباره سر بزنید.</p>
      </section>
    );
  }

  return (
    <div className="fc-root" dir="rtl">
      {error && <div className="inline-error fc-alert">{error}</div>}
      {notice && <div className="fc-notice">{notice}</div>}

      {view === "decks" && (
        <>
          <header className="fc-toolbar">
            <div>
              <h2>دسته‌های فلش‌کارت</h2>
              <p className="fc-muted">مرور امروز: {todayLabel()}</p>
            </div>
            <div className="fc-toolbar-actions">
              <button
                type="button"
                className="fc-btn"
                onClick={() => void startLegacyStudy(null)}
                disabled={loading}
              >
                <RotateCw size={16} /> مرور امروز (همهٔ دسته‌ها)
                {dueCount > 0 && <span className="fc-due-badge">{dueCount}</span>}
              </button>
              <button type="button" className="fc-btn primary" onClick={() => setGenerateOpen(true)}>
                <Sparkles size={16} /> ساخت با هوش مصنوعی
              </button>
            </div>
          </header>

          {resume && view === "decks" && (
            <div className="fc-resume-banner">
              <Layers size={18} />
              <div className="fc-resume-body">
                <b>یک جلسهٔ مطالعهٔ نیمه‌کاره دارید</b>
                <span className="fc-muted fc-small">
                  {decks.find((deck) => deck.id === resume.deck_id)?.title ?? "دستهٔ حذف‌شده"} — کارت{" "}
                  {resume.position + 1} از {resume.total_cards} · {resume.summary.got} بلد بودم ·{" "}
                  {resume.summary.missed} بلد نبودم
                </span>
              </div>
              <button type="button" className="fc-btn primary small" onClick={() => void resumeSession(resume)}>
                <Play size={14} /> ادامهٔ مطالعه
              </button>
              <button
                type="button"
                className="fc-icon-btn"
                aria-label="نادیدن جلسهٔ نیمه‌کاره"
                onClick={() => setResume(null)}
              >
                <X size={14} />
              </button>
            </div>
          )}

          <div className="fc-create-row">
            <input
              className="fc-input"
              value={newDeckTitle}
              onChange={(event) => setNewDeckTitle(event.target.value)}
              placeholder="نام دستهٔ تازه…"
              maxLength={255}
            />
            <button type="button" className="fc-btn" onClick={() => void createDeck()} disabled={!newDeckTitle.trim()}>
              <Plus size={16} /> دستهٔ جدید
            </button>
          </div>

          {decks.length > 0 && (
            <div className="fc-library-controls" role="search">
              <input
                className="fc-input"
                value={deckSearch}
                onChange={(event) => setDeckSearch(event.target.value)}
                placeholder="جست‌وجوی دسته…"
                aria-label="جست‌وجوی دسته"
                maxLength={100}
              />
              <div className="fc-choice-row" role="group" aria-label="فیلتر وضعیت مطالعه">
                {DECK_FILTERS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    className={`fc-choice small ${deckFilter === option.key ? "active" : ""}`}
                    aria-pressed={deckFilter === option.key}
                    onClick={() => setDeckFilter(option.key)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {loading && <p className="fc-muted">در حال بارگذاری…</p>}
          {!loading && decks.length === 0 && (
            <div className="fc-empty">
              هنوز دسته‌ای ندارید. با «ساخت با هوش مصنوعی» از فصل کتاب یا اشتباهات آزمون کارت بسازید، یا از
              گفت‌وگوی معلم دکمهٔ «تبدیل به فلش‌کارت» را بزنید.
            </div>
          )}
          {!loading && decks.length > 0 && filteredDecks.length === 0 && (
            <div className="fc-empty">دسته‌ای با این جست‌وجو یا فیلتر پیدا نشد.</div>
          )}

          <div className="fc-deck-grid">
            {filteredDecks.map((deck) => (
              <article key={deck.id} className="fc-deck-card">
                <div className="fc-deck-head">
                  <h3>{deck.title}</h3>
                  {deck.stats.due > 0 && <span className="fc-due-badge">مرور: {deck.stats.due}</span>}
                </div>
                <div className="fc-muted fc-small">
                  {deck.stats.total} کارت · {deck.stats.mastered} تسلط‌یافته
                  {formatLastReview(deck.stats.last_review) && <> · آخرین مرور: {formatLastReview(deck.stats.last_review)}</>}
                </div>
                <div className="fc-progress" aria-label="پیشرفت دسته">
                  <span style={{ width: `${deck.stats.progress_percent}%` }} />
                </div>
                <div className="fc-deck-actions">
                  <button type="button" className="fc-btn small" onClick={() => void openDeck(deck.id)}>
                    <Eye size={14} /> مشاهده
                  </button>
                  <button
                    type="button"
                    className="fc-btn small primary"
                    onClick={() => void createStudySession(deck.id, "full")}
                    disabled={deck.stats.total === 0}
                  >
                    <Play size={14} /> مطالعهٔ کامل
                  </button>
                  <button
                    type="button"
                    className="fc-btn small"
                    onClick={() => void createStudySession(deck.id, "smart")}
                    disabled={deck.stats.due === 0}
                    title="فقط کارت‌هایی که موعد مرورشان رسیده است"
                  >
                    <RotateCw size={14} /> مرور هوشمند
                  </button>
                </div>
              </article>
            ))}
          </div>

          {libraryDecks.length > 0 && (
            <section className="fc-library">
              <h3>کتابخانهٔ عمومی (تأییدشده)</h3>
              <div className="fc-deck-grid">
                {libraryDecks.map((deck) => (
                  <article key={deck.id} className="fc-deck-card">
                    <h3>{deck.title}</h3>
                    <div className="fc-muted fc-small">{deck.stats.total} کارت</div>
                    <button type="button" className="fc-btn small" onClick={() => void copyLibraryDeck(deck)}>
                      <Plus size={14} /> افزودن به من
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {view === "deck" && activeDeck && (
        <>
          <header className="fc-toolbar">
            <div>
              <button type="button" className="fc-link" onClick={() => setView("decks")}>
                ← همهٔ دسته‌ها
              </button>
              <h2>{activeDeck.title}</h2>
              <p className="fc-muted fc-small">
                {activeDeck.stats.total} کارت · {activeDeck.stats.due} برای مرور هوشمند
                {formatLastReview(activeDeck.stats.last_review) && <> · آخرین مرور: {formatLastReview(activeDeck.stats.last_review)}</>}
              </p>
              {(activeDeck.chapter_number !== null || activeDeck.page_start !== null) && (
                <p className="fc-muted fc-small">
                  منبع: {activeDeck.book_id !== null ? "کتاب رسمی" : "بدون کتاب"}
                  {activeDeck.chapter_number !== null && <> · فصل {activeDeck.chapter_number.toLocaleString("fa-IR")}</>}
                  {activeDeck.page_start !== null && (
                    <>
                      {" · "}صفحهٔ {activeDeck.page_start.toLocaleString("fa-IR")}
                      {activeDeck.page_end !== null && activeDeck.page_end !== activeDeck.page_start && (
                        <> تا {activeDeck.page_end.toLocaleString("fa-IR")}</>
                      )}
                    </>
                  )}
                </p>
              )}
            </div>
            <div className="fc-toolbar-actions">
              <button
                type="button"
                className="fc-btn primary"
                onClick={() => void createStudySession(activeDeck.id, "full")}
                disabled={activeDeck.cards.length === 0}
              >
                <Play size={16} /> مطالعهٔ کامل
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void createStudySession(activeDeck.id, "smart")}
                disabled={activeDeck.stats.due === 0}
              >
                <RotateCw size={16} /> مرور هوشمند
              </button>
              {resume?.deck_id === activeDeck.id && (
                <button type="button" className="fc-btn" onClick={() => void resumeSession(resume)}>
                  <Layers size={16} /> ادامهٔ جلسهٔ نیمه‌کاره
                </button>
              )}
              <button
                type="button"
                className="fc-btn"
                onClick={() => void downloadCsv(activeDeck)}
                disabled={activeDeck.cards.length === 0}
              >
                <FileSpreadsheet size={16} /> دانلود CSV
              </button>
              <button
                type="button"
                className="fc-btn"
                onClick={() => void downloadAnki(activeDeck)}
                disabled={activeDeck.cards.length === 0}
              >
                <Download size={16} /> خروجی Anki
              </button>
              <button type="button" className="fc-btn danger" onClick={() => void deleteDeck(activeDeck)}>
                <Trash2 size={16} /> حذف دسته
              </button>
            </div>
          </header>
          <div className="fc-progress wide">
            <span style={{ width: `${activeDeck.stats.progress_percent}%` }} />
          </div>
          {deckCards.length === 0 && (
            <div className="empty-state">
              <b>این دسته هنوز کارتی ندارد</b>
              <span>کارت تازه بسازید یا از یک فصل کتاب کارت تولید کنید.</span>
            </div>
          )}
          <ul className="fc-card-list">
            {deckCards.map((card) => (
              <li key={card.id} className="fc-card-row">
                <div className="fc-card-row-body">
                  <MathContent content={card.front_md} />
                  <div className="fc-back-preview">
                    <MathContent content={card.back_md} />
                  </div>
                  {card.citations.map((cite, index) => (
                    <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                      <BookOpen size={12} /> {cite.citation}
                    </span>
                  ))}
                </div>
                <div className="fc-card-row-actions">
                  <button
                    type="button"
                    className="fc-icon-btn"
                    aria-label="جزئیات کارت"
                    title="جزئیات، ویرایش و گزارش ایراد"
                    onClick={() => setDetailsCard(card)}
                  >
                    <Eye size={15} />
                  </button>
                  <button
                    type="button"
                    className="fc-icon-btn"
                    aria-label="حذف کارت"
                    onClick={() => void deleteCard(card)}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {view === "study" && !activeSession && (
        <LegacyStudyView
          cards={queue}
          total={studyTotal}
          done={legacyDone}
          percent={legacyPercent}
          flipped={flippedLegacy}
          setFlipped={setFlippedLegacy}
          reviewBusy={reviewBusy}
          onRate={(rating) => void rate(rating)}
          onBack={() => {
            setQueue([]);
            setView("decks");
          }}
        />
      )}

      {view === "study" && activeSession && (
        <SessionStudyArena
          authFetch={authFetch}
          initialSession={activeSession}
          deckTitle={decks.find((deck) => deck.id === activeSession.deck_id)?.title ?? "دستهٔ فلش‌کارت"}
          onExit={exitStudy}
        />
      )}

      {generateOpen && (
        <GenerateModal
          decks={decks}
          onClose={() => setGenerateOpen(false)}
          onGenerated={async (deckId, message) => {
            setGenerateOpen(false);
            setNotice(message);
            await loadDecks();
            await openDeck(deckId);
          }}
          authFetch={authFetch}
        />
      )}

      {detailsCard && activeDeck && (
        <CardDetailsDialog
          card={detailsCard}
          authFetch={authFetch}
          onClose={() => setDetailsCard(null)}
          onChanged={async () => {
            await openDeck(activeDeck.id);
            await loadDecks();
          }}
          onDeleted={async () => {
            setDetailsCard(null);
            await openDeck(activeDeck.id);
            await loadDecks();
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legacy global due-queue study (SM-2 four-rating flow) — preserved as-is.
// ---------------------------------------------------------------------------

type LegacyStudyViewProps = {
  cards: Flashcard[];
  total: number;
  done: number;
  percent: number;
  flipped: boolean;
  setFlipped: (value: boolean) => void;
  reviewBusy: boolean;
  onRate: (rating: 1 | 2 | 3 | 4) => void;
  onBack: () => void;
};

function LegacyStudyView({
  cards,
  total,
  done,
  percent,
  flipped,
  setFlipped,
  reviewBusy,
  onRate,
  onBack,
}: LegacyStudyViewProps) {
  const [hintOpen, setHintOpen] = useState(false);
  const card = cards[0] ?? null;
  return (
    <section className="fc-study">
      <header className="fc-toolbar">
        <button type="button" className="fc-link" onClick={onBack}>
          ← بازگشت
        </button>
        <span className="fc-muted">
          {done} از {total} · {percent}٪
        </span>
      </header>
      <div className="fc-progress wide">
        <span style={{ width: `${percent}%` }} />
      </div>

      {card ? (
        <>
          <button
            type="button"
            className={`fc-flip ${flipped ? "is-flipped" : ""}`}
            onClick={() => setFlipped(!flipped)}
            aria-pressed={flipped}
            aria-label={flipped ? "نمایش رو" : "نمایش پشت کارت"}
          >
            <div className="fc-flip-inner">
              <div className="fc-face fc-front">
                <MathContent content={card.front_md} />
              </div>
              <div className="fc-face fc-back">
                <MathContent content={card.back_md} />
                {card.citations.length > 0 && (
                  <div className="fc-cite-stack">
                    {card.citations.map((cite, index) => (
                      <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                        <BookOpen size={12} /> {cite.citation}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </button>

          <div className="fc-study-tools">
            {card.hint_md && (
              <button type="button" className="fc-btn small" onClick={() => setHintOpen((value) => !value)}>
                {hintOpen ? <EyeOff size={14} /> : <Lightbulb size={14} />}
                {hintOpen ? "پنهان کردن راهنما" : "نمایش راهنما"}
              </button>
            )}
            {hintOpen && card.hint_md && (
              <div className="fc-hint">
                <MathContent content={card.hint_md} />
              </div>
            )}
          </div>

          {flipped ? (
            <div className="fc-rating-row" role="group" aria-label="امتیاز مرور">
              {RATING_BUTTONS.map((item) => (
                <button
                  key={item.rating}
                  type="button"
                  className={`fc-rate ${item.tone}`}
                  disabled={reviewBusy}
                  onClick={() => onRate(item.rating)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : (
            <p className="fc-muted fc-center">برای دیدن پاسخ کارت را بزنید.</p>
          )}
        </>
      ) : (
        <div className="fc-empty">
          مرور امروز تمام شد. {total} کارت مرور شد.
          <div className="fc-deck-actions center">
            <button type="button" className="fc-btn" onClick={onBack}>
              بازگشت به دسته‌ها
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// NotebookLM-style study arena: one persistent session, flip, navigate,
// shuffle, fullscreen, got/missed, explain, results.
// ---------------------------------------------------------------------------

type SessionStudyArenaProps = {
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  initialSession: StudySessionPayload;
  deckTitle: string;
  onExit: () => void;
};

type ExplainState = {
  cardId: number | null;
  loading: boolean;
  payload: ExplainPayload | null;
  error: string;
};

const EXPLAIN_IDLE: ExplainState = { cardId: null, loading: false, payload: null, error: "" };

function SessionStudyArena({ authFetch, initialSession, deckTitle, onExit }: SessionStudyArenaProps) {
  const [session, setSession] = useState<StudySessionPayload>(initialSession);
  const [cards, setCards] = useState<Flashcard[]>(initialSession.cards ?? []);
  const [flipped, setFlipped] = useState(Boolean(initialSession.flipped));
  const [hintOpen, setHintOpen] = useState(false);
  const [answerBusy, setAnswerBusy] = useState(false);
  const [arenaError, setArenaError] = useState("");
  const [explain, setExplain] = useState<ExplainState>(EXPLAIN_IDLE);
  const [fsFallback, setFsFallback] = useState(false);
  const [fsActive, setFsActive] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const arenaRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const currentCard = cards[session.position] ?? null;
  const results = session.results ?? {};
  const cardResult: StudyResult | undefined = currentCard ? results[String(currentCard.id)] : undefined;
  const allAnswered = session.summary.answered >= session.summary.total && session.summary.total > 0;

  const fullscreenSupported =
    typeof document !== "undefined" &&
    typeof document.documentElement?.requestFullscreen === "function" &&
    document.fullscreenEnabled !== false;

  useEffect(() => {
    const onChange = () => setFsActive(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  useEffect(
    () => () => {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    },
    [],
  );

  async function persistProgress(position: number, flippedValue: boolean) {
    try {
      const response = await authFetch(
        `/api/v1/flashcards/study-sessions/${sessionRef.current.id}/progress`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ position, flipped: flippedValue }),
        },
      );
      if (!response.ok) return;
      const payload = (await response.json().catch(() => null)) as { session: StudySessionPayload } | null;
      if (payload?.session) {
        setSession((prev) => ({ ...prev, ...payload.session, cards: undefined }));
      }
    } catch {
      /* progress persistence is best-effort; the next action re-syncs */
    }
  }

  function goTo(nextPosition: number) {
    const target = clampPosition(nextPosition, cards.length);
    if (target === session.position) return;
    setSession((prev) => ({ ...prev, position: target }));
    setFlipped(false);
    setHintOpen(false);
    setExplain(EXPLAIN_IDLE);
    void persistProgress(target, false);
  }

  function toggleFlip() {
    if (!currentCard) return;
    const next = !flipped;
    setFlipped(next);
    void persistProgress(session.position, next);
  }

  async function answer(got: boolean) {
    if (!currentCard || answerBusy) return;
    if (results[String(currentCard.id)]) return; // idempotent guard; server enforces too
    setAnswerBusy(true);
    setArenaError("");
    try {
      const response = await authFetch(
        `/api/v1/flashcards/study-sessions/${session.id}/answer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ card_id: currentCard.id, got }),
        },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setArenaError(flashcardErrorMessage(payload, "ثبت نتیجه ناموفق بود."));
        return;
      }
      const data = payload as { session: StudySessionPayload };
      setSession((prev) => ({ ...prev, ...data.session, cards: undefined }));
      setFlipped(false);
      setHintOpen(false);
      setExplain(EXPLAIN_IDLE);
      void persistProgress(data.session.position, false);
    } catch {
      setArenaError("ارتباط با سرور برقرار نشد.");
    } finally {
      setAnswerBusy(false);
    }
  }

  async function shuffle() {
    setArenaError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/study-sessions/${session.id}/shuffle`, {
        method: "POST",
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setArenaError(flashcardErrorMessage(payload, "بر زدن کارت‌ها ناموفق بود."));
        return;
      }
      const fresh = payload as StudySessionPayload;
      setSession(fresh);
      setCards(fresh.cards ?? []);
      setFlipped(false);
      setHintOpen(false);
      setExplain(EXPLAIN_IDLE);
    } catch {
      setArenaError("ارتباط با سرور برقرار نشد.");
    }
  }

  async function startSession(mode: "full" | "smart" | "subset", cardIds?: number[]) {
    setArenaError("");
    try {
      const response = await authFetch(
        `/api/v1/flashcards/decks/${session.deck_id}/study-sessions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cardIds ? { mode, card_ids: cardIds } : { mode }),
        },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setArenaError(flashcardErrorMessage(payload, "شروع جلسهٔ تازه ناموفق بود."));
        return;
      }
      const fresh = payload as StudySessionPayload;
      setSession(fresh);
      setCards(fresh.cards ?? []);
      setFlipped(false);
      setHintOpen(false);
      setExplain(EXPLAIN_IDLE);
    } catch {
      setArenaError("ارتباط با سرور برقرار نشد.");
    }
  }

  function restart() {
    if (session.summary.answered === 0 || window.confirm("شروع مجدد؟ پیشرفت این جلسه پایان‌یافته در نظر گرفته می‌شود و مطالعه از ابتدا آغاز می‌شود.")) {
      if (session.mode === "subset") void startSession("subset", [...session.card_order]);
      else void startSession(session.mode);
    }
  }

  async function loadExplain() {
    if (!currentCard) return;
    setArenaError("");
    setExplain({ cardId: currentCard.id, loading: true, payload: null, error: "" });
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${currentCard.id}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setExplain({
          cardId: currentCard.id,
          loading: false,
          payload: null,
          error: flashcardErrorMessage(payload, "تولید توضیح ناموفق بود."),
        });
        return;
      }
      setExplain({ cardId: currentCard.id, loading: false, payload: payload as ExplainPayload, error: "" });
    } catch {
      setExplain({ cardId: currentCard.id, loading: false, payload: null, error: "ارتباط با سرور برقرار نشد." });
    }
  }

  async function deleteCurrentCard() {
    if (!currentCard || deleteBusy) return;
    if (!window.confirm("این کارت از دسته حذف شود؟ آمار مرور آن هم پاک می‌شود.")) return;
    setDeleteBusy(true);
    setArenaError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${currentCard.id}`, { method: "DELETE" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setArenaError(flashcardErrorMessage(payload, "حذف کارت ناموفق بود."));
        return;
      }
      const refreshed = await authFetch(`/api/v1/flashcards/study-sessions/${session.id}`);
      if (!refreshed.ok) {
        onExit();
        return;
      }
      const payload = (await refreshed.json().catch(() => null)) as StudySessionPayload | null;
      if (!payload || payload.card_order.length === 0) {
        onExit();
        return;
      }
      setSession(payload);
      setCards(payload.cards ?? []);
      setFlipped(false);
      setHintOpen(false);
      setExplain(EXPLAIN_IDLE);
    } catch {
      setArenaError("ارتباط با سرور برقرار نشد.");
    } finally {
      setDeleteBusy(false);
    }
  }

  function toggleFullscreen() {
    const element = arenaRef.current;
    if (!element) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    if (fullscreenSupported) {
      void element.requestFullscreen().catch(() => setFsFallback((value) => !value));
      return;
    }
    setFsFallback((value) => !value);
  }

  // Keyboard support: Space/Enter flip, ←/→ navigate (RTL), g/1 got, x/2 missed.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (allAnswered) return;
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        toggleFlip();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(sessionRef.current.position + 1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(sessionRef.current.position - 1);
      } else if (flipped && (event.key === "g" || event.key === "g".toUpperCase() || event.key === "۱")) {
        void answer(true);
      } else if (flipped && (event.key === "x" || event.key === "m" || event.key === "۲")) {
        void answer(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flipped, allAnswered, answerBusy, cards.length]);

  const total = session.summary.total;
  const answeredCount = session.summary.answered;
  const studyPercent = total ? Math.round((answeredCount / total) * 100) : 0;

  if (allAnswered) {
    return (
      <section ref={arenaRef} className={`fc-arena ${fsFallback && !fsActive ? "is-fs-fallback" : ""}`} dir="rtl">
        <ResultsScreen
          session={session}
          deckTitle={deckTitle}
          busy={answerBusy}
          onReplaySame={() => void startSession("subset", [...session.card_order])}
          onReplayAll={() => void startSession("full")}
          onReplayMissed={() =>
            void startSession(
              "subset",
              session.card_order.filter((cardId) => results[String(cardId)] === "missed"),
            )
          }
          onExit={onExit}
        />
      </section>
    );
  }

  return (
    <section
      ref={arenaRef}
      className={`fc-arena ${fsActive || fsFallback ? "is-fullscreen" : ""} ${fsFallback && !fsActive ? "is-fs-fallback" : ""}`}
      dir="rtl"
    >
      <header className="fc-arena-top">
        <div className="fc-arena-title">
          <button type="button" className="fc-link" onClick={onExit}>
            ← خروج از مطالعه
          </button>
          <span className="fc-arena-deck">{deckTitle}</span>
        </div>
        <div className="fc-arena-tools">
          <button type="button" className="fc-icon-btn" onClick={() => void shuffle()} title="بر زدن کارت‌ها (ترتیب ذخیره می‌شود)" aria-label="بر زدن کارت‌ها">
            <Shuffle size={16} />
          </button>
          <button type="button" className="fc-icon-btn" onClick={restart} title="شروع مجدد از ابتدا" aria-label="شروع مجدد">
            <RotateCcw size={16} />
          </button>
          <button
            type="button"
            className="fc-icon-btn"
            onClick={toggleFullscreen}
            title={fsActive || fsFallback ? "خروج از حالت تمام‌صفحه" : "حالت تمام‌صفحه"}
            aria-label={fsActive || fsFallback ? "خروج از حالت تمام‌صفحه" : "حالت تمام‌صفحه"}
          >
            {fsActive || fsFallback ? <Minimize size={16} /> : <Maximize size={16} />}
          </button>
        </div>
      </header>

      <div className="fc-arena-counter">
        <span>
          کارت {session.position + 1} از {total}
        </span>
        <span className="fc-arena-score">
          <span className="fc-chip got">
            <Check size={12} /> {session.summary.got}
          </span>
          <span className="fc-chip missed">
            <XCircle size={12} /> {session.summary.missed}
          </span>
        </span>
      </div>
      <div className="fc-progress wide" aria-label="پیشرفت مطالعه">
        <span style={{ width: `${studyPercent}%` }} />
      </div>

      {arenaError && <div className="inline-error fc-alert">{arenaError}</div>}

      {currentCard ? (
        <>
          <div className="fc-card-stage">
            <button
              type="button"
              className="fc-nav-btn"
              onClick={() => goTo(session.position - 1)}
              disabled={session.position === 0}
              aria-label="کارت قبلی"
            >
              <ChevronRight size={20} />
            </button>

            <div className="fc-flip fc-flip-lg" onClick={toggleFlip} role="button" tabIndex={0}
                 aria-pressed={flipped}
                 aria-label={flipped ? "نمایش رو کارت" : "نمایش پاسخ"}
                 onKeyDown={(event) => {
                   if (event.key === "Enter" || event.key === " ") {
                     event.preventDefault();
                     toggleFlip();
                   }
                 }}>
              <div className={`fc-flip-inner ${flipped ? "is-flipped" : ""}`}>
                <div className="fc-face fc-front">
                  <span className="fc-face-label">سؤال</span>
                  <div className="fc-face-content">
                    <MathContent content={currentCard.front_md} />
                  </div>
                  {currentCard.hint_md && !flipped && (
                    <span className="fc-face-hint-toggle">
                      <Lightbulb size={13} /> راهنما زیر کارت است
                    </span>
                  )}
                  <span className="fc-face-flip-hint">برای دیدن پاسخ کلیک کنید</span>
                </div>
                <div className="fc-face fc-back">
                  <span className="fc-face-label">پاسخ</span>
                  <div className="fc-face-content">
                    <MathContent content={currentCard.back_md} />
                  </div>
                  {currentCard.citations.length > 0 && (
                    <div className="fc-cite-stack">
                      {currentCard.citations.map((cite, index) => (
                        <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                          <BookOpen size={12} /> {cite.citation}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <button
              type="button"
              className="fc-nav-btn"
              onClick={() => goTo(session.position + 1)}
              disabled={session.position >= cards.length - 1}
              aria-label="کارت بعدی"
            >
              <ChevronLeft size={20} />
            </button>
          </div>

          <div className="fc-mobile-nav">
            <button
              type="button"
              className="fc-btn small"
              onClick={() => goTo(session.position - 1)}
              disabled={session.position === 0}
            >
              <ChevronRight size={14} /> قبلی
            </button>
            <button
              type="button"
              className="fc-btn small"
              onClick={() => goTo(session.position + 1)}
              disabled={session.position >= cards.length - 1}
            >
              بعدی <ChevronLeft size={14} />
            </button>
          </div>

          <div className="fc-arena-subtools">
            {currentCard.hint_md && (
              <button type="button" className="fc-btn small" onClick={() => setHintOpen((value) => !value)}>
                {hintOpen ? <EyeOff size={14} /> : <Lightbulb size={14} />}
                {hintOpen ? "پنهان کردن راهنما" : "نمایش راهنما"}
              </button>
            )}
            {flipped && (
              <button
                type="button"
                className="fc-btn small"
                onClick={() => void loadExplain()}
                disabled={explain.loading || explain.cardId === currentCard.id}
              >
                <Sparkles size={14} />
                {explain.loading ? "در حال تولید توضیح…" : "توضیح بیشتر"}
              </button>
            )}
            <button
              type="button"
              className="fc-btn small danger"
              onClick={() => void deleteCurrentCard()}
              disabled={deleteBusy}
            >
              <Trash2 size={14} /> حذف این کارت
            </button>
          </div>

          {hintOpen && currentCard.hint_md && (
            <div className="fc-hint">
              <MathContent content={currentCard.hint_md} />
            </div>
          )}

          {explain.cardId === currentCard?.id && (explain.loading || explain.payload || explain.error) && (
            <div className="fc-explain-box">
              {explain.loading && <p className="fc-muted">در حال آماده‌سازی توضیح از روی کتاب…</p>}
              {explain.error && <div className="inline-error">{explain.error}</div>}
              {explain.payload && (
                <>
                  <div className="fc-explain-head">
                    <Sparkles size={14} />
                    <b>توضیح بیشتر</b>
                    <span className="fc-cite-chip">
                      {explain.payload.grounded_in_book ? "مبتنی بر صفحهٔ کتاب" : "بر اساس محتوای همین کارت"}
                    </span>
                  </div>
                  <MathContent content={explain.payload.explain_md} />
                  {explain.payload.citations.length > 0 && (
                    <div className="fc-cite-stack start">
                      {explain.payload.citations.map((cite, index) => (
                        <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                          <BookOpen size={12} /> {cite.citation}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {flipped && !cardResult && (
            <div className="fc-eval-row" role="group" aria-label="ارزیابی این کارت">
              <button
                type="button"
                className="fc-eval got"
                disabled={answerBusy}
                onClick={() => void answer(true)}
              >
                <Check size={18} /> بلد بودم
              </button>
              <button
                type="button"
                className="fc-eval missed"
                disabled={answerBusy}
                onClick={() => void answer(false)}
              >
                <XCircle size={18} /> بلد نبودم
              </button>
            </div>
          )}

          {flipped && cardResult && (
            <p className={`fc-already ${cardResult}`}>
              {cardResult === "got" ? "این کارت را در همین جلسه «بلد بودم» زده‌اید." : "این کارت را در همین جلسه «بلد نبودم» زده‌اید."}
            </p>
          )}

          {!flipped && <p className="fc-muted fc-center fc-kbd-hint">کلید Space برای برگرداندن کارت · کلیدهای ← → برای جابه‌جایی</p>}
        </>
      ) : (
        <div className="fc-empty">کارتی برای نمایش نیست.</div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Results screen
// ---------------------------------------------------------------------------

type ResultsScreenProps = {
  session: StudySessionPayload;
  deckTitle: string;
  busy: boolean;
  onReplaySame: () => void;
  onReplayAll: () => void;
  onReplayMissed: () => void;
  onExit: () => void;
};

function ResultsScreen({ session, deckTitle, busy, onReplaySame, onReplayAll, onReplayMissed, onExit }: ResultsScreenProps) {
  const summary = session.summary;
  const missedCount = summary.missed;
  const modeLabel = session.mode === "smart" ? "مرور هوشمند" : session.mode === "subset" ? "مرور دوباره" : "مطالعهٔ کامل";
  return (
    <div className="fc-results" dir="rtl">
      <header className="fc-toolbar">
        <div>
          <h2>آفرین، جلسهٔ مطالعه تمام شد!</h2>
          <p className="fc-muted fc-small">
            {deckTitle} · {modeLabel}
          </p>
        </div>
      </header>

      <div className="fc-results-grid">
        <div className="fc-stat main">
          <span className="fc-stat-value">{summary.percent.toLocaleString("fa-IR")}٪</span>
          <span className="fc-stat-label">درصد پاسخ‌های درست</span>
        </div>
        <div className="fc-stat">
          <span className="fc-stat-value">{totalFa(summary.total)}</span>
          <span className="fc-stat-label">تعداد کارت‌ها</span>
        </div>
        <div className="fc-stat got">
          <span className="fc-stat-value">
            <Check size={16} /> {totalFa(summary.got)}
          </span>
          <span className="fc-stat-label">بلد بودم</span>
        </div>
        <div className="fc-stat missed">
          <span className="fc-stat-value">
            <XCircle size={16} /> {totalFa(summary.missed)}
          </span>
          <span className="fc-stat-label">بلد نبودم</span>
        </div>
      </div>

      <div className="fc-progress wide">
        <span style={{ width: `${summary.percent}%` }} />
      </div>

      <p className="fc-muted fc-center">
        {summary.percent >= 80
          ? "عالی بود! کارت‌های سخت‌تر هم به‌زودی با مرور هوشمند دوباره پرسیده می‌شوند."
          : summary.percent >= 50
            ? "خوب پیش رفتید؛ کارت‌های اشتباه را دوباره مرور کنید تا تثبیت شوند."
            : "اشکالی ندارد؛ از مرور دوبارهٔ کارت‌هایی که بلد نبودید شروع کنید."}
      </p>

      <div className="fc-results-actions">
        <button type="button" className="fc-btn primary" onClick={onReplaySame} disabled={busy}>
          <RotateCcw size={16} /> مرور همین کارت‌ها
        </button>
        <button type="button" className="fc-btn" onClick={onReplayAll} disabled={busy}>
          <Layers size={16} /> مرور همهٔ کارت‌ها
        </button>
        <button type="button" className="fc-btn" onClick={onReplayMissed} disabled={busy || missedCount === 0}>
          <XCircle size={16} /> مرور فقط بلد نبودم‌ها
          {missedCount === 0 && <span className="fc-small">(هیچ‌کدام)</span>}
        </button>
        <button type="button" className="fc-btn" onClick={onExit} disabled={busy}>
          بازگشت به دسته‌ها
        </button>
      </div>
    </div>
  );
}

function totalFa(value: number): string {
  return value.toLocaleString("fa-IR");
}

// ---------------------------------------------------------------------------
// Generation modal (NotebookLM-style options: count, difficulty, focus)
// ---------------------------------------------------------------------------

type GenerateModalProps = {
  decks: FlashcardDeck[];
  onClose: () => void;
  onGenerated: (deckId: number, message: string) => Promise<void>;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
};

function GenerateModal({ decks, onClose, onGenerated, authFetch }: GenerateModalProps) {
  const [source, setSource] = useState<"book" | "mistake">("book");
  const [grades, setGrades] = useState<GradeRow[]>([]);
  const [majors, setMajors] = useState<MajorRow[]>([]);
  const [grade, setGrade] = useState<number | "">("");
  const [major, setMajor] = useState("");
  const [books, setBooks] = useState<BookOption[]>([]);
  const [bookId, setBookId] = useState<number | "">("");
  const [chapter, setChapter] = useState("");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [exams, setExams] = useState<ExamRow[]>([]);
  const [examId, setExamId] = useState("");
  const [count, setCount] = useState(5);
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [focusPrompt, setFocusPrompt] = useState("");
  const [deckChoice, setDeckChoice] = useState<string>("new");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const selectedGrade = grades.find((row) => row.number === grade);
  const needsMajor = Boolean(selectedGrade?.has_major);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/curriculum/grades")
      .then((response) => response.json())
      .then((payload: GradeRow[]) => {
        if (!cancelled) setGrades(payload);
      })
      .catch(() => undefined);
    fetch("/api/v1/curriculum/majors")
      .then((response) => response.json())
      .then((payload: MajorRow[]) => {
        if (!cancelled) setMajors(payload);
      })
      .catch(() => undefined);
    authFetch("/api/v1/exams")
      .then((response) => (response.ok ? response.json() : []))
      .then((payload: ExamRow[]) => {
        if (!cancelled) setExams(payload.filter((row) => row.status === "submitted"));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  useEffect(() => {
    if (grade === "") return;
    if (needsMajor && !major) return;
    const query = new URLSearchParams({ grade_number: String(grade) });
    if (needsMajor && major) query.set("major_code", major);
    let cancelled = false;
    fetch(`/api/v1/curriculum/books?${query.toString()}`)
      .then(async (response) => {
        const payload = await response.json();
        if (!cancelled) setBooks(response.ok ? (payload as BookOption[]) : []);
      })
      .catch(() => {
        if (!cancelled) setBooks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [grade, major, needsMajor]);

  async function submit() {
    if (busy) return; // never send a duplicate request while one is in flight
    setFormError("");
    const body: Record<string, unknown> = { source, count, difficulty };
    const focus = focusPrompt.trim();
    if (focus) body.focus_prompt = focus;
    if (deckChoice === "new") {
      if (newTitle.trim()) body.new_deck_title = newTitle.trim();
    } else {
      body.deck_id = Number(deckChoice);
    }
    if (source === "book") {
      if (bookId === "") return setFormError("کتاب را انتخاب کنید.");
      body.book_id = bookId;
      if (chapter.trim()) body.chapter_number = Number(chapter);
      if (pageStart.trim()) body.page_start = Number(pageStart);
      if (pageEnd.trim()) body.page_end = Number(pageEnd);
      if (!chapter.trim() && !pageStart.trim()) return setFormError("فصل یا بازهٔ صفحه را مشخص کنید.");
    } else {
      if (!examId) return setFormError("یک آزمون ثبت‌شده را انتخاب کنید.");
      body.exam_id = examId;
    }
    setBusy(true);
    try {
      const response = await authFetch("/api/v1/flashcards/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        // The form keeps all its values so the student can retry unchanged.
        setFormError(flashcardErrorMessage(payload, "ساخت فلش‌کارت ناموفق بود."));
        return;
      }
      const created = payload as { deck_id: number; created_count: number };
      await onGenerated(created.deck_id, `${totalFa(created.created_count)} فلش‌کارت با ارجاع به کتاب ساخته شد.`);
    } catch {
      setFormError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-modal-backdrop" role="dialog" aria-modal="true" aria-label="ساخت با هوش مصنوعی">
      <div className="fc-modal">
        <header className="fc-toolbar">
          <h2>
            <Sparkles size={18} /> ساخت فلش‌کارت با هوش مصنوعی
          </h2>
          <button type="button" className="fc-icon-btn" onClick={onClose} aria-label="بستن" disabled={busy}>
            <X size={18} />
          </button>
        </header>

        <div className="fc-segment" role="tablist">
          <button type="button" className={source === "book" ? "active" : ""} onClick={() => setSource("book")} disabled={busy}>
            از فصل یا صفحه‌های کتاب
          </button>
          <button
            type="button"
            className={source === "mistake" ? "active" : ""}
            onClick={() => setSource("mistake")}
            disabled={busy}
          >
            از اشتباهات آزمون
          </button>
        </div>

        {source === "book" ? (
          <div className="fc-form-grid">
            <label>
              پایه
              <select
                value={grade}
                onChange={(event) => {
                  setGrade(event.target.value ? Number(event.target.value) : "");
                  setBooks([]);
                  setBookId("");
                }}
              >
                <option value="">انتخاب کنید</option>
                {grades.map((row) => (
                  <option key={row.number} value={row.number}>
                    {row.title}
                  </option>
                ))}
              </select>
            </label>
            {needsMajor && (
              <label>
                رشته
                <select
                  value={major}
                  onChange={(event) => {
                    setMajor(event.target.value);
                    setBooks([]);
                    setBookId("");
                  }}
                >
                  <option value="">انتخاب کنید</option>
                  {majors.map((row) => (
                    <option key={row.code} value={row.code}>
                      {row.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="wide">
              کتاب
              <select value={bookId} onChange={(event) => setBookId(event.target.value ? Number(event.target.value) : "")}>
                <option value="">انتخاب کنید</option>
                {books.map((book) => (
                  <option key={book.id} value={book.id}>
                    {book.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              شمارهٔ فصل
              <input value={chapter} onChange={(event) => setChapter(event.target.value)} inputMode="numeric" placeholder="مثلاً ۳" />
            </label>
            <label>
              از صفحهٔ PDF
              <input value={pageStart} onChange={(event) => setPageStart(event.target.value)} inputMode="numeric" />
            </label>
            <label>
              تا صفحهٔ PDF
              <input value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} inputMode="numeric" />
            </label>
            <p className="fc-muted fc-small wide">حداکثر ۸ صفحه در هر بار ساخت مجاز است.</p>
          </div>
        ) : (
          <div className="fc-form-grid">
            <label className="wide">
              آزمون
              <select value={examId} onChange={(event) => setExamId(event.target.value)}>
                <option value="">انتخاب کنید</option>
                {exams.map((exam) => (
                  <option key={exam.id} value={exam.id}>
                    {exam.title}
                    {exam.book_title ? ` — ${exam.book_title}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="fc-muted fc-small wide">
              فقط پاسخ‌های نادرستِ همین آزمون، با توضیح و ارجاع صفحه، به کارت تبدیل می‌شوند.
            </p>
          </div>
        )}

        {/* Honest scope preview: what will be sent, before any generation runs.
            The server re-validates the real page scope at generation time. */}
        <div className="fc-preview-box" aria-label="پیش‌نمایش درخواست">
          <b>پیش‌نمایش درخواست</b>
          {source === "book" ? (
            bookId !== "" ? (
              <ul>
                <li>
                  کتاب: <b>{books.find((book) => book.id === bookId)?.title ?? "—"}</b>
                </li>
                <li>
                  محدوده:{" "}
                  {chapter.trim()
                    ? `فصل ${Number(chapter).toLocaleString("fa-IR")}`
                    : "کل کتاب"}
                  {pageStart.trim() && (
                    <>
                      {" · صفحهٔ PDF "}
                      {Number(pageStart).toLocaleString("fa-IR")}
                      {pageEnd.trim() && pageEnd !== pageStart && <> تا {Number(pageEnd).toLocaleString("fa-IR")}</>}
                    </>
                  )}
                </li>
                <li>
                  {COUNT_PRESETS.find((preset) => preset.value === count)?.label ?? ""} ({totalFa(count)} کارت) · سطح:{" "}
                  {DIFFICULTY_OPTIONS.find((option) => option.key === difficulty)?.label ?? ""}
                </li>
                <li>
                  مقصد: {deckChoice === "new" ? (newTitle.trim() ? `دستهٔ تازه «${newTitle.trim()}»` : "دستهٔ تازه") : decks.find((deck) => deck.id === Number(deckChoice))?.title ?? "دستهٔ انتخابی"}
                </li>
              </ul>
            ) : (
              <p className="fc-muted fc-small">ابتدا کتاب را انتخاب کنید تا محدودهٔ ساخت اینجا نمایش داده شود.</p>
            )
          ) : examId ? (
            <ul>
              <li>
                آزمون: <b>{exams.find((exam) => exam.id === examId)?.title ?? "—"}</b>
              </li>
              <li>
                {COUNT_PRESETS.find((preset) => preset.value === count)?.label ?? ""} ({totalFa(count)} کارت) · سطح:{" "}
                {DIFFICULTY_OPTIONS.find((option) => option.key === difficulty)?.label ?? ""}
              </li>
              <li>مقصد: {deckChoice === "new" ? (newTitle.trim() ? `دستهٔ تازه «${newTitle.trim()}»` : "دستهٔ تازه") : decks.find((deck) => deck.id === Number(deckChoice))?.title ?? "دستهٔ انتخابی"}</li>
            </ul>
          ) : (
            <p className="fc-muted fc-small">ابتدا آزمون را انتخاب کنید تا پیش‌نمایش اینجا نمایش داده شود.</p>
          )}
          <span className="fc-muted fc-small">اعتبار فصل/صفحه‌ها هنگام ساخت، روی دادهٔ واقعی کتاب بررسی می‌شود.</span>
        </div>

        <fieldset className="fc-fieldset">
          <legend>تعداد فلش‌کارت‌ها</legend>
          <div className="fc-choice-row" role="radiogroup" aria-label="تعداد فلش‌کارت‌ها">
            {COUNT_PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                role="radio"
                aria-checked={count === preset.value}
                className={`fc-choice ${count === preset.value ? "active" : ""}`}
                onClick={() => setCount(preset.value)}
                disabled={busy}
              >
                <b>{preset.label}</b>
                <span className="fc-small">{totalFa(preset.value)} کارت</span>
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="fc-fieldset">
          <legend>سطح دشواری</legend>
          <div className="fc-choice-row" role="radiogroup" aria-label="سطح دشواری">
            {DIFFICULTY_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                role="radio"
                aria-checked={difficulty === option.key}
                className={`fc-choice ${difficulty === option.key ? "active" : ""}`}
                onClick={() => setDifficulty(option.key)}
                disabled={busy}
                title={option.hint}
              >
                <b>{option.label}</b>
                <span className="fc-small">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <label className="fc-focus-box">
          <b>می‌خواهی فلش‌کارت‌ها روی چه موضوعی تمرکز کنند؟</b>
          <textarea
            value={focusPrompt}
            onChange={(event) => setFocusPrompt(event.target.value.slice(0, MAX_FOCUS_PROMPT_CHARS))}
            rows={3}
            maxLength={MAX_FOCUS_PROMPT_CHARS}
            placeholder="مثلاً: فقط قوانین و فرمول‌های این فصل را پوشش بده، یا روی قانون دوم نیوتن تمرکز کن…"
          />
          <span className="fc-muted fc-small fc-focus-meta">
            اختیاری · حداکثر {totalFa(MAX_FOCUS_PROMPT_CHARS)} نویسه ·{" "}
            {totalFa(MAX_FOCUS_PROMPT_CHARS - focusPrompt.length)} باقی مانده
          </span>
        </label>

        <div className="fc-form-grid">
          <label>
            مقصد
            <select value={deckChoice} onChange={(event) => setDeckChoice(event.target.value)}>
              <option value="new">دستهٔ تازه</option>
              {decks.map((deck) => (
                <option key={deck.id} value={deck.id}>
                  {deck.title}
                </option>
              ))}
            </select>
          </label>
          {deckChoice === "new" && (
            <label className="wide">
              نام دستهٔ تازه (اختیاری)
              <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} maxLength={255} />
            </label>
          )}
        </div>

        {formError && <div className="inline-error">{formError}</div>}

        <div className="fc-modal-actions">
          <button type="button" className="fc-btn" onClick={onClose} disabled={busy}>
            انصراف
          </button>
          <button type="button" className="fc-btn primary" onClick={() => void submit()} disabled={busy}>
            <Sparkles size={16} />
            {busy ? (
              <>
                در حال ساخت… <span className="fc-spinner" aria-label="در حال ساخت" />
              </>
            ) : (
              "ساخت کارت‌ها"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Card details dialog: provenance, edit, report issue, delete (Phase 03)
// ---------------------------------------------------------------------------

type CardDetailsDialogProps = {
  card: Flashcard;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
};

function CardDetailsDialog({ card, authFetch, onClose, onChanged, onDeleted }: CardDetailsDialogProps) {
  const [editing, setEditing] = useState(false);
  const [front, setFront] = useState(card.front_md);
  const [back, setBack] = useState(card.back_md);
  const [hint, setHint] = useState(card.hint_md || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState(CARD_REPORT_REASONS[0]?.value ?? "other");
  const [reportNote, setReportNote] = useState("");
  const [reported, setReported] = useState(false);

  async function saveEdit() {
    if (busy) return; // double-submit guard
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${card.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          front_md: front.trim(),
          back_md: back.trim(),
          hint_md: hint.trim(),
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        // keep the editor open with its values so the student can retry
        setError(flashcardErrorMessage(payload, "ذخیرهٔ ویرایش ناموفق بود."));
        return;
      }
      setEditing(false);
      setSaved("ویرایش ذخیره شد.");
      await onChanged();
    } catch {
      setError("ارتباط با سرور برقرار نشد؛ ویرایش ذخیره نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function submitReport() {
    if (busy || reported) return; // double-submit guard
    setBusy(true);
    setError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${card.id}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reportReason, note: reportNote.trim() || null }),
      });
      if (response.status === 409) {
        setReported(true);
        setSaved("گزارش بازی از این کارت دارید؛ در انتظار بررسی است.");
        return;
      }
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setError(flashcardErrorMessage(payload, "ثبت گزارش ناموفق بود."));
        return;
      }
      setReported(true);
      setReportOpen(false);
      setSaved("گزارش شما ثبت شد و برای بررسی ارسال گردید.");
      await onChanged();
    } catch {
      setError("ارتباط با سرور برقرار نشد؛ گزارش ثبت نشد.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (busy) return;
    if (!window.confirm("این کارت حذف شود؟ آمار مرور آن هم پاک می‌شود.")) return;
    setBusy(true);
    setError("");
    try {
      const response = await authFetch(`/api/v1/flashcards/cards/${card.id}`, { method: "DELETE" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(flashcardErrorMessage(payload, "حذف کارت ناموفق بود."));
        return;
      }
      await onDeleted();
    } catch {
      setError("ارتباط با سرور برقرار نشد؛ کارت حذف نشد.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-modal-backdrop" role="dialog" aria-modal="true" aria-label="جزئیات کارت">
      <div className="fc-modal">
        <header className="fc-toolbar">
          <h2>
            <Layers size={18} /> جزئیات کارت
          </h2>
          <button type="button" className="fc-icon-btn" onClick={onClose} aria-label="بستن" disabled={busy}>
            <X size={18} />
          </button>
        </header>

        {error && <div className="inline-error">{error}</div>}
        {saved && !error && <div className="fc-notice">{saved}</div>}

        {editing ? (
          <div className="fc-form-grid">
            <label className="wide">
              روی کارت
              <textarea value={front} onChange={(event) => setFront(event.target.value)} rows={3} maxLength={1200} />
            </label>
            <label className="wide">
              پشت کارت
              <textarea value={back} onChange={(event) => setBack(event.target.value)} rows={4} maxLength={2000} />
            </label>
            <label className="wide">
              راهنما (اختیاری)
              <textarea value={hint} onChange={(event) => setHint(event.target.value)} rows={2} maxLength={600} />
            </label>
            <div className="fc-modal-actions wide">
              <button type="button" className="fc-btn" onClick={() => setEditing(false)} disabled={busy}>
                انصراف
              </button>
              <button
                type="button"
                className="fc-btn primary"
                onClick={() => void saveEdit()}
                disabled={busy || !front.trim() || !back.trim()}
              >
                <Check size={15} /> {busy ? "در حال ذخیره…" : "ذخیرهٔ ویرایش"}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="fc-details-block">
              <span className="fc-face-label">سؤال</span>
              <MathContent content={card.front_md} />
            </div>
            <div className="fc-details-block">
              <span className="fc-face-label">پاسخ</span>
              <MathContent content={card.back_md} />
            </div>
            {card.hint_md && (
              <div className="fc-hint">
                <MathContent content={card.hint_md} />
              </div>
            )}
            {card.citations.length > 0 ? (
              <div className="fc-cite-stack">
                {card.citations.map((cite, index) => (
                  <span key={`${cite.pdf_page_index}-${index}`} className="fc-cite-chip">
                    <BookOpen size={12} /> {cite.citation}
                    {cite.printed_page_number !== null && cite.printed_page_number !== undefined && (
                      <> · صفحهٔ چاپی {cite.printed_page_number.toLocaleString("fa-IR")}</>
                    )}
                  </span>
                ))}
              </div>
            ) : (
              <p className="fc-muted fc-small">این کارت ارجاع صفحه‌ای به کتاب رسمی ندارد.</p>
            )}
          </>
        )}

        {!editing && (
          <div className="fc-modal-actions">
            <button type="button" className="fc-btn" onClick={() => setEditing(true)} disabled={busy}>
              <RotateCcw size={15} /> ویرایش
            </button>
            {!reported && (
              <button type="button" className="fc-btn" onClick={() => setReportOpen((value) => !value)} disabled={busy}>
                <XCircle size={15} /> گزارش ایراد
              </button>
            )}
            <button type="button" className="fc-btn danger" onClick={() => void remove()} disabled={busy}>
              <Trash2 size={15} /> حذف کارت
            </button>
          </div>
        )}

        {reportOpen && !reported && (
          <div className="fc-report-box">
            <label>
              دلیل گزارش
              <select value={reportReason} onChange={(event) => setReportReason(event.target.value)} disabled={busy}>
                {CARD_REPORT_REASONS.map((reason) => (
                  <option key={reason.value} value={reason.value}>
                    {reason.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              توضیح (اختیاری)
              <textarea
                value={reportNote}
                onChange={(event) => setReportNote(event.target.value.slice(0, 300))}
                rows={2}
                maxLength={300}
                placeholder="مثلاً: پاسخ با صفحهٔ ۲۳ کتاب می‌خواند."
              />
            </label>
            <button type="button" className="fc-btn primary small" onClick={() => void submitReport()} disabled={busy}>
              {busy ? "در حال ارسال…" : "ثبت گزارش"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
