"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  Laptop,
  LoaderCircle,
  LogOut,
  Shield,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import SettingsShell from "@/components/SettingsShell";
import { formatDateTime } from "@/lib/i18n";
import type { UserSessionItem } from "@/lib/types";

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function summarizeUserAgent(ua: string | null, lang: "fa" | "en"): string {
  if (!ua) return lang === "en" ? "Browser Session" : "نشست مرورگر";
  const browser = ua.includes("Edg")
    ? "Edge"
    : ua.includes("Chrome")
    ? "Chrome"
    : ua.includes("Firefox")
    ? "Firefox"
    : ua.includes("Safari")
    ? "Safari"
    : ua.slice(0, 32);
  const os = ua.includes("Windows")
    ? "Windows"
    : ua.includes("Mac OS")
    ? "macOS"
    : ua.includes("Android")
    ? "Android"
    : ua.includes("iPhone") || ua.includes("iPad")
    ? "iOS"
    : ua.includes("Linux")
    ? "Linux"
    : "";
  return os ? `${browser} · ${os}` : browser;
}

export default function PrivacySecurityPage() {
  const {
    preferences,
    updatePreferences,
    authFetch,
    requestLogout,
    performLogoutNow,
  } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const tz = preferences.general.timezone || "Asia/Tehran";
  const privacy = preferences.privacy;

  const [sessions, setSessions] = useState<UserSessionItem[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [savingPref, setSavingPref] = useState(false);
  const [busySessionId, setBusySessionId] = useState<string | null>(null);
  const [revokingOthers, setRevokingOthers] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const fetchSessionsAsync = useCallback(async (): Promise<UserSessionItem[] | null> => {
    try {
      const res = await authFetch("/api/v1/account/sessions");
      const payload = await res.json().catch(() => ({}));
      if (res.ok && Array.isArray(payload.sessions)) {
        return payload.sessions as UserSessionItem[];
      }
      return null;
    } catch {
      return null;
    }
  }, [authFetch]);

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    const items = await fetchSessionsAsync();
    if (items) setSessions(items);
    setLoadingSessions(false);
  }, [fetchSessionsAsync]);

  useEffect(() => {
    let active = true;
    void (async () => {
      const items = await fetchSessionsAsync();
      if (!active) return;
      if (items) setSessions(items);
      setLoadingSessions(false);
    })();
    return () => {
      active = false;
    };
  }, [fetchSessionsAsync]);

  const togglePrivacy = async (key: keyof typeof privacy, value: boolean) => {
    setSavingPref(true);
    setFeedback("");
    setError("");
    try {
      await updatePreferences({ privacy: { [key]: value } });
      setFeedback(
        lang === "en"
          ? "Privacy preference saved."
          : "تنظیمات حریم خصوصی ذخیره شد."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Failed to save preference."
          : "ذخیره تنظیمات انجام نشد."
      );
    } finally {
      setSavingPref(false);
    }
  };

  const handleRevokeSession = async (sessionId: string) => {
    setBusySessionId(sessionId);
    setError("");
    setFeedback("");
    try {
      const res = await authFetch(`/api/v1/account/sessions/${sessionId}`, {
        method: "DELETE",
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to revoke session." : "لغو نشست انجام نشد."
          )
        );
      }
      if (payload.revoked_current) {
        await performLogoutNow();
        return;
      }
      setFeedback(
        lang === "en" ? "Session revoked." : "نشست انتخاب‌شده با موفقیت بسته شد."
      );
      await loadSessions();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Error revoking session."
          : "خطا در بستن نشست"
      );
    } finally {
      setBusySessionId(null);
    }
  };

  const handleRevokeOthers = async () => {
    setRevokingOthers(true);
    setError("");
    setFeedback("");
    try {
      const res = await authFetch("/api/v1/account/sessions/revoke-others", {
        method: "POST",
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to revoke sessions." : "بستن سایر نشست‌ها انجام نشد."
          )
        );
      }
      setFeedback(
        lang === "en"
          ? `Revoked ${payload.revoked_count ?? 0} other session(s).`
          : `${payload.revoked_count ?? 0} نشست دیگر با موفقیت بسته شد.`
      );
      await loadSessions();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Error revoking sessions."
          : "خطا در بستن سایر نشست‌ها"
      );
    } finally {
      setRevokingOthers(false);
    }
  };

  const activeOthersCount = sessions.filter((s) => s.is_active && !s.is_current).length;

  return (
    <SettingsShell>
      <div className="settings-stack">
        {/* Privacy Controls */}
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Shield size={16} />{" "}
                {lang === "en" ? "Data & Privacy Controls" : "کنترل داده‌ها و حریم خصوصی"}
              </h2>
              <p>
                {lang === "en"
                  ? "Control how Darsyar retains your chat history, uploaded attachments, and phone display."
                  : "نحوهٔ ذخیرهٔ تاریخچه گفت‌وگوها، فایل‌های پیوست‌شده به معلم و نمایش شماره موبایل را کنترل کنید."}
              </p>
            </div>
            {savingPref && <LoaderCircle className="spin" size={16} />}
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>
                {lang === "en"
                  ? "Save New Chat History"
                  : "ذخیره خودکار تاریخچه گفت‌وگوها"}
              </b>
              <small>
                {lang === "en"
                  ? "When off, new classroom conversations stay only in your active tab and are not persisted."
                  : "در صورت غیرفعال کردن، گفت‌وگوهای تازه در تاریخچه حساب ذخیره نمی‌شوند."}
              </small>
            </div>
            <label className="switch-control">
              <input
                type="checkbox"
                checked={privacy.save_chat_history}
                onChange={(e) => void togglePrivacy("save_chat_history", e.target.checked)}
              />
              <span className="switch-track" />
            </label>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>
                {lang === "en"
                  ? "Store Tutor Image & Voice Attachments"
                  : "نگهداری پیوست‌های تصویر و صدای معلم در حافظه شخصی"}
              </b>
              <small>
                {lang === "en"
                  ? "When on, uploaded question images and recordings are saved under Storage & Data so you can inspect or delete them."
                  : "با فعال بودن، تصویر تمرین و صدای ارسالی شما در بخش «حافظه و داده‌ها» ذخیره و قابل مدیریت می‌شود."}
              </small>
            </div>
            <label className="switch-control">
              <input
                type="checkbox"
                checked={privacy.store_uploaded_attachments}
                onChange={(e) =>
                  void togglePrivacy("store_uploaded_attachments", e.target.checked)
                }
              />
              <span className="switch-track" />
            </label>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>
                {lang === "en"
                  ? "Mask Mobile Number in Account Header"
                  : "نمایش ماسک‌شده شماره موبایل در منوی کاربری"}
              </b>
              <small>
                {lang === "en"
                  ? "Hide middle digits (e.g. 0912***6789) inside menus and headers."
                  : "نمایش شماره به صورت پوشیده‌شده (مانند ۰۹۱۲***۶۷۸۹) در منوی حساب."}
              </small>
            </div>
            <label className="switch-control">
              <input
                type="checkbox"
                checked={privacy.show_phone_masked}
                onChange={(e) => void togglePrivacy("show_phone_masked", e.target.checked)}
              />
              <span className="switch-track" />
            </label>
          </div>
        </section>

        {feedback && (
          <div className="success-note">
            <Check size={16} />
            <span>{feedback}</span>
          </div>
        )}
        {error && <div className="inline-error">{error}</div>}

        {/* Active Sessions */}
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Laptop size={16} />{" "}
                {lang === "en" ? "Active Sessions & Devices" : "نشست‌های فعال و دستگاه‌ها"}
              </h2>
              <p>
                {lang === "en"
                  ? "Revoking a session immediately invalidates its authentication token on the server."
                  : "با بستن هر نشست، توکن آن بلافاصله در سرور باطل می‌شود."}
              </p>
            </div>
            {activeOthersCount > 0 && (
              <button
                type="button"
                className="outline-button"
                disabled={revokingOthers}
                onClick={() => void handleRevokeOthers()}
              >
                {revokingOthers ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <ShieldAlert size={14} />
                )}
                <span>
                  {lang === "en" ? "Sign out other sessions" : "بستن سایر نشست‌ها"}
                </span>
              </button>
            )}
          </div>

          {loadingSessions ? (
            <div className="account-loading-box">
              <LoaderCircle className="spin" size={20} />
              <span>{lang === "en" ? "Loading sessions..." : "در حال دریافت نشست‌ها..."}</span>
            </div>
          ) : sessions.length === 0 ? (
            <div className="history-empty">
              <span>
                {lang === "en"
                  ? "No tracked sessions recorded for this account yet."
                  : "هنوز نشستی برای این حساب ثبت نشده است."}
              </span>
            </div>
          ) : (
            <div className="sessions-list">
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`session-row ${s.is_current ? "current" : ""} ${
                    !s.is_active ? "revoked" : ""
                  }`}
                >
                  <div className="session-row-main">
                    <div className="session-row-top">
                      <b>{summarizeUserAgent(s.user_agent, lang)}</b>
                      {s.is_current && (
                        <span className="plan-pill">
                          {lang === "en" ? "Current Session" : "نشست فعلی"}
                        </span>
                      )}
                      {!s.is_active && (
                        <span className="badge-pill failed">
                          {s.revoked_at
                            ? lang === "en"
                              ? "Revoked"
                              : "باطل‌شده"
                            : lang === "en"
                            ? "Expired"
                            : "منقضی‌شده"}
                        </span>
                      )}
                    </div>
                    <small>
                      {s.ip_address ? `IP: ${s.ip_address} · ` : ""}
                      {lang === "en" ? "Last active:" : "آخرین فعالیت:"}{" "}
                      {formatDateTime(s.last_seen_at ?? s.created_at, lang, tz)}
                    </small>
                  </div>
                  {s.is_active && (
                    <button
                      type="button"
                      className="outline-button danger-outline"
                      disabled={busySessionId === s.id}
                      onClick={() => void handleRevokeSession(s.id)}
                    >
                      {busySessionId === s.id ? (
                        <LoaderCircle className="spin" size={14} />
                      ) : (
                        <Trash2 size={14} />
                      )}
                      <span>
                        {s.is_current
                          ? lang === "en"
                            ? "Log Out"
                            : "خروج"
                          : lang === "en"
                          ? "Revoke"
                          : "لغو نشست"}
                      </span>
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Sign Out Card */}
        <section className="account-card">
          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Log out from this device" : "خروج از حساب کاربری"}</b>
              <small>
                {lang === "en"
                  ? "Immediately revoke your current session token and return to the login gate."
                  : "ابطال نشست فعلی در سرور، پاک‌سازی وضعیت محلی و بازگشت به صفحه ورود."}
              </small>
            </div>
            <button type="button" className="danger-button" onClick={requestLogout}>
              <LogOut size={16} />
              <span>{lang === "en" ? "Log Out" : "خروج از حساب کاربری"}</span>
            </button>
          </div>
        </section>
      </div>
    </SettingsShell>
  );
}
