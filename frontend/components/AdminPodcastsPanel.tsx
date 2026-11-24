"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, Mic, RefreshCw } from "lucide-react";

/**
 * Phase 06 admin view over the existing podcast admin endpoints
 * (GET /api/v1/admin/podcasts/stats + /episodes). Strictly read-only: the
 * backend exposes no admin mutation for episodes (retry/cancel are owner-side
 * student endpoints), so none is fabricated here. All numbers come from the
 * API; an empty dataset renders an explicit empty state, never zeroes styled
 * as live data.
 */

type StatsPayload = {
  total_episodes: number;
  by_status: Record<string, number>;
  completed: number;
  failed: number;
  storage_bytes: number;
  total_duration_seconds: number;
  avg_processing_seconds: number | null;
  model_usage: Record<string, number>;
  ai_calls: number;
  tokens_in: number;
  tokens_out: number;
  regenerations: number;
  feedback: { liked: number; disliked: number; reason_counts: Record<string, number> };
};

type EpisodeRow = {
  id: string;
  title: string;
  book_id: number | null;
  format: string;
  language: string;
  length: string;
  status: string;
  progress: number | null;
  duration_seconds: number | null;
  byte_size: number | null;
  model_name: string | null;
  error_code: string | null;
  single_speaker_mode: boolean;
  created_at: string | null;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "در صف",
  processing: "در حال تولید",
  generating: "در حال تولید",
  completed: "آماده",
  failed: "خطا",
  cancelled: "لغوشده",
};

const STATUS_OPTIONS = ["completed", "processing", "generating", "pending", "failed", "cancelled"] as const;

function fmtNum(value: number) {
  try {
    return new Intl.NumberFormat("fa-IR").format(value);
  } catch {
    return String(value);
  }
}

function fmtBytes(bytes: number) {
  if (!bytes || bytes <= 0) return "۰ بایت";
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} گیگابایت`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} مگابایت`;
  return `${Math.max(1, Math.round(bytes / 1024))} کیلوبایت`;
}

function fmtSeconds(seconds: number | null) {
  if (seconds === null || seconds === undefined) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes > 0 ? `${fmtNum(minutes)} دقیقه و ${fmtNum(rest)} ثانیه` : `${fmtNum(rest)} ثانیه`;
}

function fmtWhen(value: string | null) {
  if (!value) return "—";
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return value;
  try {
    return new Intl.DateTimeFormat("fa-IR", { dateStyle: "short", timeStyle: "short" }).format(ms);
  } catch {
    return value;
  }
}

export default function AdminPodcastsPanel({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [rows, setRows] = useState<EpisodeRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Read the persisted status filter back from the URL (?tab=podcasts&status=…)
  // so a refresh or shared link keeps the same working context. Lazy init: the
  // panel renders client-side only (page body is gated behind the auth check),
  // so no SSR/hydration mismatch; try/catch keeps the prerendered shell safe.
  const [statusFilter, setStatusFilter] = useState(() => {
    try {
      const current = new URLSearchParams(window.location.search).get("status") ?? "";
      return STATUS_OPTIONS.includes(current as (typeof STATUS_OPTIONS)[number]) ? current : "";
    } catch {
      return "";
    }
  });

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (statusFilter) params.set("status", statusFilter);
    return params.toString();
  }, [statusFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [statsRes, listRes] = await Promise.all([
        fetch("/api/v1/admin/podcasts/stats", { credentials: "same-origin", headers: authHeaders }),
        fetch(`/api/v1/admin/podcasts/episodes?${query}`, { credentials: "same-origin", headers: authHeaders }),
      ]);
      if (statsRes.status === 401 || listRes.status === 401) {
        onUnauthorized();
        return;
      }
      if (!statsRes.ok || !listRes.ok) {
        setError("بارگذاری آمار پادکست‌ها ناموفق بود.");
        return;
      }
      setStats((await statsRes.json()) as StatsPayload);
      setRows(((await listRes.json()) as { items: EpisodeRow[] }).items ?? []);
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, onUnauthorized, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Persist the status filter into the URL (replaceState: filters are working
  // context, not history steps — tab navigation already owns history entries).
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("tab", "podcasts");
      if (statusFilter) params.set("status", statusFilter);
      else params.delete("status");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      // best-effort
    }
  }, [statusFilter]);

  return (
    <div className="admin-billing-stack">
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>پادکست‌های آموزشی (نمای عملیاتی)</h2>
            <p>
              آمار تولید، مصرف و بازخورد پادکست‌ها از APIهای موجود مدیریت؛ متن رونویسی و محتوای خصوصی کاربران
              در این نما هرگز نمایش داده نمی‌شود. تکرار یا لغو تولید، عملیاتی سمت دانش‌آموز است.
            </p>
          </div>
          <div className="report-head-actions">
            <button type="button" className="outline-button" disabled={loading} onClick={() => void load()}>
              <RefreshCw size={14} className={loading ? "spin" : ""} /> بروزرسانی
            </button>
          </div>
        </div>
        {error && <div className="inline-error admin-banner">{error}</div>}
        {loading && !stats ? (
          <div className="review-loading">
            <LoaderCircle className="spin" size={18} /> <span>در حال دریافت آمار پادکست…</span>
          </div>
        ) : null}
        {stats && !loading ? (
          <div className="admin-kpi-grid">
            <div className="admin-kpi-card">
              <span>کل اپیزودها</span>
              <b>{fmtNum(stats.total_episodes)}</b>
              <small>آماده: {fmtNum(stats.completed)} · خطا: {fmtNum(stats.failed)}</small>
            </div>
            <div className="admin-kpi-card">
              <span>حجم ذخیره‌سازی</span>
              <b>{fmtBytes(stats.storage_bytes)}</b>
              <small>مدت کل: {fmtSeconds(stats.total_duration_seconds)}</small>
            </div>
            <div className="admin-kpi-card">
              <span>میانگین زمان پردازش</span>
              <b>{stats.avg_processing_seconds === null ? "داده‌ای ثبت نشده" : fmtSeconds(stats.avg_processing_seconds)}</b>
              <small>فقط اپیزودهای با زمان‌سنج کامل</small>
            </div>
            <div className="admin-kpi-card">
              <span>مصرف هوش مصنوعی</span>
              <b>{fmtNum(stats.tokens_in + stats.tokens_out)} توکن</b>
              <small>{fmtNum(stats.ai_calls)} فراخوانی · تولید مجدد: {fmtNum(stats.regenerations)}</small>
            </div>
            <div className="admin-kpi-card">
              <span>بازخورد دانش‌آموزان</span>
              <b>{fmtNum(stats.feedback.liked)} / {fmtNum(stats.feedback.disliked)}</b>
              <small>پسندیده / ناپسندیده</small>
            </div>
            <div className="admin-kpi-card">
              <span>مدل‌های استفاده‌شده</span>
              <b dir="ltr">{Object.keys(stats.model_usage).length || "—"}</b>
              <small dir="ltr">{Object.entries(stats.model_usage).map(([m, c]) => `${m} (${c})`).join(" · ") || "بدون ثبت مدل"}</small>
            </div>
          </div>
        ) : null}
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>اپیزودهای اخیر</h2>
            <p>۵۰ اپیزود آخر؛ فیلتر وضعیت در URL ذخیره می‌شود و با بازآوری صفحه باقی می‌ماند.</p>
          </div>
          <label style={{ fontSize: 14 }}>
            وضعیت{" "}
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">همه</option>
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status] ?? status}
                </option>
              ))}
            </select>
          </label>
        </div>
        {loading && rows === null ? (
          <div className="review-loading">
            <LoaderCircle className="spin" size={18} /> <span>در حال دریافت فهرست…</span>
          </div>
        ) : rows && rows.length === 0 ? (
          <div className="usage-empty">
            <Mic size={16} /> اپیزودی با این فیلتر ثبت نشده است.
          </div>
        ) : rows ? (
          <div className="admin-users-table-wrap">
            <table className="admin-users-table compact">
              <thead>
                <tr>
                  <th>عنوان</th>
                  <th>وضعیت</th>
                  <th>قالب / زبان</th>
                  <th>مدت</th>
                  <th>حجم</th>
                  <th>مدل</th>
                  <th>ایجاد</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <b>{row.title || "بدون عنوان"}</b>
                      <small>{row.error_code ? `خطا: ${row.error_code}` : row.book_id ? `کتاب #${row.book_id}` : "—"}</small>
                    </td>
                    <td>
                      <span className={`badge-pill ${row.status === "completed" ? "done" : row.status === "failed" ? "failed" : ""}`}>
                        {STATUS_LABELS[row.status] ?? row.status}
                      </span>
                    </td>
                    <td>{row.format} · {row.language}</td>
                    <td>{fmtSeconds(row.duration_seconds)}</td>
                    <td>{fmtBytes(row.byte_size ?? 0)}</td>
                    <td dir="ltr"><small>{row.model_name || "—"}</small></td>
                    <td><small>{fmtWhen(row.created_at)}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
