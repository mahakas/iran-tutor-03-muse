"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Clock,
  Download,
  Mic,
  Pause,
  Play,
  RotateCw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import { buildUserAuthHeaders, useAppContext } from "@/components/AppProvider";
import MathContent from "@/components/MathContent";
import { usePodcastPlayer, type PlayerTrack } from "@/components/PodcastPlayerProvider";
import { fetchMyCapabilities } from "@/lib/capabilities";
import { flashcardErrorMessage } from "@/lib/flashcards";
import {
  FEEDBACK_REASON_LABELS,
  FORMAT_HINTS,
  FORMAT_LABELS,
  LENGTH_LABELS,
  PLAYBACK_SPEEDS,
  STATUS_LABELS,
  faDate,
  formatDuration,
  podcastErrorMessage,
  type PodcastConfig,
  type PodcastEpisode,
  type PodcastFormat,
  type PodcastLength,
} from "@/lib/podcast";
import type { BookOption } from "@/lib/types";

type View = "library" | "create" | "detail";
type GradeRow = { number: number; title: string; has_major: boolean };
type MajorRow = { code: string; title: string };
const IN_PROGRESS_STATUSES = new Set(["queued", "generating_script", "generating_audio", "assembling_audio"]);

function toLatinDigits(raw: string): string {
  return raw
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

function parseChapters(raw: string): number[] {
  return [...new Set(
    toLatinDigits(raw)
      .split(/[,،\s]+/)
      .map((token) => Number(token.trim()))
      .filter((value) => Number.isInteger(value) && value >= 1 && value <= 99),
  )].slice(0, 12);
}

async function downloadResponse(response: Response, filename: string) {
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

async function retryEpisode(authFetch: (input: string, init?: RequestInit) => Promise<Response>, episodeId: number) {
  const response = await authFetch(`/api/v1/podcasts/${episodeId}/retry`, { method: "POST" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(podcastErrorMessage(payload, "تلاش مجدد ناموفق بود."));
  }
}

/** Real cancel through the backend job lifecycle (queued/generating/assembling). */
async function cancelEpisodeJob(authFetch: (input: string, init?: RequestInit) => Promise<Response>, episodeId: number) {
  const response = await authFetch(`/api/v1/podcasts/${episodeId}/cancel`, { method: "POST" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(podcastErrorMessage(payload, "لغو تولید ناموفق بود."));
  }
}

export default function PodcastWorkspace() {
  const { authFetch, getActiveToken } = useAppContext();
  const player = usePodcastPlayer();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("library");
  const [config, setConfig] = useState<PodcastConfig | null>(null);
  const [episodes, setEpisodes] = useState<PodcastEpisode[]>([]);
  const [detail, setDetail] = useState<PodcastEpisode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadEpisodes = useCallback(async () => {
    const response = await authFetch("/api/v1/podcasts");
    if (response.status === 403) {
      setEnabled(false);
      return;
    }
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(podcastErrorMessage(payload, "بارگذاری پادکست‌ها ناموفق بود."));
    setEpisodes(((payload as { items: PodcastEpisode[] }).items) ?? []);
  }, [authFetch]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      const keys = await fetchMyCapabilities(buildUserAuthHeaders(getActiveToken()));
      if (cancelled) return;
      if (keys !== null && !keys.has("audio_podcast")) {
        setEnabled(false);
        setLoading(false);
        return;
      }
      setEnabled(true);
      try {
        const configResponse = await authFetch("/api/v1/podcasts/config");
        if (configResponse.ok) setConfig((await configResponse.json()) as PodcastConfig);
        await loadEpisodes();
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
  }, [authFetch, getActiveToken, loadEpisodes]);

  // Poll while any episode is still generating (survives leaving/returning to the page).
  const hasPending = useMemo(
    () => episodes.some((episode) => IN_PROGRESS_STATUSES.has(episode.status)),
    [episodes],
  );
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => {
      void loadEpisodes().catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [hasPending, loadEpisodes]);

  function openDetail(episode: PodcastEpisode) {
    setDetail(episode);
    setView("detail");
    setError("");
    setNotice("");
  }

  async function refreshDetail(episodeId: number) {
    const response = await authFetch(`/api/v1/podcasts/${episodeId}`);
    if (!response.ok) return;
    const payload = (await response.json()) as PodcastEpisode;
    setDetail(payload);
    await loadEpisodes();
  }

  async function playEpisode(episode: PodcastEpisode) {
    setError("");
    const response = await authFetch(`/api/v1/podcasts/${episode.id}/audio`);
    if (!response.ok) {
      setError("فایل صوتی این پادکست هنوز آماده نیست.");
      return;
    }
    const blob = await response.blob();
    const track: PlayerTrack = {
      episodeId: episode.id,
      title: episode.title,
      subtitle: [episode.book_title, episode.format_label].filter(Boolean).join(" · "),
      src: URL.createObjectURL(blob),
    };
    player.load(track);
  }

  async function downloadEpisode(episode: PodcastEpisode) {
    const response = await authFetch(`/api/v1/podcasts/${episode.id}/download`);
    if (!response.ok) {
      setError("دانلود ناموفق بود.");
      return;
    }
    await downloadResponse(response, `darsyar-podcast-${episode.id}.mp3`);
  }

  async function renameEpisode(episode: PodcastEpisode) {
    const title = window.prompt("عنوان تازهٔ پادکست:", episode.title)?.trim();
    if (!title || title === episode.title) return;
    const response = await authFetch(`/api/v1/podcasts/${episode.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!response.ok) {
      setError("تغییر عنوان ناموفق بود.");
      return;
    }
    setNotice("عنوان پادکست تغییر کرد.");
    await loadEpisodes();
    if (detail?.id === episode.id) await refreshDetail(episode.id);
  }

  async function deleteEpisode(episode: PodcastEpisode) {
    if (!window.confirm(`پادکست «${episode.title}» حذف شود؟ فایل صوتی و متن آن هم پاک می‌شود.`)) return;
    if (player.current?.episodeId === episode.id) player.close();
    const response = await authFetch(`/api/v1/podcasts/${episode.id}`, { method: "DELETE" });
    if (!response.ok) {
      setError("حذف پادکست ناموفق بود.");
      return;
    }
    setNotice("پادکست حذف شد.");
    if (detail?.id === episode.id) {
      setDetail(null);
      setView("library");
    }
    await loadEpisodes();
  }

  async function regenerateEpisode(episode: PodcastEpisode) {
    const response = await authFetch(`/api/v1/podcasts/${episode.id}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(podcastErrorMessage(payload, "تولید نسخهٔ جدید ناموفق بود."));
      return;
    }
    setNotice("نسخهٔ جدید در صف تولید قرار گرفت؛ نسخهٔ قبلی حفظ شد.");
    await loadEpisodes();
    await openEpisodeById(Number(payload.episode_id));
  }

  async function openEpisodeById(episodeId: number) {
    const response = await authFetch(`/api/v1/podcasts/${episodeId}`);
    if (!response.ok) return;
    openDetail((await response.json()) as PodcastEpisode);
  }

  if (enabled === false) {
    return (
      <section className="fc-panel fc-disabled" dir="rtl">
        <X size={22} />
        <h2>این قابلیت در حال حاضر غیرفعال است</h2>
        <p>پادکست آموزشی توسط مدیر درسیار غیرفعال شده است. بعداً دوباره سر بزنید.</p>
      </section>
    );
  }

  return (
    <div className="pc-root" dir="rtl">
      {error && <div className="inline-error fc-alert">{error}</div>}
      {notice && <div className="fc-notice">{notice}</div>}

      {view === "library" && (
        <PodcastLibrary
          loading={loading}
          episodes={episodes}
          onCreate={() => {
            setView("create");
            setError("");
            setNotice("");
          }}
          onPlay={(episode) => void playEpisode(episode)}
          onOpen={(episode) => void openEpisodeById(episode.id)}
          onDownload={(episode) => void downloadEpisode(episode)}
          onRename={(episode) => void renameEpisode(episode)}
          onDelete={(episode) => void deleteEpisode(episode)}
          onRegenerate={(episode) => void regenerateEpisode(episode)}
          onRetry={(episode) =>
            void retryEpisode(authFetch, episode.id)
              .then(() => loadEpisodes())
              .then(() => setNotice("پادکست دوباره در صف تولید قرار گرفت."))
              .catch((caught: unknown) =>
                setError(caught instanceof Error ? caught.message : "تلاش مجدد ناموفق بود."),
              )
          }
          onCancelJob={(episode) =>
            void cancelEpisodeJob(authFetch, episode.id)
              .then(() => loadEpisodes())
              .then(() => setNotice("تولید پادکست لغو شد."))
              .catch((caught: unknown) =>
                setError(caught instanceof Error ? caught.message : "لغو تولید ناموفق بود."),
              )
          }
        />
      )}

      {view === "create" && config && (
        <PodcastCreateForm
          config={config}
          onCancel={() => setView("library")}
          onCreated={async (episodeId) => {
            await loadEpisodes();
            await openEpisodeById(episodeId);
          }}
        />
      )}

      {view === "detail" && detail && (
        <PodcastDetail
          detail={detail}
          onBack={() => {
            setView("library");
            void loadEpisodes();
          }}
          onRefresh={async () => {
            await refreshDetail(detail.id);
          }}
          onPlay={() => void playEpisode(detail)}
          onRetry={() =>
            void retryEpisode(authFetch, detail.id)
              .then(() => refreshDetail(detail.id))
              .catch((caught: unknown) =>
                setError(caught instanceof Error ? caught.message : "تلاش مجدد ناموفق بود."),
              )
          }
          onCancelJob={() =>
            void cancelEpisodeJob(authFetch, detail.id)
              .then(() => refreshDetail(detail.id))
              .catch((caught: unknown) =>
                setError(caught instanceof Error ? caught.message : "لغو تولید ناموفق بود."),
              )
          }
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

type LibraryProps = {
  loading: boolean;
  episodes: PodcastEpisode[];
  onCreate: () => void;
  onPlay: (episode: PodcastEpisode) => void;
  onOpen: (episode: PodcastEpisode) => void;
  onDownload: (episode: PodcastEpisode) => void;
  onRename: (episode: PodcastEpisode) => void;
  onDelete: (episode: PodcastEpisode) => void;
  onRegenerate: (episode: PodcastEpisode) => void;
  onRetry: (episode: PodcastEpisode) => void;
  onCancelJob: (episode: PodcastEpisode) => void;
};

function PodcastLibrary({ loading, episodes, onCreate, onPlay, onOpen, onDownload, onRename, onDelete, onRegenerate, onRetry, onCancelJob }: LibraryProps) {
  return (
    <>
      <header className="fc-toolbar">
        <div>
          <h2>
            <Mic size={20} /> پادکست‌های من
          </h2>
          <p className="fc-muted">گفت‌وگوی صوتی آموزشی تولیدشده از فصل‌های کتاب درسی شما.</p>
        </div>
        <button type="button" className="fc-btn primary" onClick={onCreate}>
          <Sparkles size={16} /> ساخت پادکست جدید
        </button>
      </header>

      {loading && <p className="fc-muted">در حال بارگذاری…</p>}
      {!loading && episodes.length === 0 && (
        <div className="pc-empty">
          هنوز پادکستی ندارید. یک فصل از کتابتان را انتخاب کنید و اولین گفت‌وگوی صوتی‌تان را بسازید.
        </div>
      )}

      <div className="pc-grid">
        {episodes.map((episode) => (
          <article key={episode.id} className="pc-card" data-status={episode.status}>
            <div className="pc-cover" aria-hidden="true">
              <Mic size={26} />
              {episode.status === "completed" && (
                <button
                  type="button"
                  className="pc-cover-play"
                  aria-label={`پخش ${episode.title}`}
                  onClick={() => onPlay(episode)}
                >
                  <Play size={20} />
                </button>
              )}
            </div>
            <div className="pc-card-body">
              <h3>
                <button type="button" className="pc-link" onClick={() => onOpen(episode)}>
                  {episode.title}
                </button>
              </h3>
              <div className="pc-meta">
                <span>{episode.book_title ?? "—"}</span>
                {episode.chapters.length > 0 && <span>· فصل {episode.chapters.join(" و ")}</span>}
                <span>· {faDate(episode.created_at)}</span>
                <span>· {formatDuration(episode.duration_seconds)}</span>
              </div>
              <div className="pc-badges">
                <span className="pc-badge format">{episode.format_label}</span>
                <span className={`pc-badge status ${episode.status}`}>{STATUS_LABELS[episode.status]}</span>
                {episode.single_speaker_mode && <span className="pc-badge">تک‌گوینده</span>}
              </div>
              {IN_PROGRESS_STATUSES.has(episode.status) && (
                <div className="pc-progress">
                  <span style={{ width: `${episode.progress}%` }} />
                  <small>
                    {episode.progress}٪ · {episode.progress_stage}
                  </small>
                </div>
              )}
              {episode.status === "failed" && episode.error_detail && (
                <p className="pc-error-text">{episode.error_detail}</p>
              )}
            </div>
            <div className="pc-card-actions">
              {episode.status === "completed" && (
                <button type="button" className="fc-btn small" onClick={() => onPlay(episode)}>
                  <Play size={14} /> پخش
                </button>
              )}
              {(episode.status === "failed" || episode.status === "cancelled") && (
                <button type="button" className="fc-btn small" onClick={() => onRetry(episode)}>
                  <RotateCw size={14} /> تلاش مجدد
                </button>
              )}
              {IN_PROGRESS_STATUSES.has(episode.status) && (
                <button
                  type="button"
                  className="fc-btn small pc-cancel-btn"
                  onClick={() => onCancelJob(episode)}
                  aria-label={`لغو تولید ${episode.title}`}
                >
                  <X size={14} /> لغو تولید
                </button>
              )}
              <button type="button" className="fc-btn small" onClick={() => onOpen(episode)}>
                جزئیات
              </button>
              {episode.has_audio && (
                <button type="button" className="fc-icon-btn" aria-label="دانلود" onClick={() => onDownload(episode)}>
                  <Download size={15} />
                </button>
              )}
              <button type="button" className="fc-icon-btn" aria-label="تغییر عنوان" onClick={() => onRename(episode)}>
                <RotateCw size={15} />
              </button>
              <button type="button" className="fc-icon-btn" aria-label="تولید نسخهٔ جدید" onClick={() => onRegenerate(episode)}>
                <Sparkles size={15} />
              </button>
              <button type="button" className="fc-icon-btn" aria-label="حذف پادکست" onClick={() => onDelete(episode)}>
                <Trash2 size={15} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Create form (NotebookLM "Customize Audio Overview" style)
// ---------------------------------------------------------------------------

type CreateProps = {
  config: PodcastConfig;
  onCancel: () => void;
  onCreated: (episodeId: number) => Promise<void>;
};

function PodcastCreateForm({ config, onCancel, onCreated }: CreateProps) {
  const { authFetch } = useAppContext();
  const [grades, setGrades] = useState<GradeRow[]>([]);
  const [majors, setMajors] = useState<MajorRow[]>([]);
  const [grade, setGrade] = useState<number | "">("");
  const [major, setMajor] = useState("");
  const [books, setBooks] = useState<BookOption[]>([]);
  const [bookId, setBookId] = useState<number | "">("");
  const [chaptersRaw, setChaptersRaw] = useState("");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [includeNotebook, setIncludeNotebook] = useState(false);
  const [includeLivingBook, setIncludeLivingBook] = useState(false);
  const [format, setFormat] = useState<PodcastFormat>("deep_dive");
  const [language, setLanguage] = useState("fa");
  const [length, setLength] = useState<PodcastLength>("standard");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

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
    return () => {
      cancelled = true;
    };
  }, []);

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

  const chapters = parseChapters(chaptersRaw);
  const selectedBook = books.find((book) => book.id === bookId);
  const lengthMeta = config.lengths.find((item) => item.key === length);

  async function submit() {
    if (busy) return; // never double-submit
    setFormError("");
    if (bookId === "") return setFormError("کتاب را انتخاب کنید.");
    if (chapters.length === 0 && !pageStart.trim()) return setFormError("حداقل یک فصل یا بازهٔ صفحه را انتخاب کنید.");
    setBusy(true);
    try {
      const response = await authFetch("/api/v1/podcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          book_id: bookId,
          format,
          language,
          length,
          custom_prompt: prompt,
          chapter_numbers: chapters,
          page_start: pageStart.trim() ? Number(pageStart) : undefined,
          page_end: pageEnd.trim() ? Number(pageEnd) : undefined,
          include_notebook: includeNotebook,
          include_living_book: includeLivingBook,
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setFormError(podcastErrorMessage(payload, "شروع تولید پادکست ناموفق بود."));
        setConfirmOpen(false);
        return;
      }
      await onCreated(Number((payload as { episode_id: number }).episode_id));
    } catch {
      setFormError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  }

  /** Step 1: validate, then show the explicit source confirmation before any generation. */
  function requestConfirmation() {
    setFormError("");
    if (bookId === "") {
      setFormError("کتاب را انتخاب کنید.");
      return;
    }
    if (chapters.length === 0 && !pageStart.trim()) {
      setFormError("حداقل یک فصل یا بازهٔ صفحه را انتخاب کنید.");
      return;
    }
    setConfirmOpen(true);
  }

  return (
    <div className="pc-create" dir="rtl">
      <header className="fc-toolbar">
        <div>
          <button type="button" className="fc-link" onClick={onCancel}>
            ← پادکست‌های من
          </button>
          <h2>ساخت پادکست جدید</h2>
        </div>
      </header>

      <section className="pc-section">
        <h3>۱. انتخاب منابع</h3>
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
            فصل‌ها (با ویرگول جدا کنید؛ چند فصل مجاز است)
            <input
              value={chaptersRaw}
              onChange={(event) => setChaptersRaw(event.target.value)}
              placeholder="مثلاً: ۲، ۳"
            />
          </label>
          <label>
            از صفحهٔ PDF (اختیاری)
            <input value={pageStart} onChange={(event) => setPageStart(event.target.value)} inputMode="numeric" />
          </label>
          <label>
            تا صفحهٔ PDF (اختیاری)
            <input value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} inputMode="numeric" />
          </label>
          <label className="pc-check wide">
            <input type="checkbox" checked={includeNotebook} onChange={(event) => setIncludeNotebook(event.target.checked)} />
            استفاده از دفترچهٔ یادداشت این کتاب
          </label>
          <label className="pc-check wide">
            <input type="checkbox" checked={includeLivingBook} onChange={(event) => setIncludeLivingBook(event.target.checked)} />
            استفاده از خلاصهٔ تأییدشدهٔ کتاب زنده
          </label>
        </div>
        <div className="pc-summary">
          <b>منابع انتخاب‌شده:</b>{" "}
          {selectedBook ? selectedBook.title : "—"}
          {chapters.length > 0 && ` · فصل ${chapters.join(" و ")}`}
          {pageStart.trim() && ` · صفحهٔ ${pageStart.trim()} تا ${pageEnd.trim() || pageStart.trim()}`}
          {includeNotebook && " · دفترچهٔ یادداشت"}
          {includeLivingBook && " · کتاب زنده"}
        </div>
        <p className="fc-muted fc-small">
          فقط صفحات تأییدشده با متن معتبر استفاده می‌شوند و محتوا به پایهٔ تحصیلی شما محدود است.
        </p>
      </section>

      <section className="pc-section">
        <h3>۲. قالب پادکست</h3>
        <div className="pc-format-grid" role="radiogroup" aria-label="قالب پادکست">
          {(Object.keys(FORMAT_LABELS) as PodcastFormat[]).map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={format === key}
              className={`pc-choice ${format === key ? "active" : ""}`}
              onClick={() => setFormat(key)}
              disabled={busy}
            >
              <b>{FORMAT_LABELS[key]}</b>
              <span className="fc-small">{FORMAT_HINTS[key]}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="pc-section">
        <h3>۳. زبان، مدت و تمرکز گویندگان</h3>
        <div className="pc-row">
          <label>
            زبان
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {config.languages.map((lang) => (
                <option key={lang.code} value={lang.code}>
                  {lang.label}
                </option>
              ))}
            </select>
          </label>
          <div className="pc-length-row" role="radiogroup" aria-label="مدت پادکست">
            {config.lengths.map((item) => (
              <button
                key={item.key}
                type="button"
                role="radio"
                aria-checked={length === item.key}
                className={`pc-choice small ${length === item.key ? "active" : ""}`}
                onClick={() => setLength(item.key)}
                disabled={busy}
              >
                <b>{item.label}</b>
                <span className="fc-small">{item.target_minutes} دقیقه</span>
              </button>
            ))}
          </div>
        </div>
        {config.single_speaker_mode && (
          <p className="fc-muted fc-small">
            صدای دو گوینده در تنظیمات مدیریتی یکسان است؛ پادکست دو نفره با یک صدا و نقش‌های متفاوت ساخته می‌شود.
          </p>
        )}
        <label className="pc-prompt-box">
          <b>دوست داری گویندگان در این قسمت روی چه موضوعی تمرکز کنند؟</b>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value.slice(0, config.max_custom_prompt_chars))}
            rows={3}
            maxLength={config.max_custom_prompt_chars}
            placeholder="مثلاً: فقط نکات امتحانی فصل را توضیح بدهند، یا روی فرمول‌های مهم تمرکز کنند…"
          />
          <span className="fc-muted fc-small fc-focus-meta">
            اختیاری · حداکثر {config.max_custom_prompt_chars} نویسه ·{" "}
            {config.max_custom_prompt_chars - prompt.length} باقی مانده
          </span>
        </label>
      </section>

      <section className="pc-section pc-preview">
        <h3>۴. پیش‌نمایش</h3>
        <ul>
          <li>
            کتاب: {selectedBook ? selectedBook.title : "—"}
            {chapters.length > 0 && ` — فصل ${chapters.join(" و ")}`}
          </li>
          <li>قالب: {FORMAT_LABELS[format]} — {FORMAT_HINTS[format]}</li>
          <li>
            مدت هدف: {LENGTH_LABELS[length]} ({lengthMeta?.target_minutes} دقیقه) · زبان:{" "}
            {config.languages.find((lang) => lang.code === language)?.label ?? language}
          </li>
          {prompt.trim() && <li>تمرکز: {prompt.trim()}</li>}
        </ul>
      </section>

      {formError && <div className="inline-error">{formError}</div>}

      {confirmOpen && (
        <section className="pc-section pc-confirm" aria-label="تأیید منابع و شروع تولید">
          <h3>۵. تأیید منبع و محدوده</h3>
          <ul>
            <li>
              کتاب: {selectedBook ? selectedBook.title : "—"}
              {chapters.length > 0 && ` — فصل ${chapters.join(" و ")}`}
              {pageStart.trim() &&
                ` — صفحهٔ ${pageStart.trim()} تا ${pageEnd.trim() || pageStart.trim()}`}
            </li>
            <li>قالب: {FORMAT_LABELS[format]} · مدت: {LENGTH_LABELS[length]} · زبان: {config.languages.find((lang) => lang.code === language)?.label ?? language}</li>
            {prompt.trim() && <li>تمرکز گویندگان: {prompt.trim()}</li>}
          </ul>
          <p className="pc-confirm-warn">
            فقط صفحات تأییدشدهٔ همین کتاب با متن معتبر وارد پادکست می‌شوند؛ محتوا در محدودهٔ پایه و رشتهٔ شما می‌ماند.
            اگر برای این محدوده منبع کافی پیدا نشود، تولید همان ابتدا متوقف می‌شود و پیام دقیق نتیجه نمایش داده می‌شود.
          </p>
          <div className="fc-modal-actions">
            <button type="button" className="fc-btn" onClick={() => setConfirmOpen(false)} disabled={busy}>
              بازگشت به ویرایش
            </button>
            <button type="button" className="fc-btn primary" onClick={() => void submit()} disabled={busy}>
              <Mic size={16} />
              {busy ? "در حال ارسال…" : "تأیید و شروع تولید"}
            </button>
          </div>
        </section>
      )}

      <div className="fc-modal-actions">
        <button type="button" className="fc-btn" onClick={onCancel} disabled={busy}>
          انصراف
        </button>
        <button type="button" className="fc-btn primary" onClick={requestConfirmation} disabled={busy}>
          <Mic size={16} />
          {busy ? "در حال ارسال…" : "تولید پادکست"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail: full player + transcript + sources + interaction
// ---------------------------------------------------------------------------

const IN_PROGRESS: string[] = ["queued", "generating_script", "generating_audio", "assembling_audio"];

type DetailProps = {
  detail: PodcastEpisode;
  onBack: () => void;
  onRefresh: () => Promise<void>;
  onPlay: () => void;
  onRetry: () => void;
  onCancelJob: () => void;
};

function PodcastDetail({ detail, onBack, onRefresh, onPlay, onRetry, onCancelJob }: DetailProps) {
  const player = usePodcastPlayer();
  const { authFetch } = useAppContext();
  const [showTranscript, setShowTranscript] = useState(true);
  const [askOpen, setAskOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState("");
  const [showReasons, setShowReasons] = useState(false);

  const episode = detail;
  const isCurrent = player.current?.episodeId === episode.id;
  const inProgress = IN_PROGRESS.includes(episode.status);

  // Poll generation status while working; refresh once when it completes.
  useEffect(() => {
    if (!inProgress) return;
    const timer = setInterval(() => {
      void onRefresh();
    }, 3000);
    return () => clearInterval(timer);
  }, [inProgress, onRefresh]);

  const played = isCurrent ? player.position : 0;
  const total = isCurrent && player.duration > 0 ? player.duration : episode.duration_seconds ?? 0;
  const percent = total > 0 ? Math.min(100, (played / total) * 100) : 0;

  const activeSegmentId = useMemo(() => {
    if (!episode.segments) return null;
    const timed = episode.segments.find(
      (segment) => segment.start_time !== null && segment.end_time !== null && played >= segment.start_time && played < segment.end_time,
    );
    return timed ? timed.id : null;
  }, [episode.segments, played]);

  // Segment timeline only from backend-measured times (never estimates).
  const timedSegments = useMemo(() => {
    if (!episode.segments || total <= 0) return [];
    return episode.segments.filter(
      (segment) => segment.start_time !== null && segment.end_time !== null && segment.end_time > segment.start_time,
    );
  }, [episode.segments, total]);

  async function submitQuestion(text: string) {
    if (!text.trim() || asking) return;
    setAsking(true);
    setAskError("");
    try {
      if (isCurrent && !player.isPlaying) player.toggle(); // keep playback paused while asking
      const response = await authFetch(`/api/v1/podcasts/${episode.id}/questions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text.trim() }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setAskError(podcastErrorMessage(payload, "دریافت پاسخ ناموفق بود."));
        return;
      }
      setQuestion("");
      await onRefresh();
    } catch {
      setAskError("ارتباط با سرور برقرار نشد.");
    } finally {
      setAsking(false);
    }
  }

  async function setFeedback(liked: boolean, reasons: string[] = []) {
    const response = await authFetch(`/api/v1/podcasts/${episode.id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ liked, reasons }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setAskError(podcastErrorMessage(payload, "ثبت بازخورد ناموفق بود."));
      return;
    }
    setShowReasons(false);
    await onRefresh();
  }

  const speedValue = isCurrent ? player.speed : 1;
  function changeSpeed() {
    if (!isCurrent) return;
    const index = PLAYBACK_SPEEDS.indexOf(speedValue as (typeof PLAYBACK_SPEEDS)[number]);
    player.setSpeed(PLAYBACK_SPEEDS[(index + 1) % PLAYBACK_SPEEDS.length]);
  }

  function seekTo(time: number) {
    if (!isCurrent) return;
    player.seek(time);
  }

  function toggleOrPlay() {
    // When this episode is already loaded in the global player, these buttons
    // are a play/pause toggle — their icon and label say so. Re-loading via
    // onPlay() would keep playing, so the "توقف" label never actually paused
    // (Phase 04C: root cause of the mislabelled wasPlaying evidence in the
    // Phase 04B report).
    if (isCurrent) {
      player.toggle();
      return;
    }
    onPlay();
  }

  return (
    <div className="pc-detail" dir="rtl">
      <header className="fc-toolbar">
        <div>
          <button type="button" className="fc-link" onClick={onBack}>
            ← پادکست‌های من
          </button>
          <h2>{episode.title}</h2>
          <p className="fc-muted fc-small">
            {episode.book_title ?? "—"}
            {episode.chapters.length > 0 && ` · فصل ${episode.chapters.join(" و ")}`} · {episode.format_label} ·{" "}
            {STATUS_LABELS[episode.status]}
          </p>
        </div>
        <div className="fc-toolbar-actions">
          {episode.status === "completed" && (
            <button type="button" className="fc-btn primary" onClick={toggleOrPlay} disabled={!episode.has_audio}>
              {isCurrent && player.isPlaying ? <Pause size={16} /> : <Play size={16} />} پخش
            </button>
          )}
          {(episode.status === "failed" || episode.status === "cancelled") && (
            <button type="button" className="fc-btn primary" onClick={onRetry}>
              <RotateCw size={16} /> تلاش مجدد
            </button>
          )}
          {inProgress && (
            <button type="button" className="fc-btn pc-cancel-btn" onClick={onCancelJob}>
              <X size={16} /> لغو تولید
            </button>
          )}
          {episode.status === "failed" && (
            <span className="pc-badge status failed">ناموفق: {episode.error_detail}</span>
          )}
        </div>
      </header>

      {inProgress && (
        <div className="pc-progress wide">
          <span style={{ width: `${episode.progress}%` }} />
          <small>
            {episode.progress}٪ · {episode.progress_stage} — می‌توانید صفحه را ببندید؛ وضعیت ذخیره می‌شود.
          </small>
        </div>
      )}

      {episode.status === "completed" && (
        <section className="pc-player" aria-label="پخش‌کنندهٔ پادکست">
          <div className="pc-player-main">
            <button type="button" className="pc-big-play" onClick={toggleOrPlay} disabled={!episode.has_audio}
                    aria-label={isCurrent && player.isPlaying ? "توقف" : "پخش"}>
              {isCurrent && player.isPlaying ? <Pause size={26} /> : <Play size={26} />}
            </button>
            <div className="pc-player-body">
              <div className="pc-player-bar" role="slider" aria-label="نوار پیشرفت"
                   aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(played)}
                   tabIndex={0}
                   onClick={(event) => {
                     const rect = event.currentTarget.getBoundingClientRect();
                     const ratio = 1 - (event.clientX - rect.left) / rect.width; // RTL bar
                     seekTo(ratio * total);
                   }}>
                <span style={{ width: `${percent}%` }} />
              </div>
              <div className="pc-player-times">
                <span>{formatDuration(played)}</span>
                <span>{formatDuration(total)}</span>
              </div>
              {timedSegments.length > 0 && (
                <div className="pc-timeline" role="group" aria-label="خط زمانی بخش‌های پادکست">
                  {timedSegments.map((segment, index) => (
                    <button
                      key={segment.id}
                      type="button"
                      className={`pc-timeline-seg speaker-${segment.speaker} ${activeSegmentId === segment.id ? "active" : ""}`}
                      style={{ flexGrow: Math.max(1, (segment.end_time ?? 0) - (segment.start_time ?? 0)) }}
                      onClick={() => seekTo(segment.start_time ?? 0)}
                      aria-label={`پرش به بخش ${index + 1}: ${segment.speaker_label} از ${formatDuration(segment.start_time)}`}
                      title={`${segment.speaker_label} · ${formatDuration(segment.start_time)}`}
                    >
                      <span>{index + 1}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="pc-player-controls">
                <button type="button" className="fc-btn small" onClick={() => seekTo(Math.max(0, played - 15))} disabled={!isCurrent}>
                  −۱۵ ثانیه
                </button>
                <button type="button" className="fc-btn small" onClick={() => seekTo(played + 15)} disabled={!isCurrent}>
                  +۱۵ ثانیه
                </button>
                <button type="button" className="fc-btn small" onClick={changeSpeed} disabled={!isCurrent}>
                  سرعت: {speedValue}×
                </button>
                <label className="pc-volume">
                  <Volume2 size={15} />
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={isCurrent ? player.volume : 1}
                    onChange={(event) => player.setVolume(Number(event.target.value))}
                    aria-label="صدا"
                  />
                </label>
              </div>
            </div>
          </div>
          <div className="pc-player-actions">
            <button type="button" className="fc-btn small" onClick={() => setAskOpen((value) => !value)}>
              <Sparkles size={14} /> از گویندگان سؤال بپرس
            </button>
            <button type="button" className="fc-btn small" onClick={() => setShowTranscript((value) => !value)}>
              {showTranscript ? "بستن متن پادکست" : "نمایش متن پادکست"}
            </button>
          </div>
        </section>
      )}

      {askOpen && episode.status === "completed" && (
        <section className="pc-ask">
          <h3>از گویندگان سؤال بپرس</h3>
          {episode.suggested_questions.length > 0 && (
            <div className="pc-suggested">
              {episode.suggested_questions.map((suggestion) => (
                <button key={suggestion} type="button" className="pc-chip" onClick={() => void submitQuestion(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={2}
            maxLength={1000}
            placeholder="مثلاً: چرا در این مثال از این قانون استفاده شد؟"
          />
          {askError && <div className="inline-error">{askError}</div>}
          <button type="button" className="fc-btn primary small" onClick={() => void submitQuestion(question)} disabled={asking}>
            {asking ? "در حال پاسخ‌گیری…" : "پرسش از گویندگان"}
          </button>
          {episode.questions && episode.questions.length > 0 && (
            <div className="pc-qa-list">
              {episode.questions.map((qa) => (
                <article key={qa.id} className="pc-qa">
                  <b>سؤال: {qa.question}</b>
                  <MathContent content={qa.answer_md} />
                  {qa.citations.length > 0 && (
                    <div className="pc-cite-stack">
                      {qa.citations.map((cite) => (
                        <span key={cite.index} className="fc-cite-chip">
                          <BookOpen size={12} /> {cite.citation}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {showTranscript && episode.segments && episode.segments.length > 0 && (
        <section className="pc-transcript">
          <h3>متن پادکست</h3>
          <ol className="pc-transcript-list">
            {episode.segments.map((segment) => (
              <li
                key={segment.id}
                className={`pc-turn ${activeSegmentId === segment.id ? "active" : ""} speaker-${segment.speaker}`}
              >
                <header>
                  <b>{segment.speaker_label}</b>
                  {segment.start_time !== null && (
                    <button type="button" className="pc-time-chip" onClick={() => seekTo(segment.start_time ?? 0)}>
                      <Clock size={12} /> {formatDuration(segment.start_time)}
                    </button>
                  )}
                </header>
                <p>{segment.text}</p>
                {episode.sources && segment.source_refs.length > 0 && (
                  <div className="pc-cite-stack">
                    {segment.source_refs.map((ref) => {
                      const source = episode.sources?.find((item) => item.index === ref);
                      return source ? (
                        <span key={ref} className="fc-cite-chip">
                          <BookOpen size={12} /> {source.citation}
                        </span>
                      ) : null;
                    })}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {episode.status === "completed" && (
        <section className="pc-feedback" aria-label="بازخورد پادکست">
          <span>این پادکست چطور بود؟</span>
          <button
            type="button"
            className={`fc-icon-btn ${episode.feedback?.liked === true ? "liked" : ""}`}
            aria-label="پسندیدم"
            onClick={() => void setFeedback(true)}
          >
            <ThumbsUp size={16} />
          </button>
          <button
            type="button"
            className={`fc-icon-btn ${episode.feedback?.liked === false ? "disliked" : ""}`}
            aria-label="نپسندیدم"
            onClick={() => setShowReasons((value) => !value)}
          >
            <ThumbsDown size={16} />
          </button>
          {showReasons && (
            <div className="pc-reasons">
              {Object.entries(FEEDBACK_REASON_LABELS).map(([key, label]) => (
                <label key={key} className="pc-check">
                  <input
                    type="checkbox"
                    checked={episode.feedback?.reasons.includes(key) ?? false}
                    onChange={() => {
                      const current = episode.feedback?.reasons ?? [];
                      const next = current.includes(key) ? current.filter((item) => item !== key) : [...current, key];
                      episode.feedback = { liked: false, reasons: next };
                      void setFeedback(false, next);
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
