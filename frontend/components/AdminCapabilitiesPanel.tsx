"use client";

import { useCallback, useEffect, useState } from "react";

type CapabilityRow = {
  key: string;
  title_fa: string;
  description_fa: string;
  is_enabled: boolean;
  allowed_roles: string[];
  allowed_plans: string[];
  default_route_key: string | null;
};

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

/** Feature flags for the Capability Registry (admin only). */
export default function AdminCapabilitiesPanel({ authHeaders, onUnauthorized }: Props) {
  const [items, setItems] = useState<CapabilityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/admin/capabilities", {
        cache: "no-store",
        credentials: "same-origin",
        headers: authHeaders,
      });
      if (response.status === 401 || response.status === 403) {
        onUnauthorized();
        return;
      }
      if (!response.ok) throw new Error("load failed");
      const payload = (await response.json()) as { capabilities: CapabilityRow[] };
      setError("");
      setItems(payload.capabilities);
    } catch {
      setError("بارگذاری قابلیت‌ها ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, onUnauthorized]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    void load();
  }, [load]);

  async function toggle(item: CapabilityRow) {
    setBusyKey(item.key);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/api/v1/admin/capabilities/${item.key}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ is_enabled: !item.is_enabled }),
      });
      if (response.status === 401 || response.status === 403) {
        onUnauthorized();
        return;
      }
      if (!response.ok) throw new Error("toggle failed");
      setNotice(`وضعیت «${item.title_fa}» به‌روزرسانی شد. منوی دانش‌آموز در بارگذاری بعدی تغییر می‌کند.`);
      await load();
    } catch {
      setError("به‌روزرسانی قابلیت ناموفق بود.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <section className="admin-panel" dir="rtl">
      <header className="admin-panel-head">
        <h2>قابلیت‌ها و پرچم‌های فعال‌سازی</h2>
        <p>
          منوی دانش‌آموز از روی این فهرست رندر می‌شود. قابلیت‌های غیرفعال برای دانش‌آموز نمایش داده نمی‌شوند.
        </p>
      </header>
      {error && <p className="admin-error">{error}</p>}
      {notice && <p className="admin-notice">{notice}</p>}
      {loading ? (
        <p>در حال بارگذاری…</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>قابلیت</th>
              <th>کلید</th>
              <th>مسیر پیش‌فرض</th>
              <th>نقش‌های مجاز</th>
              <th>وضعیت</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.key}>
                <td>
                  <strong>{item.title_fa}</strong>
                  <div className="admin-muted">{item.description_fa}</div>
                </td>
                <td dir="ltr">{item.key}</td>
                <td dir="ltr">{item.default_route_key || "—"}</td>
                <td>{item.allowed_roles.length ? item.allowed_roles.join("، ") : "همه"}</td>
                <td>
                  <button
                    type="button"
                    className={`admin-btn ${item.is_enabled ? "primary" : ""}`}
                    disabled={busyKey === item.key}
                    onClick={() => void toggle(item)}
                    aria-pressed={item.is_enabled}
                  >
                    {item.is_enabled ? "فعال" : "غیرفعال"}
                  </button>
                  {item.key === "flashcards" && !item.is_enabled && (
                    <div className="admin-muted">تا فاز ۳ غیرفعال است.</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
