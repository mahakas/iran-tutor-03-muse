"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Gauge,
  LoaderCircle,
  RefreshCw,
  Save,
  ShieldCheck,
  Users,
} from "lucide-react";

export type AdminRoleUser = {
  id: string;
  phone_number?: string;
  full_name?: string | null;
  role?: string;
  grade_level?: number | null;
  major?: string | null;
  plan_id?: number | null;
  is_active?: boolean;
};

type QuotaPolicy = {
  daily_tokens: number;
  monthly_tokens: number;
  daily_requests: number;
  requests_per_minute: number;
};

type FeatureOverrides = Record<string, Partial<QuotaPolicy>>;

const ROLE_LABELS: Record<string, string> = {
  admin: "مدیر",
  teacher: "معلم",
  student: "دانش‌آموز",
  guardian: "ولی",
};

const MAJOR_LABELS: Record<string, string> = {
  math_physics: "ریاضی‌فیزیک",
  experimental: "علوم تجربی",
  humanities: "علوم انسانی",
};

const POLICY_FIELDS: { key: keyof QuotaPolicy; label: string; hint: string }[] = [
  { key: "daily_tokens", label: "سقف توکن روزانه", hint: "برای هر کاربر و هر قابلیت در هر روز" },
  { key: "monthly_tokens", label: "سقف توکن ماهانه", hint: "برای هر کاربر و هر قابلیت در هر ماه" },
  { key: "daily_requests", label: "سقف درخواست روزانه", hint: "قبل از هر فراخوانی بررسی می‌شود" },
  { key: "requests_per_minute", label: "سقف درخواست در دقیقه", hint: "پنجرهٔ لغزان Redis" },
];

export default function AdminRolesQuotasPanel({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [policy, setPolicy] = useState<QuotaPolicy | null>(null);
  const [defaults, setDefaults] = useState<QuotaPolicy | null>(null);
  const [overrides, setOverrides] = useState<FeatureOverrides>({});
  const [overrideKey, setOverrideKey] = useState("");
  const [overrideDraft, setOverrideDraft] = useState<Record<string, string>>({});
  const [savingOverride, setSavingOverride] = useState(false);
  const [users, setUsers] = useState<AdminRoleUser[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [busyUser, setBusyUser] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const handle = useCallback(
    (status: number) => {
      if (status === 401) onUnauthorized();
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [policyRes, usersRes] = await Promise.all([
        fetch("/api/v1/admin/quotas", { credentials: "same-origin", headers: authHeaders }),
        fetch("/api/v1/admin/users?limit=50", {
          credentials: "same-origin",
          headers: authHeaders,
        }),
      ]);
      if (!handle(policyRes.status) || !handle(usersRes.status)) {
        setError("دسترسی مدیریت منقضی شده است.");
        return;
      }
      const policyPayload = await policyRes.json();
      setPolicy(policyPayload.policy as QuotaPolicy);
      setDefaults(policyPayload.defaults as QuotaPolicy);
      setOverrides((policyPayload.feature_overrides ?? {}) as FeatureOverrides);
      const usersPayload = await usersRes.json();
      const rows = Array.isArray(usersPayload)
        ? usersPayload
        : (usersPayload.users ?? usersPayload.items ?? []);
      setUsers(rows as AdminRoleUser[]);
    } catch {
      setError("بارگذاری اطلاعات کاربران ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, handle]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function saveOverride(event: React.FormEvent) {
    event.preventDefault();
    const key = overrideKey.trim();
    const fields: Record<string, number> = {};
    for (const field of POLICY_FIELDS) {
      const raw = (overrideDraft[field.key] ?? "").trim();
      if (raw !== "") fields[field.key] = Math.max(0, Math.floor(Number(raw)) || 0);
    }
    if (!key || Object.keys(fields).length === 0) {
      setError("کلید قابلیت و حداقل یک سقف را وارد کنید (خالی = ارث‌بری از سقف کلی).");
      return;
    }
    setSavingOverride(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/v1/admin/quotas/features/${encodeURIComponent(key)}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(fields),
      });
      if (!handle(response.status) || !response.ok) {
        setError("ذخیرهٔ سقف اختصاصی قابلیت ناموفق بود (کلید را بررسی کنید).");
        return;
      }
      setMessage(`سقف اختصاصی «${key}» ذخیره شد.`);
      setOverrideDraft({});
      setOverrideKey("");
      await load();
    } finally {
      setSavingOverride(false);
    }
  }

  async function removeOverride(key: string) {
    setError("");
    setMessage("");
    const response = await fetch(`/api/v1/admin/quotas/features/${encodeURIComponent(key)}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (!handle(response.status) || !response.ok) {
      setError("حذف سقف اختصاصی ناموفق بود.");
      return;
    }
    setMessage(`سقف اختصاصی «${key}» حذف شد و به سقف کلی برمی‌گردد.`);
    await load();
  }

  async function savePolicy(event: React.FormEvent) {
    event.preventDefault();
    if (!policy) return;
    setSavingPolicy(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/v1/admin/quotas", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(policy),
      });
      if (!handle(response.status)) {
        setError("ذخیرهٔ سیاست سهمیه ناموفق بود.");
        return;
      }
      setMessage("سیاست سهمیه و نرخ ذخیره شد.");
      await load();
    } finally {
      setSavingPolicy(false);
    }
  }

  async function updateUser(
    userId: string,
    patch: Partial<Pick<AdminRoleUser, "role" | "is_active">>,
  ) {
    setBusyUser(userId);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/v1/admin/users/${userId}/role`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(patch),
      });
      if (!handle(response.status)) {
        const detail = await response.json().catch(() => ({}));
        setError(detail?.detail ?? "به‌روزرسانی نقش ناموفق بود.");
        return;
      }
      const payload = await response.json();
      setUsers((prev) =>
        prev.map((user) =>
          user.id === userId ? { ...user, ...(payload.user as AdminRoleUser) } : user,
        ),
      );
      setMessage("نقش و دسترسی کاربر به‌روزرسانی شد.");
    } finally {
      setBusyUser(null);
    }
  }

  const visibleUsers = users.filter((user) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return (
      (user.full_name ?? "").toLowerCase().includes(term) ||
      (user.phone_number ?? "").includes(term) ||
      user.id.toLowerCase().includes(term)
    );
  });

  if (loading) {
    return (
      <div className="admin-card admin-empty">
        <div>
          <LoaderCircle size={22} className="spin" />
        </div>
        <b>بارگذاری نقش‌ها و سهمیه‌ها…</b>
      </div>
    );
  }

  return (
    <div className="admin-billing-stack">
      {message && (
        <div className="success-note admin-banner">
          <CheckCircle2 size={15} />
          {message}
        </div>
      )}
      {error && <div className="inline-error admin-banner">{error}</div>}

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>سیاست سهمیه و محدودسازی نرخ</h2>
            <p>
              قبل از هر فراخوانی هوش مصنوعی، این محدودیت‌ها اعمال می‌شوند. مقادیر در تنظیمات
              سامانه ذخیره می‌شوند و بلافاصله فعال می‌گردند.
            </p>
          </div>
          <div className="admin-chip-row">
            {defaults && (
              <button
                type="button"
                className="admin-theme-chip"
                onClick={() => setPolicy({ ...defaults })}
              >
                بازگردانی پیش‌فرض
              </button>
            )}
            <span className="step-badge">
              <Gauge size={14} />
            </span>
          </div>
        </div>

        {policy && (
          <form className="admin-form" onSubmit={savePolicy}>
            <div className="admin-grid">
              {POLICY_FIELDS.map((field) => (
                <label key={field.key} className="form-field">
                  <span>
                    {field.label} <small className="admin-muted">({field.hint})</small>
                  </span>
                  <input
                    dir="ltr"
                    type="number"
                    min={0}
                    value={policy[field.key]}
                    onChange={(event) =>
                      setPolicy({ ...policy, [field.key]: Number(event.target.value) || 0 })
                    }
                  />
                </label>
              ))}
            </div>
            <button className="primary-button admin-submit" type="submit" disabled={savingPolicy}>
              {savingPolicy ? <LoaderCircle size={17} className="spin" /> : <Save size={17} />}
              ذخیرهٔ سیاست سهمیه
            </button>
          </form>
        )}
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>سقف مصرف به‌تفکیک قابلیت</h2>
            <p>
              برای هر قابلیت (کلید مثل <code dir="ltr">quiz</code> یا <code dir="ltr">chat</code>) می‌توانید
              سقف اختصاصی تعیین کنید. فیلد خالی یعنی همان مقدار سقف کلی. شمارنده‌ها جدا از هم هستند.
            </p>
          </div>
        </div>

        {Object.keys(overrides).length === 0 ? (
          <p className="admin-muted">هنوز سقف اختصاصی‌ای ثبت نشده است.</p>
        ) : (
          <ul className="admin-list">
            {Object.entries(overrides).map(([key, values]) => (
              <li key={key} className="admin-row">
                <strong dir="ltr">{key}</strong>
                <span dir="ltr">
                  {Object.entries(values)
                    .map(([name, value]) => `${name}=${value}`)
                    .join("  ")}
                </span>
                <button type="button" className="admin-theme-chip" onClick={() => void removeOverride(key)}>
                  حذف
                </button>
              </li>
            ))}
          </ul>
        )}

        <form className="admin-form" onSubmit={saveOverride}>
          <div className="admin-grid">
            <label className="form-field">
              <span>کلید قابلیت</span>
              <input
                dir="ltr"
                type="text"
                placeholder="quiz"
                value={overrideKey}
                onChange={(event) => setOverrideKey(event.target.value)}
              />
            </label>
            {POLICY_FIELDS.map((field) => (
              <label key={field.key} className="form-field">
                <span>
                  {field.label} <small className="admin-muted">(خالی = کلی)</small>
                </span>
                <input
                  dir="ltr"
                  type="number"
                  min={0}
                  value={overrideDraft[field.key] ?? ""}
                  onChange={(event) =>
                    setOverrideDraft({ ...overrideDraft, [field.key]: event.target.value })
                  }
                />
              </label>
            ))}
          </div>
          <button className="primary-button admin-submit" type="submit" disabled={savingOverride}>
            {savingOverride ? <LoaderCircle size={17} className="spin" /> : <Save size={17} />}
            ذخیرهٔ سقف اختصاصی
          </button>
        </form>
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>کاربران، نقش‌ها و سطوح دسترسی</h2>
            <p>
              نقش‌ها: مدیر، معلم، دانش‌آموز، ولی. فقط نقش «مدیر» به بخش مدیریت دسترسی دارد؛
              دانش‌آموز هرگز نمی‌تواند به تنظیمات هوش مصنوعی دست پیدا کند.
            </p>
          </div>
          <div className="admin-chip-row">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="جست‌وجوی نام یا شماره…"
            />
            <button type="button" className="admin-theme-chip" onClick={() => void load()}>
              <RefreshCw size={14} /> بازخوانی
            </button>
          </div>
        </div>

        {visibleUsers.length === 0 ? (
          <div className="admin-empty">
            <div>
              <Users size={22} />
            </div>
            <b>کاربری یافت نشد</b>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>کاربر</th>
                  <th>نقش</th>
                  <th>پایه</th>
                  <th>رشته</th>
                  <th>وضعیت</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleUsers.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <b>{user.full_name || "بدون نام"}</b>
                      <div className="admin-muted" dir="ltr">
                        {user.phone_number ?? user.id}
                      </div>
                      <a className="admin-chip-btn" href={`/admin/users/${user.id}`} style={{ marginTop: 6, display: "inline-flex" }}>
                        پروندهٔ حافظه
                      </a>
                    </td>
                    <td>
                      <select
                        value={user.role ?? "student"}
                        onChange={(event) =>
                          void updateUser(user.id, { role: event.target.value })
                        }
                        disabled={busyUser === user.id}
                      >
                        {Object.entries(ROLE_LABELS).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <span className="admin-muted">
                        {user.grade_level ? `پایهٔ ${user.grade_level}` : "—"}
                      </span>
                    </td>
                    <td>
                      <span className="admin-muted">
                        {user.major ? MAJOR_LABELS[user.major] ?? user.major : "—"}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`admin-theme-chip ${user.is_active === false ? "" : "active"}`}
                        onClick={() =>
                          void updateUser(user.id, { is_active: !(user.is_active !== false) })
                        }
                        disabled={busyUser === user.id}
                      >
                        <ShieldCheck size={14} />
                        {user.is_active === false ? "غیرفعال" : "فعال"}
                      </button>
                    </td>
                    <td>
                      {busyUser === user.id && <LoaderCircle size={14} className="spin" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
