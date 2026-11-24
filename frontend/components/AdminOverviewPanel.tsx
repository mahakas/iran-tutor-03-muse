"use client";

import {
  Activity,
  AlertTriangle,
  ArrowUpLeft,
  BookOpen,
  CheckCircle2,
  Coins,
  Cpu,
  CreditCard,
  Database,
  FolderOpen,
  LoaderCircle,
  MessageSquare,
  RefreshCw,
  Server,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";

export type AdminOverviewData = {
  system: {
    status: string;
    mode: "demo" | "production";
    database: string;
    vector_backend: string;
    sms_provider: string;
    payment_provider: string;
    llm_base_url: string | null;
    tutor_model: string | null;
    vision_model_primary: string | null;
    vision_model_escalation: string | null;
    speech_to_text_model: string | null;
    embedding_model: string | null;
    has_llm_api_key: boolean;
    override_count: number;
  };
  counts: {
    books_total: number;
    books_ready: number;
    books_ingesting: number;
    books_failed: number;
    pages_total: number;
    pages_done: number;
    pages_needs_review: number;
    pages_failed: number;
    pages_pending: number;
    users_total: number;
    users_active: number;
    users_paid: number;
    active_sessions: number;
    chats_total: number;
    exams_total: number;
    user_files_count: number;
    user_files_bytes: number;
    tokens_used_total: number;
    tokens_used_today: number;
    revenue_toman: number;
  };
  needs_review_pages: Array<{
    book_id: number;
    book_title: string;
    pdf_page_index: number;
    printed_page_number: number | null;
    chapter_title: string | null;
    status: string;
    warnings: string[];
    error_message: string | null;
  }>;
  recent_transactions: Array<{
    id: string;
    user_id: string;
    phone_number: string;
    full_name: string | null;
    plan_code: string;
    plan_name: string;
    amount_toman: number;
    tokens_granted: number;
    duration_days: number;
    provider: string;
    status: string;
    ref_id: string | null;
    created_at: string | null;
    paid_at: string | null;
  }>;
  recent_usage_logs: Array<{
    id: string;
    user_id: string;
    phone_number: string;
    full_name: string | null;
    action: string;
    book_id: number | null;
    book_title: string | null;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_toman: number;
    created_at: string | null;
  }>;
};

type AdminOverviewPanelProps = {
  overview: AdminOverviewData | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onJumpToTab: (tab: "books" | "plans" | "users" | "integrations" | "appearance" | "observability") => void;
  onJumpToBookPage: (bookId: number, pageIndex?: number) => void;
  onJumpToUser: (userId: string) => void;
};

const ACTION_LABELS: Record<string, string> = {
  tutor_ask: "پرسش متنی از معلم",
  tutor_image: "تحلیل تصویر تمرین",
  tutor_audio: "پرسش صوتی",
  exam_create: "ساخت آزمون زمان‌دار",
};

const PROVIDER_LABELS: Record<string, string> = {
  demo: "درگاه آزمایشی",
  zarinpal: "زرین‌پال",
  admin_grant: "تخصیص مدیر",
};

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

function fmtDateTime(iso?: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fa-IR", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export default function AdminOverviewPanel({
  overview,
  loading,
  error,
  onRefresh,
  onJumpToTab,
  onJumpToBookPage,
  onJumpToUser,
}: AdminOverviewPanelProps) {
  if (loading && !overview) {
    return (
      <section className="admin-card">
        <div className="review-loading">
          <LoaderCircle className="spin" size={20} />
          <span>در حال دریافت نمای کلی و آمار زنده سیستم...</span>
        </div>
      </section>
    );
  }

  if (error && !overview) {
    return (
      <section className="admin-card">
        <div className="inline-error">{error}</div>
        <div className="admin-inline-actions" style={{ marginTop: 12 }}>
          <button type="button" className="outline-button" onClick={onRefresh}>
            <RefreshCw size={15} /> تلاش مجدد
          </button>
        </div>
      </section>
    );
  }

  if (!overview) return null;

  const { system, counts, needs_review_pages, recent_transactions, recent_usage_logs } = overview;

  return (
    <div className="admin-billing-stack">
      {error && <div className="inline-error admin-banner">{error}</div>}

      {/* Education catalog management — independent section (owner addendum) */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>مدیریت نظام آموزشی و کاتالوگ درسی</h2>
            <p>
              دوره‌ها، پایه‌ها، شاخه‌ها، زمینه‌ها، رشته‌ها، درس‌ها، کتاب‌ها، نسخه‌ها، ارتباط‌ها و سال‌های تحصیلی —
              تمام تغییرات ممیزی‌شده و بلافاصله در انتخاب‌گر دانش‌آموز اعمال می‌شوند.
            </p>
          </div>
          <a href="/admin/education" className="primary-button" style={{ textDecoration: "none" }}>
            <BookOpen size={15} /> <span>ورود به بخش</span>
          </a>
        </div>
      </section>

      {/* System Status & Quick Actions Strip */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>وضعیت زیرساخت، هوش مصنوعی و درگاه‌های فعال</h2>
            <p>نمای لحظه‌ای سرویس‌های متصل؛ تمام تنظیمات را می‌توانید بدون ری‌استارت از بخش «API و درگاه‌ها» تغییر دهید.</p>
          </div>
          <div className="report-head-actions">
            <button type="button" className="outline-button" disabled={loading} onClick={onRefresh}>
              <RefreshCw size={14} className={loading ? "spin" : ""} /> بروزرسانی آمار
            </button>
            <button type="button" className="primary-button" onClick={() => onJumpToTab("integrations")}>
              <Cpu size={15} /> مدیریت API و درگاه‌ها
            </button>
          </div>
        </div>

        <div className="admin-infra-strip">
          <div className={`admin-infra-pill ${system.mode === "production" ? "live" : "demo"}`}>
            <Sparkles size={15} />
            <div>
              <small>حالت اجرای سیستم</small>
              <b>{system.mode === "production" ? "تولید واقعی (AI Live)" : "آزمایشی (Demo Mode)"}</b>
            </div>
          </div>
          <div className="admin-infra-pill ok">
            <Database size={15} />
            <div>
              <small>پایگاه‌داده و جستجو</small>
              <b>
                {system.database === "postgresql" ? "PostgreSQL" : "SQLite"} · {system.vector_backend}
              </b>
            </div>
          </div>
          <div className={`admin-infra-pill ${system.has_llm_api_key ? "ok" : "warn"}`}>
            <Server size={15} />
            <div>
              <small>مدل معلم / بینایی</small>
              <b dir="ltr">
                {system.tutor_model || "—"} · {system.vision_model_primary || "—"}
              </b>
            </div>
          </div>
          <div className="admin-infra-pill ok">
            <CreditCard size={15} />
            <div>
              <small>درگاه پیامک و پرداخت</small>
              <b>
                SMS: {system.sms_provider} · پرداخت: {system.payment_provider}
              </b>
            </div>
          </div>
        </div>

        {system.override_count > 0 && (
          <div className="review-tip" style={{ marginTop: 12 }}>
            <CheckCircle2 size={15} />
            <span>
              تعداد <b>{fmtNum(system.override_count)}</b> تنظیم پیکربندی از طریق پنل مدیریت جایگزین مقادیر پایهٔ سرور شده و هم‌اکنون فعال است.
            </span>
          </div>
        )}
      </section>

      {/* 8-Card Operational KPI Grid */}
      <div className="admin-kpi-grid">
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("books")}>
          <span>کتاب‌های درسی</span>
          <b>{fmtNum(counts.books_total)} کتاب</b>
          <small>
            آماده: {fmtNum(counts.books_ready)} · در حال پردازش: {fmtNum(counts.books_ingesting)} · خطا: {fmtNum(counts.books_failed)}
          </small>
        </button>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("books")}>
          <span>وضعیت صفحه‌های کتاب‌ها</span>
          <b>{fmtNum(counts.pages_done)} / {fmtNum(counts.pages_total)}</b>
          <small>
            نیازمند بازبینی: {fmtNum(counts.pages_needs_review)} · خطا: {fmtNum(counts.pages_failed)}
          </small>
        </button>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("users")}>
          <span>کاربران ثبت‌نامی</span>
          <b>{fmtNum(counts.users_total)} کاربر</b>
          <small>
            فعال: {fmtNum(counts.users_active)} · پلن پولی: {fmtNum(counts.users_paid)} · نشست فعال: {fmtNum(counts.active_sessions)}
          </small>
        </button>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("plans")}>
          <span>درآمد پرداختی ثبت‌شده</span>
          <b>{fmtNum(counts.revenue_toman)} تومان</b>
          <small>مجموع توکن کل: {fmtNum(counts.tokens_used_total)}</small>
        </button>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("observability")}>
          <span>مصرف توکن امروز</span>
          <b>{fmtNum(counts.tokens_used_today)} توکن</b>
          <small>از ابتدای روز جاری (UTC) · کلیک: گزارش مصرف AI</small>
        </button>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("observability")}>
          <span>گفت‌وگوها و آزمون‌ها</span>
          <b>{fmtNum(counts.chats_total)} / {fmtNum(counts.exams_total)}</b>
          <small>گفت‌وگوی ذخیره / آزمون ساخته‌شده · کلیک: گزارش‌های AI</small>
        </button>
        <div className="admin-kpi-card">
          <span>فایل‌های ذخیره‌شده کاربران</span>
          <b>{fmtNum(counts.user_files_count)} فایل</b>
          <small>حجم اشغال‌شده: {fmtBytes(counts.user_files_bytes)}</small>
        </div>
        <button type="button" className="admin-kpi-card interactive" onClick={() => onJumpToTab("integrations")}>
          <span>تنظیمات سفارشی فعال</span>
          <b>{fmtNum(system.override_count)} مورد</b>
          <small>کلیک برای مدیریت مدل‌ها و کلیدهای API</small>
        </button>
      </div>

      {/* Urgent Review Queue */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>صفحه‌های نیازمند بازبینی یا دارای خطا</h2>
            <p>صفحه‌هایی که در استخراج یا ساختار با هشدار یا خطا روبه‌رو شده‌اند؛ برای اصلاح فوری روی هر ردیف کلیک کنید.</p>
          </div>
          <span className="step-badge">
            {counts.pages_needs_review + counts.pages_failed > 0 ? (
              <AlertTriangle size={15} />
            ) : (
              <CheckCircle2 size={15} />
            )}
          </span>
        </div>

        {needs_review_pages.length === 0 ? (
          <div className="review-tip" style={{ marginTop: 0 }}>
            <CheckCircle2 size={16} />
            <span>همهٔ صفحه‌های ثبت‌شده وضعیت سالم و تأییدشده دارند.</span>
          </div>
        ) : (
          <div className="admin-users-table-wrap">
            <table className="admin-users-table compact">
              <thead>
                <tr>
                  <th>کتاب</th>
                  <th>شماره صفحه</th>
                  <th>فصل</th>
                  <th>وضعیت</th>
                  <th>جزئیات هشدار / خطا</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {needs_review_pages.map((item) => (
                  <tr key={`${item.book_id}-${item.pdf_page_index}`}>
                    <td><b>{item.book_title}</b></td>
                    <td>
                      PDF {fmtNum(item.pdf_page_index)}
                      {item.printed_page_number !== null && (
                        <small>چاپی {fmtNum(item.printed_page_number)}</small>
                      )}
                    </td>
                    <td>{item.chapter_title || "—"}</td>
                    <td>
                      <span className={`badge-pill ${item.status}`}>
                        {item.status === "failed" ? "خطا" : "نیازمند بازبینی"}
                      </span>
                    </td>
                    <td>
                      <small>{item.error_message || item.warnings.join(" · ") || "نیازمند بررسی انسانی"}</small>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="outline-button"
                        onClick={() => onJumpToBookPage(item.book_id, item.pdf_page_index)}
                      >
                        <ArrowUpLeft size={14} /> بازبینی صفحه
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Split Telemetry: Recent Transactions + Recent Token Usage Logs */}
      <div className="user-report-split">
        <section className="admin-card">
          <div className="card-heading">
            <div>
              <h2>تراکنش‌های پرداخت اخیر</h2>
              <p>پرداخت‌های ثبت‌شده و تخصیص‌های مدیر در کل سامانه.</p>
            </div>
            <span className="step-badge"><Coins size={15} /></span>
          </div>
          {recent_transactions.length === 0 ? (
            <div className="usage-empty">هنوز تراکنش پرداختی ثبت نشده است.</div>
          ) : (
            <div className="admin-users-table-wrap user-report-scroll">
              <table className="admin-users-table compact">
                <thead>
                  <tr>
                    <th>کاربر</th>
                    <th>پلن</th>
                    <th>مبلغ (تومان)</th>
                    <th>درگاه</th>
                    <th>وضعیت</th>
                    <th>تاریخ</th>
                  </tr>
                </thead>
                <tbody>
                  {recent_transactions.map((tx) => (
                    <tr key={tx.id}>
                      <td>
                        <button
                          type="button"
                          className="admin-link-cell"
                          onClick={() => onJumpToUser(tx.user_id)}
                        >
                          <b dir="ltr">{tx.phone_number}</b>
                          <small>{tx.full_name || "بدون نام"}</small>
                        </button>
                      </td>
                      <td><b>{tx.plan_name}</b></td>
                      <td>{fmtNum(tx.amount_toman)}</td>
                      <td>{PROVIDER_LABELS[tx.provider] ?? tx.provider}</td>
                      <td>
                        <span className={`badge-pill ${tx.status === "paid" ? "done" : "failed"}`}>
                          {tx.status === "paid" ? "موفق" : tx.status}
                        </span>
                      </td>
                      <td><small>{fmtDateTime(tx.paid_at ?? tx.created_at)}</small></td>
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
              <h2>آخرین مصرف‌های هوش مصنوعی</h2>
              <p>تراکنش‌های اخیر پرسش معلم، تصویر، صدا و آزمون‌ساز.</p>
            </div>
            <span className="step-badge"><Activity size={15} /></span>
          </div>
          {recent_usage_logs.length === 0 ? (
            <div className="usage-empty">هنوز هیچ مصرفی ثبت نشده است.</div>
          ) : (
            <div className="admin-users-table-wrap user-report-scroll">
              <table className="admin-users-table compact">
                <thead>
                  <tr>
                    <th>کاربر</th>
                    <th>فعالیت</th>
                    <th>کتاب</th>
                    <th>توکن</th>
                    <th>هزینه</th>
                    <th>زمان</th>
                  </tr>
                </thead>
                <tbody>
                  {recent_usage_logs.map((log) => (
                    <tr key={log.id}>
                      <td>
                        <button
                          type="button"
                          className="admin-link-cell"
                          onClick={() => onJumpToUser(log.user_id)}
                        >
                          <b dir="ltr">{log.phone_number}</b>
                          <small>{log.full_name || "بدون نام"}</small>
                        </button>
                      </td>
                      <td><b>{ACTION_LABELS[log.action] ?? log.action}</b></td>
                      <td>{log.book_title || "—"}</td>
                      <td>{fmtNum(log.total_tokens)}</td>
                      <td>{fmtNum(log.cost_toman)}</td>
                      <td><small>{fmtDateTime(log.created_at)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Quick Navigation Footer */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>دسترسی سریع بخش‌های کنترلی</h2>
            <p>پرش مستقیم به هر بخش از مدیریت محتوا، زیرساخت، حساب‌ها و ظاهر.</p>
          </div>
        </div>
        <div className="admin-quick-nav-grid">
          <button type="button" className="outline-button" onClick={() => onJumpToTab("integrations")}>
            <Cpu size={15} /> تنظیم کلیدها و مدل‌های AI
          </button>
          <button type="button" className="outline-button" onClick={() => onJumpToTab("books")}>
            <BookOpen size={15} /> آپلود و بازبینی کتاب‌ها
          </button>
          <button type="button" className="outline-button" onClick={() => onJumpToTab("users")}>
            <Users size={15} /> مدیریت کاربران و نشست‌ها
          </button>
          <button type="button" className="outline-button" onClick={() => onJumpToTab("plans")}>
            <Coins size={15} /> قیمت توکن و پلن‌ها
          </button>
          <button type="button" className="outline-button" onClick={() => onJumpToTab("integrations")}>
            <ShieldAlert size={15} /> درگاه پیامک (OTP) و پرداخت
          </button>
          <button type="button" className="outline-button" onClick={() => onJumpToTab("appearance")}>
            <FolderOpen size={15} /> ظاهر و دسترس‌پذیری پنل
          </button>
        </div>
      </section>
    </div>
  );
}
