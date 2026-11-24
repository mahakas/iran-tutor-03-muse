"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type BookRow = {
  id: number;
  title: string;
  grade_number: number;
  major_code: string | null;
  total_pdf_pages: number;
  status: string;
};

type JobRow = {
  id: string;
  book_id: number;
  status: string;
  total_pages: number;
  processed_pages: number;
  failed_pages: number;
  start_page: number | null;
  end_page: number | null;
  error_log: string | null;
  created_at: string | null;
};

type FigureRow = {
  id: number;
  pdf_page_index: number;
  printed_page_number: number | null;
  chapter_number: number | null;
  figure_label: string | null;
  width: number | null;
  height: number | null;
};

type BenchmarkRow = {
  model: string;
  pages: number;
  done: number;
  failed: number;
  needs_review: number;
  warnings: number;
  tokens: number;
  latency_seconds: number;
};

const ACTIVE_JOB_STATES = new Set(["queued", "running"]);

const JOB_STATUS_FA: Record<string, string> = {
  queued: "در صف",
  running: "در حال ایندکس",
  completed: "تکمیل‌شده",
  failed: "ناموفق",
  cancelled: "لغو شده",
};

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

/** Web KB Pipeline + Source Figures + Model Benchmark Lab (Phase 2, admin only). */
export default function AdminKbPanel({ authHeaders, onUnauthorized }: Props) {
  const [books, setBooks] = useState<BookRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [figures, setFigures] = useState<FigureRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  // upload form
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [gradeNumber, setGradeNumber] = useState(12);
  const [majorCode, setMajorCode] = useState("math_physics");
  const [startPage, setStartPage] = useState(1);
  const [endPage, setEndPage] = useState<number | "">("");
  const fileInput = useRef<HTMLInputElement | null>(null);

  // re-index controls
  const [pageIndex, setPageIndex] = useState(1);
  const [chapterNumber, setChapterNumber] = useState(1);

  // benchmark lab
  const [benchModels, setBenchModels] = useState("");
  const [benchPages, setBenchPages] = useState("1");
  const [benchRows, setBenchRows] = useState<BenchmarkRow[] | null>(null);

  const guard = useCallback(
    (status: number) => {
      if (status === 401 || status === 403) {
        onUnauthorized();
        return false;
      }
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const loadBooks = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/admin/books", { cache: "no-store", credentials: "same-origin", headers: authHeaders });
      if (!guard(response.status)) return;
      const rows = (await response.json()) as BookRow[];
      setBooks(rows);
      setSelectedId((current) => current ?? rows[0]?.id ?? null);
    } catch {
      setError("بارگذاری فهرست کتاب‌ها ناموفق بود.");
    }
  }, [authHeaders, guard]);

  const loadJobs = useCallback(
    async (bookId: number) => {
      try {
        const response = await fetch(`/api/v1/admin/kb/jobs?book_id=${bookId}`, { cache: "no-store", credentials: "same-origin", headers: authHeaders });
        if (!guard(response.status)) return;
        const payload = (await response.json()) as { jobs: JobRow[] };
        setJobs(payload.jobs);
      } catch {
        /* keep last known state */
      }
    },
    [authHeaders, guard],
  );

  const loadFigures = useCallback(
    async (bookId: number) => {
      try {
        const response = await fetch(`/api/v1/admin/kb/books/${bookId}/figures`, { cache: "no-store", credentials: "same-origin", headers: authHeaders });
        if (!guard(response.status)) return;
        const payload = (await response.json()) as { figures: FigureRow[] };
        setFigures(payload.figures);
      } catch {
        /* ignore */
      }
    },
    [authHeaders, guard],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    void loadBooks();
  }, [loadBooks]);

  useEffect(() => {
    if (selectedId === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    void loadJobs(selectedId);
    void loadFigures(selectedId);
  }, [selectedId, loadJobs, loadFigures]);

  const hasActiveJob = useMemo(() => jobs.some((job) => ACTIVE_JOB_STATES.has(job.status)), [jobs]);

  // Live progress: poll while a job is queued or running.
  useEffect(() => {
    if (selectedId === null || !hasActiveJob) return;
    const timer = window.setInterval(() => {
      void loadJobs(selectedId);
      void loadBooks();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, selectedId, loadJobs, loadBooks]);

  async function uploadPdf(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("ابتدا یک فایل PDF انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("grade_number", String(gradeNumber));
      if (majorCode.trim()) form.append("major_code", majorCode.trim());
      form.append("book_title", title || file.name.replace(/\.pdf$/i, ""));
      form.append("start_page", String(startPage));
      if (endPage !== "") form.append("end_page", String(endPage));
      const response = await fetch("/api/v1/admin/books/upload-and-ingest", {
        method: "POST",
        credentials: "same-origin",
        headers: authHeaders,
        body: form,
      });
      if (!guard(response.status)) return;
      const payload = (await response.json().catch(() => ({}))) as { detail?: string; book_id?: number; job_id?: string };
      if (!response.ok) {
        setError(payload.detail || "آپلود ناموفق بود.");
        return;
      }
      setNotice("فایل دریافت شد و ایندکس در پس‌زمینه شروع شد. پیشرفت را در همین صفحه ببینید.");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await loadBooks();
      if (payload.book_id) setSelectedId(payload.book_id);
    } catch {
      setError("آپلود ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function postJson(url: string, body: unknown, successText: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(body),
      });
      if (!guard(response.status)) return null;
      const payload = (await response.json().catch(() => ({}))) as Record<string, unknown> & { detail?: string };
      if (!response.ok) {
        setError(payload.detail || "عملیات ناموفق بود.");
        return null;
      }
      setNotice(successText);
      if (selectedId !== null) {
        await loadJobs(selectedId);
        await loadFigures(selectedId);
      }
      return payload;
    } catch {
      setError("عملیات ناموفق بود.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function reindexRange() {
    if (selectedId === null) return;
    await postJson(`/api/v1/admin/kb/books/${selectedId}/ingest`, { start_page: startPage, end_page: endPage === "" ? null : endPage }, "ایندکس بازه در صف قرار گرفت.");
  }

  async function reindexPage() {
    if (selectedId === null) return;
    await postJson(`/api/v1/admin/kb/books/${selectedId}/reindex-page`, { pdf_page_index: pageIndex }, `صفحهٔ ${pageIndex} دوباره ایندکس شد.`);
  }

  async function reindexChapter() {
    if (selectedId === null) return;
    await postJson(`/api/v1/admin/kb/books/${selectedId}/reindex-chapter`, { chapter_number: chapterNumber }, `فصل ${chapterNumber} دوباره ایندکس شد.`);
  }

  async function extractFigures() {
    if (selectedId === null) return;
    const result = await postJson(`/api/v1/admin/kb/books/${selectedId}/figures/extract`, { replace: true }, "شکل‌ها استخراج و ذخیره شدند.");
    if (result && typeof result.figures_created === "number") {
      setNotice(`${result.figures_created} شکل استخراج شد.`);
    }
  }

  async function cancelJob(jobId: string) {
    await postJson(`/api/v1/admin/kb/jobs/${jobId}/cancel`, {}, "درخواست لغو ثبت شد.");
  }

  async function runBenchmark(event: React.FormEvent) {
    event.preventDefault();
    if (selectedId === null) return;
    const models = benchModels.split(",").map((item) => item.trim()).filter(Boolean);
    const pages = benchPages.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0);
    if (!models.length || !pages.length) {
      setError("حداقل یک مدل و یک شمارهٔ صفحه وارد کنید.");
      return;
    }
    setBusy(true);
    setError("");
    setBenchRows(null);
    try {
      const response = await fetch(`/api/v1/admin/kb/books/${selectedId}/benchmark`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ models, pages }),
      });
      if (!guard(response.status)) return;
      const payload = (await response.json().catch(() => ({}))) as { comparison?: BenchmarkRow[]; detail?: string };
      if (!response.ok || !payload.comparison) {
        setError(payload.detail || "مقایسهٔ مدل‌ها ناموفق بود.");
        return;
      }
      setBenchRows(payload.comparison);
    } catch {
      setError("مقایسهٔ مدل‌ها ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  const selectedBook = books.find((book) => book.id === selectedId) || null;

  return (
    <section className="admin-panel" dir="rtl">
      <header className="admin-panel-head">
        <h2>پایگاه دانش کتاب (Web KB Pipeline)</h2>
        <p>
          آپلود PDF، پیگیری پیشرفت ایندکس، ایندکس مجدد صفحه یا فصل، استخراج شکل‌های کتاب و مقایسهٔ مدل‌ها — همه از این صفحه.
        </p>
      </header>
      {error && <p className="admin-error">{error}</p>}
      {notice && <p className="admin-notice">{notice}</p>}

      <form className="admin-card" onSubmit={uploadPdf}>
        <h3>آپلود کتاب PDF</h3>
        <div className="admin-grid">
          <label className="admin-field">
            <span>فایل PDF</span>
            <input ref={fileInput} type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className="admin-field">
            <span>عنوان کتاب</span>
            <input type="text" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="admin-field">
            <span>پایه</span>
            <input type="number" min={1} max={12} value={gradeNumber} onChange={(event) => setGradeNumber(Number(event.target.value))} />
          </label>
          <label className="admin-field">
            <span>رشته (برای پایه‌های دارای رشته)</span>
            <input type="text" dir="ltr" value={majorCode} onChange={(event) => setMajorCode(event.target.value)} />
          </label>
          <label className="admin-field">
            <span>صفحهٔ شروع</span>
            <input type="number" min={1} value={startPage} onChange={(event) => setStartPage(Number(event.target.value))} />
          </label>
          <label className="admin-field">
            <span>صفحهٔ پایان</span>
            <input type="number" min={1} value={endPage} onChange={(event) => setEndPage(event.target.value === "" ? "" : Number(event.target.value))} />
          </label>
        </div>
        <button type="submit" className="admin-btn primary" disabled={busy}>
          آپلود و ایندکس
        </button>
      </form>

      <div className="admin-card">
        <h3>کتاب‌ها</h3>
        <div className="admin-row">
          <select value={selectedId ?? ""} onChange={(event) => setSelectedId(Number(event.target.value))}>
            {books.map((book) => (
              <option key={book.id} value={book.id}>
                {book.title} — پایه {book.grade_number} · {JOB_STATUS_FA[book.status] || book.status}
              </option>
            ))}
          </select>
          {selectedBook && <span className="admin-muted">{selectedBook.total_pdf_pages} صفحه</span>}
        </div>
      </div>

      {selectedId !== null && (
        <>
          <div className="admin-card">
            <h3>پیشرفت ایندکس</h3>
            {jobs.length === 0 && <p className="admin-muted">هنوز جابی برای این کتاب ثبت نشده است.</p>}
            <ul className="admin-jobs">
              {jobs.map((job) => {
                const pct = job.total_pages ? Math.min(100, Math.round((job.processed_pages / job.total_pages) * 100)) : 0;
                return (
                  <li key={job.id} className="admin-job">
                    <div className="admin-row">
                      <strong>{JOB_STATUS_FA[job.status] || job.status}</strong>
                      <span className="admin-muted" dir="ltr">
                        pages {job.start_page}–{job.end_page}
                      </span>
                      {ACTIVE_JOB_STATES.has(job.status) && (
                        <button type="button" className="admin-btn" disabled={busy} onClick={() => void cancelJob(job.id)}>
                          لغو
                        </button>
                      )}
                    </div>
                    <div className="admin-progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                      <span style={{ width: `${pct}%` }} />
                    </div>
                    <div className="admin-muted" dir="ltr">
                      {job.processed_pages}/{job.total_pages} · failed={job.failed_pages}
                    </div>
                    {job.error_log && <div className="admin-error">{job.error_log}</div>}
                  </li>
                );
              })}
            </ul>
            <div className="admin-row">
              <button type="button" className="admin-btn primary" disabled={busy} onClick={() => void reindexRange()}>
                ایندکس مجدد بازهٔ انتخابی
              </button>
              <span className="admin-muted">بازه از فیلدهای «صفحهٔ شروع/پایان» فرم آپلود خوانده می‌شود.</span>
            </div>
          </div>

          <div className="admin-card">
            <h3>ایندکس مجدد تک‌صفحه یا تک‌فصل</h3>
            <div className="admin-row">
              <label className="admin-field inline">
                <span>صفحهٔ PDF</span>
                <input type="number" min={1} value={pageIndex} onChange={(event) => setPageIndex(Number(event.target.value))} />
              </label>
              <button type="button" className="admin-btn" disabled={busy} onClick={() => void reindexPage()}>
                ایندکس این صفحه
              </button>
            </div>
            <div className="admin-row">
              <label className="admin-field inline">
                <span>شمارهٔ فصل</span>
                <input type="number" min={1} value={chapterNumber} onChange={(event) => setChapterNumber(Number(event.target.value))} />
              </label>
              <button type="button" className="admin-btn" disabled={busy} onClick={() => void reindexChapter()}>
                ایندکس این فصل
              </button>
            </div>
          </div>

          <div className="admin-card">
            <h3>شکل‌ها و نمودارهای کتاب (source_figures)</h3>
            <div className="admin-row">
              <button type="button" className="admin-btn" disabled={busy} onClick={() => void extractFigures()}>
                استخراج شکل‌ها از PDF
              </button>
              <span className="admin-muted">{figures.length} شکل ثبت شده</span>
            </div>
            <div className="admin-figure-grid">
              {figures.map((figure) => (
                <FigureThumb key={figure.id} figure={figure} authHeaders={authHeaders} />
              ))}
            </div>
          </div>

          <div className="admin-card">
            <h3>Model Benchmark Lab</h3>
            <p className="admin-muted">
              همان صفحه‌ها را با چند مدل OCR/Vision اجرا و کیفیت، خطا و تأخیر را مقایسه کنید. همهٔ فراخوانی‌ها از ai_gateway و لاگ شفافیت عبور می‌کنند.
            </p>
            <form className="admin-grid" onSubmit={runBenchmark}>
              <label className="admin-field">
                <span>مدل‌ها (با کاما جدا کنید)</span>
                <input type="text" dir="ltr" value={benchModels} onChange={(event) => setBenchModels(event.target.value)} placeholder="model-a, model-b" />
              </label>
              <label className="admin-field">
                <span>شمارهٔ صفحه‌ها (با کاما)</span>
                <input type="text" dir="ltr" value={benchPages} onChange={(event) => setBenchPages(event.target.value)} />
              </label>
              <button type="submit" className="admin-btn primary" disabled={busy}>
                اجرای مقایسه
              </button>
            </form>
            {benchRows && (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>مدل</th>
                    <th>صفحه</th>
                    <th>موفق</th>
                    <th>ناموفق</th>
                    <th>نیازمند بازبینی</th>
                    <th>هشدار</th>
                    <th>توکن</th>
                    <th>تأخیر (ثانیه)</th>
                  </tr>
                </thead>
                <tbody>
                  {benchRows.map((row) => (
                    <tr key={row.model}>
                      <td dir="ltr">{row.model}</td>
                      <td>{row.pages}</td>
                      <td>{row.done}</td>
                      <td>{row.failed}</td>
                      <td>{row.needs_review}</td>
                      <td>{row.warnings}</td>
                      <td>{row.tokens}</td>
                      <td>{row.latency_seconds}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function FigureThumb({ figure, authHeaders }: { figure: FigureRow; authHeaders: Record<string, string> }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    void fetch(`/api/v1/admin/kb/figures/${figure.id}/image`, { credentials: "same-origin", headers: authHeaders })
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [figure.id, authHeaders]);
  return (
    <figure className="admin-figure">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={figure.figure_label || "شکل کتاب"} />
      ) : (
        <div className="admin-figure-placeholder">بارگذاری…</div>
      )}
      <figcaption className="admin-muted">
        {figure.figure_label || `صفحهٔ ${figure.pdf_page_index}`}
        {figure.printed_page_number ? ` · صفحهٔ چاپی ${figure.printed_page_number}` : ""}
      </figcaption>
    </figure>
  );
}
