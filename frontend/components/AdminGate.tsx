"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  ShieldCheck,
} from "lucide-react";

const ADMIN_TOKEN_STORAGE_KEY = "iran_tutor_admin_token";

function readStoredAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    // Older builds stored the admin token in localStorage; drop that copy.
    window.localStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    return window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Shared admin session gate for the Phase 1 sub-pages
 * (`/admin/providers`, `/admin/observability`, `/admin/roles`).
 *
 * The admin cookie is HTTP-only; a bearer token is also kept so the panel works
 * inside a cross-site preview iframe where cookies are blocked.
 */
export default function AdminGate({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: (auth: {
    authHeaders: Record<string, string>;
    onUnauthorized: () => void;
  }) => React.ReactNode;
}) {
  const [authState, setAuthState] = useState<"checking" | "locked" | "authenticated">("checking");
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const authHeaders = useMemo<Record<string, string>>(() => {
    const headers: Record<string, string> = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      headers["X-Admin-Token"] = token;
    }
    return headers;
  }, [token]);

  const lockPanel = useCallback(() => {
    try {
      window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    } catch {
      // ignore storage errors
    }
    setToken(null);
    setAuthState("locked");
  }, []);

  useEffect(() => {
    const stored = readStoredAdminToken();
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch("/api/v1/admin/auth/session", {
          credentials: "same-origin",
          headers: stored ? { Authorization: `Bearer ${stored}` } : {},
        });
        const payload = await response.json();
        if (payload?.authenticated) {
          setToken(stored ?? null);
          setAuthState("authenticated");
        } else {
          setAuthState("locked");
        }
      } catch {
        setAuthState("locked");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/v1/admin/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        setError("نام کاربری یا رمز عبور مدیر نادرست است.");
        return;
      }
      const payload = await response.json();
      const nextToken = typeof payload.token === "string" ? payload.token : null;
      try {
        if (nextToken) window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, nextToken);
      } catch {
        // ignore storage errors
      }
      setToken(nextToken);
      setPassword("");
      setAuthState("authenticated");
    } catch {
      setError("ورود ناموفق بود. اتصال شبکه را بررسی کنید.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    try {
      await fetch("/api/v1/admin/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: authHeaders,
      });
    } finally {
      lockPanel();
    }
  }

  if (authState === "checking") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <div className="admin-login-card">
          <div className="admin-login-icon">
            <LoaderCircle size={24} className="spin" />
          </div>
          <h1>بررسی دسترسی مدیریت...</h1>
        </div>
      </main>
    );
  }

  if (authState === "locked") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <section className="admin-login-card" aria-labelledby="admin-login-title">
          <div className="admin-login-icon">
            <LockKeyhole size={24} />
          </div>
          <span className="eyebrow">دسترسی محدود</span>
          <h1 id="admin-login-title">ورود به پنل مدیریت درسیار</h1>
          <p>
            این بخش فقط برای مدیران سامانه است. دانش‌آموزان به تنظیمات هوش مصنوعی، کلیدها و
            گزارش‌ها دسترسی ندارند.
          </p>
          <form onSubmit={handleLogin} className="admin-form">
            <label className="form-field">
              <span>نام کاربری</span>
              <input
                type="text"
                dir="ltr"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
              />
            </label>
            <label className="form-field">
              <span>رمز عبور</span>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  dir="ltr"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="رمز عبور را وارد کنید"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "مخفی کردن رمز" : "نمایش رمز"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            {error && <div className="inline-error">{error}</div>}
            <button className="primary-button admin-submit" type="submit" disabled={busy}>
              {busy ? <LoaderCircle size={17} className="spin" /> : <LockKeyhole size={17} />}
              ورود به پنل مدیریت
            </button>
          </form>
          <Link href="/admin" className="admin-login-back">
            <ArrowRight size={14} /> بازگشت به پنل اصلی
          </Link>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-shell" dir="rtl">
      <header className="admin-topbar">
        <div className="admin-brand">
          <ShieldCheck size={18} />
          <span>درسیار · مدیریت</span>
        </div>
        <nav className="admin-tabs" aria-label="بخش‌های مدیریت">
          <Link className="admin-tab" href="/admin">
            <ArrowRight size={14} /> پنل اصلی
          </Link>
          <Link className="admin-tab" href="/admin/providers">
            <KeyRound size={14} /> ارائه‌دهنده‌ها
          </Link>
          <Link className="admin-tab active" href="/admin/observability">
            <Eye size={14} /> شفافیت
          </Link>
        </nav>
        <button type="button" className="admin-logout-btn" onClick={() => void handleLogout()}>
          <LogOut size={14} /> خروج
        </button>
      </header>

      <div className="admin-content">
        <div className="admin-heading">
          <div>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
        </div>
        <div className="admin-warning admin-protected-note">
          <ShieldCheck size={18} />
          <span>
            <b>دسترسی محافظت‌شده</b> · همهٔ کلیدهای API رمزنگاری‌شده ذخیره می‌شوند و هرگز در
            پاسخ‌های API بازگردانده نمی‌شوند.
          </span>
        </div>
        {children({ authHeaders, onUnauthorized: lockPanel })}
      </div>
    </main>
  );
}
