"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AdminDeletedChatsSection from "@/components/AdminDeletedChatsSection";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  Eye,
  Filter,
  Flag,
  LoaderCircle,
  RefreshCw,
  Search,
  X,
  XCircle,
} from "lucide-react";

export type AdminAuditSummary = {
  id: string;
  user_id: string | null;
  session_id: string | null;
  feature_key: string;
  provider_id: number | null;
  model_name: string | null;
  tokens_in: number;
  tokens_out: number;
  estimated_cost_usd: number;
  latency_ms: number;
  status: string;
  rag_hit_count: number;
  flag_reason: string | null;
  created_at: string | null;
  preview: string;
};

export type AdminAuditDetail = AdminAuditSummary & {
  request_messages_json: { role?: string; content?: unknown }[];
  response_text: string | null;
  rag_citations_json: Record<string, unknown>[];
  error_message: string | null;
  skill_id: string | null;
  flagged_by: string | null;
};

type AuditListPayload = {
  total: number;
  limit: number;
  offset: number;
  items: AdminAuditSummary[];
};

type SummaryPayload = {
  days: number;
  totals: {
    calls: number;
    tokens_in: number;
    tokens_out: number;
    estimated_cost_usd: number;
    errors: number;
    flagged: number;
  };
  by_feature: Record<string, { calls: number; tokens_in: number; tokens_out: number; estimated_cost_usd: number }>;
  by_day: Record<string, { calls: number; tokens_in: number; tokens_out: number; estimated_cost_usd: number }>;
  by_user: Record<string, { calls: number; tokens_in: number; tokens_out: number; estimated_cost_usd: number }>;
};

const STATUS_LABELS: Record<string, string> = {
  success: "موفق",
  error: "خطا",
  blocked: "مسدود",
  flagged: "علامت‌خورده",
};

const FEATURE_LABELS: Record<string, string> = {
  chat: "گفت‌وگو",
  solve: "حل تمرین",
  quiz: "آزمون",
  vision_ocr: "خواندن تصویر",
  stt: "گفتار به متن",
  embedding: "بردارسازی",
  embedding_query: "جست‌وجوی برداری",
  ingest_ocr: "پردازش کتاب",
  flashcards: "فلش‌کارت",
};

const FLAG_REASON_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "grounding_mismatch", label: "عدم تطابق منبع" },
  { value: "rag_miss", label: "منبع یافت نشد" },
  { value: "rag_miss_in_textbook_strict_mode", label: "منبع در حالت سخت‌گیرانه یافت نشد" },
  { value: "provider_probe", label: "آزمایش ارائه‌دهنده" },
  { value: "router_heuristic_fallback", label: "مسیر اکتشافی" },
  { value: "living_book_cache_hit", label: "حافظهٔ کتاب زنده" },
  { value: "notebook_inline_accept", label: "پذیرش درون‌خطی دفترچه" },
  { value: "notebook_inline_reject", label: "رد درون‌خطی دفترچه" },
  { value: "validator_model_disabled", label: "اعتبارسنج غیرفعال" },
  { value: "validator_approved", label: "تأیید اعتبارسنج" },
  { value: "validator_fixed", label: "اصلاح‌شده توسط اعتبارسنج" },
  { value: "validator_rejected", label: "ردشده توسط اعتبارسنج" },
  { value: "tts_cache_hit", label: "حافظهٔ گفتار" },
  { value: "visual_rejected", label: "رد تصویرسازی" },
  { value: "admin_review", label: "بازبینی مدیر" },
];

export default function AdminObservabilityPanel({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [list, setList] = useState<AuditListPayload | null>(null);
  const [summary, setSummary] = useState<SummaryPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<AdminAuditDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Phase 06 URL contract: the observability working context (feature/status/
  // flagged/user/days/page) is read back from the URL on mount and mirrored
  // into it on change, so refresh and shared links keep the exact view.
  const urlParams = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search);
    } catch {
      return new URLSearchParams();
    }
  }, []);

  const [featureFilter, setFeatureFilter] = useState(urlParams.get("feature") ?? "");
  const [statusFilter, setStatusFilter] = useState(urlParams.get("status") ?? "");
  const [flagReasonFilter, setFlagReasonFilter] = useState(() => {
    const initial = urlParams.get("flag_reason") ?? "";
    return FLAG_REASON_OPTIONS.some((option) => option.value === initial) ? initial : "";
  });
  const [flaggedOnly, setFlaggedOnly] = useState(urlParams.get("flagged") === "true");
  const [userFilter, setUserFilter] = useState(urlParams.get("user") ?? "");
  const [days, setDays] = useState(() => {
    const parsed = Number.parseInt(urlParams.get("days") ?? "7", 10);
    return parsed >= 1 && parsed <= 90 ? parsed : 7;
  });
  const [page, setPage] = useState(() => Math.max(0, Number.parseInt(urlParams.get("page") ?? "0", 10) || 0));
  const pageSize = 25;

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (featureFilter) params.set("feature", featureFilter);
      else params.delete("feature");
      if (statusFilter) params.set("status", statusFilter);
      else params.delete("status");
      if (flagReasonFilter) params.set("flag_reason", flagReasonFilter);
      else params.delete("flag_reason");
      if (flaggedOnly) params.set("flagged", "true");
      else params.delete("flagged");
      if (userFilter.trim()) params.set("user", userFilter.trim());
      else params.delete("user");
      if (days !== 7) params.set("days", String(days));
      else params.delete("days");
      if (page > 0) params.set("page", String(page));
      else params.delete("page");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      // history is best-effort
    }
  }, [featureFilter, statusFilter, flagReasonFilter, flaggedOnly, userFilter, days, page]);

  const handle = useCallback(
    (status: number) => {
      if (status === 401) onUnauthorized();
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (featureFilter) params.set("feature_key", featureFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (flagReasonFilter) params.set("flag_reason", flagReasonFilter);
    if (flaggedOnly) params.set("flagged_only", "true");
    if (userFilter.trim()) params.set("user_id", userFilter.trim());
    params.set("limit", String(pageSize));
    params.set("offset", String(page * pageSize));
    return params.toString();
  }, [featureFilter, statusFilter, flagReasonFilter, flaggedOnly, userFilter, page]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [listRes, summaryRes] = await Promise.all([
        fetch(`/api/v1/admin/audit-logs?${query}`, {
          credentials: "same-origin",
          headers: authHeaders,
        }),
        fetch(`/api/v1/admin/audit-logs/summary?days=${days}`, {
          credentials: "same-origin",
          headers: authHeaders,
        }),
      ]);
      if (!handle(listRes.status) || !handle(summaryRes.status)) {
        setError("دسترسی مدیریت منقضی شده است.");
        return;
      }
      setList((await listRes.json()) as AuditListPayload);
      setSummary((await summaryRes.json()) as SummaryPayload);
    } catch {
      setError("بارگذاری گزارش‌ها ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, days, handle, query]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function openDetail(id: string) {
    setDetailLoading(true);
    try {
      const response = await fetch(`/api/v1/admin/audit-logs/${id}`, {
        credentials: "same-origin",
        headers: authHeaders,
      });
      if (!handle(response.status)) return;
      const payload = await response.json();
      setDetail(payload.item as AdminAuditDetail);
    } finally {
      setDetailLoading(false);
    }
  }

  async function flagRecord(id: string) {
    const response = await fetch(`/api/v1/admin/audit-logs/${id}/flag`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({ reason: "admin_review" }),
    });
    if (!handle(response.status)) return;
    setMessage("رکورد برای بازبینی علامت‌گذاری شد.");
    await load();
  }

  const totalPages = list ? Math.max(1, Math.ceil(list.total / pageSize)) : 1;

  return (
    <div className="admin-billing-stack">
      {message && (
        <div className="success-note admin-banner">
          <CheckCircle2 size={15} />
          {message}
        </div>
      )}
      {error && <div className="inline-error admin-banner">{error}</div>}

      <AdminDeletedChatsSection authHeaders={authHeaders} onUnauthorized={onUnauthorized} />

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>مرکز شفافیت کامل (Glass-Box)</h2>
            <p>
              هر فراخوانی هوش مصنوعی با پرامپت، پاسخ، منابع کتاب، توکن، هزینه و تأخیر ثبت می‌شود.
              هیچ درخواستی از دید مدیر پنهان نیست.
            </p>
          </div>
          <div className="admin-chip-row">
            <label className="admin-muted">
              بازه:
              <select
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
                style={{ marginInlineStart: 6 }}
              >
                <option value={1}>۱ روز</option>
                <option value={7}>۷ روز</option>
                <option value={30}>۳۰ روز</option>
                <option value={90}>۹۰ روز</option>
              </select>
            </label>
            <button type="button" className="admin-theme-chip" onClick={() => void load()}>
              <RefreshCw size={14} /> بازخوانی
            </button>
          </div>
        </div>

        {summary && (
          <div className="admin-stat-grid">
            <StatCard label="تعداد فراخوانی" value={summary.totals.calls} icon={<Bot size={16} />} />
            <StatCard
              label="توکن ورودی / خروجی"
              value={`${summary.totals.tokens_in.toLocaleString("fa-IR")} / ${summary.totals.tokens_out.toLocaleString("fa-IR")}`}
              icon={<Clock size={16} />}
            />
            <StatCard
              label="هزینهٔ تخمینی (دلار)"
              value={`$${summary.totals.estimated_cost_usd.toFixed(4)}`}
              icon={<Eye size={16} />}
            />
            <StatCard
              label="خطا / علامت‌خورده"
              value={`${summary.totals.errors} / ${summary.totals.flagged}`}
              icon={<AlertTriangle size={16} />}
            />
          </div>
        )}

        {summary && Object.keys(summary.by_feature).length > 0 && (
          <div className="admin-table-wrap" style={{ marginTop: 14 }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>قابلیت</th>
                  <th>فراخوانی</th>
                  <th>توکن ورودی</th>
                  <th>توکن خروجی</th>
                  <th>هزینه (دلار)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary.by_feature).map(([feature, stats]) => (
                  <tr key={feature}>
                    <td>{FEATURE_LABELS[feature] ?? feature}</td>
                    <td>{stats.calls.toLocaleString("fa-IR")}</td>
                    <td>{stats.tokens_in.toLocaleString("fa-IR")}</td>
                    <td>{stats.tokens_out.toLocaleString("fa-IR")}</td>
                    <td>${stats.estimated_cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>گزارش فراخوانی‌ها</h2>
            <p>فیلتر بر اساس قابلیت، وضعیت، کاربر و رکوردهای علامت‌خورده.</p>
          </div>
          <span className="step-badge">
            <Filter size={14} />
          </span>
        </div>

        <div className="admin-chip-row" style={{ marginBottom: 14 }}>
          <label className="form-field" style={{ minWidth: 160 }}>
            <span>قابلیت</span>
            <select
              value={featureFilter}
              onChange={(event) => {
                setFeatureFilter(event.target.value);
                setPage(0);
              }}
            >
              <option value="">همه</option>
              {Object.keys(FEATURE_LABELS).map((key) => (
                <option key={key} value={key}>
                  {FEATURE_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field" style={{ minWidth: 140 }}>
            <span>وضعیت</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(0);
              }}
            >
              <option value="">همه</option>
              {Object.keys(STATUS_LABELS).map((key) => (
                <option key={key} value={key}>
                  {STATUS_LABELS[key]}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field" style={{ minWidth: 180 }}>
            <span>دلیل علامت</span>
            <select
              value={flagReasonFilter}
              onChange={(event) => {
                setFlagReasonFilter(event.target.value);
                setPage(0);
              }}
            >
              <option value="">همه</option>
              {FLAG_REASON_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field" style={{ minWidth: 180 }}>
            <span>شناسهٔ کاربر</span>
            <input
              dir="ltr"
              value={userFilter}
              onChange={(event) => {
                setUserFilter(event.target.value);
                setPage(0);
              }}
              placeholder="user id"
            />
          </label>
          <button
            type="button"
            className={`admin-theme-chip ${flaggedOnly ? "active" : ""}`}
            onClick={() => {
              setFlaggedOnly((prev) => !prev);
              setPage(0);
            }}
            style={{ alignSelf: "flex-end" }}
          >
            <Flag size={14} /> فقط علامت‌خورده‌ها
          </button>
        </div>

        {loading ? (
          <div className="admin-empty">
            <div>
              <LoaderCircle size={22} className="spin" />
            </div>
            <b>در حال بارگذاری گزارش‌ها…</b>
          </div>
        ) : !list || list.items.length === 0 ? (
          <div className="admin-empty">
            <div>
              <Search size={22} />
            </div>
            <b>رکوردی با این فیلترها پیدا نشد</b>
            <span>پس از اولین فراخوانی هوش مصنوعی، رکوردها اینجا نمایش داده می‌شوند.</span>
          </div>
        ) : (
          <>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>زمان</th>
                    <th>قابلیت</th>
                    <th>مدل</th>
                    <th>منابع</th>
                    <th>توکن</th>
                    <th>تأخیر</th>
                    <th>وضعیت</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((item) => (
                    <tr key={item.id}>
                      <td dir="ltr">
                        {item.created_at ? new Date(item.created_at).toLocaleString("fa-IR") : "—"}
                      </td>
                      <td>{FEATURE_LABELS[item.feature_key] ?? item.feature_key}</td>
                      <td dir="ltr">{item.model_name ?? "—"}</td>
                      <td>{item.rag_hit_count}</td>
                      <td dir="ltr">
                        {item.tokens_in}/{item.tokens_out}
                      </td>
                      <td dir="ltr">{item.latency_ms}ms</td>
                      <td>
                        <StatusChip status={item.status} />
                      </td>
                      <td>
                        <div className="admin-chip-row">
                          <button
                            type="button"
                            className="admin-theme-chip"
                            onClick={() => void openDetail(item.id)}
                          >
                            <Eye size={14} /> جزئیات
                          </button>
                          {item.status !== "flagged" && (
                            <button
                              type="button"
                              className="admin-theme-chip"
                              onClick={() => void flagRecord(item.id)}
                            >
                              <Flag size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="admin-chip-row" style={{ justifyContent: "space-between", marginTop: 12 }}>
              <span className="admin-muted">
                {list.total.toLocaleString("fa-IR")} رکورد · صفحه {page + 1} از {totalPages}
              </span>
              <div className="admin-chip-row">
                <button
                  type="button"
                  className="admin-theme-chip"
                  disabled={page === 0}
                  onClick={() => setPage((prev) => Math.max(0, prev - 1))}
                >
                  قبلی
                </button>
                <button
                  type="button"
                  className="admin-theme-chip"
                  disabled={page + 1 >= totalPages}
                  onClick={() => setPage((prev) => prev + 1)}
                >
                  بعدی
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      {(detail || detailLoading) && (
        <div className="admin-drawer-scrim" role="presentation" onClick={() => setDetail(null)}>
          <aside
            className="admin-drawer"
            onClick={(event) => event.stopPropagation()}
            aria-label="جزئیات فراخوانی هوش مصنوعی"
          >
            <div className="card-heading">
              <div>
                <h2>جزئیات کامل فراخوانی</h2>
                <p dir="ltr">{detail?.id ?? "…"}</p>
              </div>
              <button type="button" className="admin-theme-chip" onClick={() => setDetail(null)}>
                <X size={14} /> بستن
              </button>
            </div>

            {detailLoading || !detail ? (
              <div className="admin-empty">
                <div>
                  <LoaderCircle size={22} className="spin" />
                </div>
                <b>در حال بارگذاری…</b>
              </div>
            ) : (
              <div className="admin-drawer-body">
                <dl className="admin-kv">
                  <div>
                    <dt>قابلیت</dt>
                    <dd>{FEATURE_LABELS[detail.feature_key] ?? detail.feature_key}</dd>
                  </div>
                  <div>
                    <dt>وضعیت</dt>
                    <dd>
                      <StatusChip status={detail.status} />
                    </dd>
                  </div>
                  <div>
                    <dt>مدل</dt>
                    <dd dir="ltr">{detail.model_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>کاربر</dt>
                    <dd dir="ltr">{detail.user_id ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>نشست</dt>
                    <dd dir="ltr">{detail.session_id ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>توکن ورودی / خروجی</dt>
                    <dd dir="ltr">
                      {detail.tokens_in} / {detail.tokens_out}
                    </dd>
                  </div>
                  <div>
                    <dt>هزینهٔ تخمینی</dt>
                    <dd dir="ltr">${detail.estimated_cost_usd.toFixed(6)}</dd>
                  </div>
                  <div>
                    <dt>تأخیر</dt>
                    <dd dir="ltr">{detail.latency_ms}ms</dd>
                  </div>
                  <div>
                    <dt>تعداد منابع کتاب</dt>
                    <dd>{detail.rag_hit_count}</dd>
                  </div>
                  {detail.flag_reason && (
                    <div>
                      <dt>دلیل علامت</dt>
                      <dd>{detail.flag_reason}</dd>
                    </div>
                  )}
                </dl>

                {detail.error_message && (
                  <div className="inline-error" dir="ltr">
                    {detail.error_message}
                  </div>
                )}

                <h3>پرامپت ارسالی</h3>
                <pre className="admin-code" dir="ltr">
                  {JSON.stringify(detail.request_messages_json, null, 2)}
                </pre>

                <h3>پاسخ مدل</h3>
                <pre className="admin-code" dir="rtl">
                  {detail.response_text ?? "—"}
                </pre>

                <h3>منابع کتاب (RAG)</h3>
                {detail.rag_citations_json.length === 0 ? (
                  <div className="admin-muted">
                    هیچ منبعی برای این پاسخ بازیابی نشد
                    {detail.flag_reason === "rag_miss_in_textbook_strict_mode"
                      ? " — به همین دلیل به‌صورت خودکار علامت خورده است."
                      : "."}
                  </div>
                ) : (
                  <ul className="admin-citation-list">
                    {detail.rag_citations_json.map((citation, index) => (
                      <li key={index}>
                        <b>{String(citation.book_title ?? "کتاب")}</b>
                        {citation.chapter_title ? ` · ${String(citation.chapter_title)}` : ""}
                        {citation.printed_page_number != null
                          ? ` · صفحهٔ ${String(citation.printed_page_number)}`
                          : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
}) {
  return (
    <div className="admin-stat-card">
      <span className="admin-stat-icon">{icon}</span>
      <div>
        <span className="admin-muted">{label}</span>
        <b dir="ltr">{typeof value === "number" ? value.toLocaleString("fa-IR") : value}</b>
      </div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const className =
    status === "success"
      ? "admin-status ok"
      : status === "error"
        ? "admin-status bad"
        : "admin-status warn";
  const icon =
    status === "success" ? (
      <CheckCircle2 size={13} />
    ) : status === "error" ? (
      <XCircle size={13} />
    ) : (
      <AlertTriangle size={13} />
    );
  return (
    <span className={className}>
      {icon}
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}
