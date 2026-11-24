"use client";

/**
 * Phone + password authentication flow (hotfix 2026-11-22).
 *
 * One modal, four entry cards:
 *  1. `login`      mobile + password (no SMS)
 *  2. `register`   mobile → OTP → password (creates the account)
 *  3. `recover`    mobile → OTP → new password
 *  4. `code`       legacy OTP-only sign-in (kept for demo/back-compat)
 *
 * Every network call goes through `apiRequest`, so loading/duplicate-submit/CSRF/401
 * handling and server validation messages are shared with the rest of the app.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  Phone,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import { apiRequest, describeApiError, rememberCsrfToken } from "@/lib/apiClient";
import type { StudentUser } from "@/lib/types";

export type AuthMode = "login" | "register" | "recover" | "code";
type Step = "identity" | "otp" | "password";

type AuthResponse = {
  authenticated?: boolean;
  token?: string;
  user?: StudentUser | null;
  csrf_token?: string;
};

export type AuthFlowModalProps = {
  open: boolean;
  initialMode?: AuthMode;
  initialPhone?: string;
  notice?: string;
  onClose: () => void;
  onAuthenticated: (token: string, user: StudentUser | null) => void;
};

const MODE_TITLES: Record<AuthMode, { fa: string; en: string }> = {
  login: { fa: "ورود با رمز عبور", en: "Sign in with password" },
  register: { fa: "ثبت‌نام با موبایل", en: "Create an account" },
  recover: { fa: "بازیابی رمز عبور", en: "Reset your password" },
  code: { fa: "ورود با کد پیامکی", en: "Sign in with SMS code" },
};

function passwordChecks(value: string, minLength: number) {
  return [
    { key: "length", ok: value.length >= minLength, label: `حداقل ${minLength} کاراکتر` },
    { key: "letter", ok: /[A-Za-z\u0600-\u06FF]/.test(value), label: "حداقل یک حرف" },
    { key: "digit", ok: /\d/.test(value), label: "حداقل یک رقم" },
  ];
}

export default function AuthFlowModal({
  open,
  initialMode = "login",
  initialPhone = "",
  notice = "",
  onClose,
  onAuthenticated,
}: AuthFlowModalProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [step, setStep] = useState<Step>(initialMode === "register" || initialMode === "recover" ? "identity" : "identity");
  const [phone, setPhone] = useState(initialPhone);
  const [normalizedPhone, setNormalizedPhone] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fullName, setFullName] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [handshakeToken, setHandshakeToken] = useState("");
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState(notice);
  const [remember, setRemember] = useState(true);
  const phoneRef = useRef<HTMLInputElement | null>(null);

  const minPasswordLength = 8;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      // Defer the form reset one microtask: effects run after paint and microtasks run
      // before the next paint, so the dialog never paints stale fields — the reset is
      // just not synchronous inside the effect (React 19 cascading-render rule).
      await Promise.resolve();
      if (cancelled) return;
      setMode(initialMode);
      setStep("identity");
      setPhone(initialPhone);
      setNormalizedPhone("");
      setPassword("");
      setPasswordConfirm("");
      setOtpCode("");
      setHandshakeToken("");
      setDemoCode(null);
      setError("");
      setInfo(notice);
      setBusy(false);
    })();
    const timer = window.setTimeout(() => {
      // Autofocus the phone field only while the user has not already started
      // interacting with another field — never steal focus mid-typing (this used to
      // drop typed characters into the phone input when the 50ms timer fired late).
      const active = document.activeElement;
      const interacting =
        active instanceof HTMLElement &&
        (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.tagName === "SELECT");
      if (!interacting) phoneRef.current?.focus();
    }, 50);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, initialMode, initialPhone, notice]);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = window.setInterval(() => setResendIn((prev) => (prev <= 1 ? 0 : prev - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [resendIn]);

  const switchMode = useCallback((next: AuthMode) => {
    setMode(next);
    setStep("identity");
    setPassword("");
    setPasswordConfirm("");
    setOtpCode("");
    setHandshakeToken("");
    setDemoCode(null);
    setError("");
    setInfo("");
  }, []);

  const finish = useCallback(
    (payload: AuthResponse) => {
      if (payload.csrf_token) rememberCsrfToken(payload.csrf_token);
      onAuthenticated(payload.token ?? "", (payload.user ?? null) as StudentUser | null);
      onClose();
    },
    [onAuthenticated, onClose]
  );

  // --- step 1: identify -----------------------------------------------------
  async function submitIdentity(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setInfo("");
    if (!phone.trim()) {
      setError("شماره موبایل را وارد کنید.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") {
        const payload = await apiRequest<AuthResponse>("/api/v1/auth/login", {
          method: "POST",
          body: { phone_number: phone.trim(), password },
          csrf: false,
          fallbackMessage: "ورود انجام نشد.",
        });
        finish(payload);
        return;
      }

      // register / recover / code need an SMS code first
      const endpoint =
        mode === "register"
          ? "/api/v1/auth/register/request-otp"
          : mode === "recover"
          ? "/api/v1/auth/password/recover/request-otp"
          : "/api/v1/auth/request-otp";
      const payload = await apiRequest<{
        phone_number: string;
        demo_code?: string;
        resend_after_seconds?: number;
      }>(endpoint, {
        method: "POST",
        body: { phone_number: phone.trim() },
        csrf: false,
        fallbackMessage: "ارسال کد تأیید انجام نشد.",
      });
      setNormalizedPhone(payload.phone_number || phone.trim());
      setDemoCode(payload.demo_code ?? null);
      setResendIn(Number(payload.resend_after_seconds ?? 60));
      setStep("otp");
      setInfo(`کد ۶ رقمی به ${payload.phone_number || phone.trim()} ارسال شد.`);
    } catch (cause) {
      setError(describeApiError(cause, "خطا در برقراری ارتباط"));
    } finally {
      setBusy(false);
    }
  }

  // --- step 2: OTP ----------------------------------------------------------
  async function submitOtp(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setInfo("");
    if (otpCode.trim().length < 4) {
      setError("کد تأیید ۶ رقمی را وارد کنید.");
      return;
    }
    setBusy(true);
    try {
      const endpoint =
        mode === "register"
          ? "/api/v1/auth/register/verify-otp"
          : mode === "recover"
          ? "/api/v1/auth/password/recover/verify-otp"
          : "/api/v1/auth/verify-otp";
      const payload = await apiRequest<{
        verified?: boolean;
        otp_token?: string;
        token?: string;
        user?: StudentUser | null;
        csrf_token?: string;
      }>(endpoint, {
        method: "POST",
        body: { phone_number: normalizedPhone || phone.trim(), code: otpCode.trim() },
        csrf: false,
        fallbackMessage: "تأیید کد انجام نشد.",
      });

      if (mode === "code") {
        finish(payload as AuthResponse);
        return;
      }
      if (!payload.otp_token) {
        throw new Error("پاسخ سرور معتبر نبود. دوباره تلاش کنید.");
      }
      setHandshakeToken(payload.otp_token);
      setDemoCode(null);
      setStep("password");
      setInfo("کد تأیید شد. اکنون رمز عبور خود را تعیین کنید.");
    } catch (cause) {
      setError(describeApiError(cause, "کد تأیید نادرست است."));
    } finally {
      setBusy(false);
    }
  }

  async function resendOtp() {
    if (resendIn > 0 || busy) return;
    setError("");
    setBusy(true);
    try {
      const endpoint =
        mode === "register"
          ? "/api/v1/auth/register/request-otp"
          : mode === "recover"
          ? "/api/v1/auth/password/recover/request-otp"
          : "/api/v1/auth/request-otp";
      const payload = await apiRequest<{ demo_code?: string; resend_after_seconds?: number }>(
        endpoint,
        {
          method: "POST",
          body: { phone_number: normalizedPhone || phone.trim() },
          csrf: false,
          fallbackMessage: "ارسال مجدد کد انجام نشد.",
        }
      );
      setDemoCode(payload.demo_code ?? null);
      setResendIn(Number(payload.resend_after_seconds ?? 60));
      setInfo("کد تازه ارسال شد.");
    } catch (cause) {
      setError(describeApiError(cause, "ارسال مجدد کد انجام نشد."));
    } finally {
      setBusy(false);
    }
  }

  // --- step 3: password -----------------------------------------------------
  async function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setInfo("");
    if (password !== passwordConfirm) {
      setError("رمز عبور و تکرار آن یکسان نیست.");
      return;
    }
    if (password.length < minPasswordLength) {
      setError(`رمز عبور باید حداقل ${minPasswordLength} کاراکتر باشد.`);
      return;
    }
    setBusy(true);
    try {
      const endpoint =
        mode === "register" ? "/api/v1/auth/register/complete" : "/api/v1/auth/password/recover/complete";
      const payload = await apiRequest<AuthResponse>(endpoint, {
        method: "POST",
        body: {
          phone_number: normalizedPhone || phone.trim(),
          otp_token: handshakeToken,
          password,
          password_confirm: passwordConfirm,
          ...(mode === "register" && fullName.trim() ? { full_name: fullName.trim() } : {}),
        },
        csrf: false,
        fallbackMessage: "ثبت رمز عبور انجام نشد.",
      });
      finish(payload);
    } catch (cause) {
      setError(describeApiError(cause, "ثبت رمز عبور انجام نشد."));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  const title = MODE_TITLES[mode].fa;
  const checks = passwordChecks(password, minPasswordLength);
  const checkStep = step === "otp" ? 2 : step === "password" ? 3 : 1;

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(event) => {
        if (!busy && event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="exam-setup-modal otp-modal auth-flow-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-flow-title"
        dir="rtl"
      >
        <button className="modal-close icon-button" onClick={onClose} disabled={busy} aria-label="بستن">
          <X size={18} />
        </button>
        <div className="modal-icon">
          {mode === "login" ? <LockKeyhole size={22} /> : mode === "recover" ? <KeyRound size={22} /> : <Phone size={22} />}
        </div>
        <span className="eyebrow">احراز هویت درسیار</span>
        <h2 id="auth-flow-title">{title}</h2>

        <div className="auth-mode-tabs" role="tablist" aria-label="روش ورود">
          {(["login", "register", "recover"] as AuthMode[]).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={mode === item}
              className={`auth-mode-tab ${mode === item ? "active" : ""}`}
              onClick={() => switchMode(item)}
              disabled={busy}
            >
              {MODE_TITLES[item].fa}
            </button>
          ))}
        </div>

        <ol className="auth-step-indicator" aria-label="مراحل">
          {["شماره موبایل", mode === "login" ? "رمز عبور" : "کد تأیید", "رمز عبور"].map((label, index) => (
            <li
              key={`${index}-${label}`}
              className={index + 1 === checkStep ? "current" : index + 1 < checkStep ? "done" : ""}
            >
              <span>{index + 1}</span>
              {label}
            </li>
          ))}
        </ol>

        {error && <div className="inline-error" role="alert">{error}</div>}
        {!error && info && <div className="auth-info-note" role="status">{info}</div>}

        {step === "identity" && mode === "login" && (
          <form onSubmit={submitIdentity}>
            <p>شماره موبایل و رمز عبور خود را وارد کنید. برای ورود عادی پیامکی ارسال نمی‌شود.</p>
            <label className="form-field">
              <span>شماره موبایل (ایران)</span>
              <input
                ref={phoneRef}
                type="tel"
                dir="ltr"
                inputMode="tel"
                autoComplete="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="09123456789"
                required
              />
            </label>
            <label className="form-field">
              <span>رمز عبور</span>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  dir="ltr"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  required
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
            <label className="auth-remember">
              <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
              مرا روی این دستگاه به خاطر بسپار
            </label>
            <button className="primary-button modal-submit" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <LockKeyhole size={17} />}
              ورود به حساب
            </button>
            <div className="otp-footer-actions">
              <button type="button" className="text-button" onClick={() => switchMode("recover")} disabled={busy}>
                رمز عبورم را فراموش کرده‌ام
              </button>
              <button type="button" className="text-button" onClick={() => switchMode("register")} disabled={busy}>
                حساب ندارم — ثبت‌نام
              </button>
            </div>
          </form>
        )}

        {step === "identity" && mode !== "login" && (
          <form onSubmit={submitIdentity}>
            <p>
              {mode === "register"
                ? "شماره موبایل خود را وارد کنید تا کد ۶ رقمی تأیید برایتان پیامک شود. پس از تأیید، رمز عبور دلخواه خود را تعیین می‌کنید."
                : "برای بازیابی رمز عبور، شماره موبایل خود را وارد کنید تا کد تأیید ارسال شود."}
            </p>
            <label className="form-field">
              <span>شماره موبایل (ایران)</span>
              <input
                ref={phoneRef}
                type="tel"
                dir="ltr"
                inputMode="tel"
                autoComplete="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="09123456789"
                required
              />
            </label>
            {mode === "register" && (
              <label className="form-field">
                <span>نام و نام خانوادگی (اختیاری)</span>
                <input
                  type="text"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="مثلاً مهدی رضایی"
                />
              </label>
            )}
            <button className="primary-button modal-submit" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}
              ارسال کد تأیید
            </button>
          </form>
        )}

        {step === "otp" && (
          <form onSubmit={submitOtp}>
            <p>
              کد ۶ رقمی ارسال‌شده به <b dir="ltr">{normalizedPhone}</b> را وارد کنید.
            </p>
            {demoCode && (
              <div className="demo-otp-box">
                <div>
                  <b>حالت آزمایشی</b>
                  <span>
                    کد تأیید شما: <strong dir="ltr">{demoCode}</strong>
                  </span>
                </div>
                <button type="button" className="outline-button" onClick={() => setOtpCode(demoCode)}>
                  درج خودکار کد
                </button>
              </div>
            )}
            <label className="form-field">
              <span>کد تأیید ۶ رقمی</span>
              <input
                type="text"
                dir="ltr"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={otpCode}
                onChange={(event) => setOtpCode(event.target.value)}
                placeholder="123456"
                autoFocus
                required
              />
            </label>
            <button className="primary-button modal-submit" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />}
              تأیید کد
            </button>
            <div className="otp-footer-actions">
              <button type="button" className="text-button" onClick={() => setStep("identity")} disabled={busy}>
                تغییر شماره موبایل
              </button>
              <button type="button" className="text-button" disabled={resendIn > 0 || busy} onClick={() => void resendOtp()}>
                {resendIn > 0 ? `ارسال مجدد (${resendIn} ثانیه)` : "ارسال مجدد کد"}
              </button>
            </div>
          </form>
        )}

        {step === "password" && (
          <form onSubmit={submitPassword}>
            <p>
              {mode === "register"
                ? "رمز عبور حساب خود را تعیین کنید. این رمز با الگوریتم Argon2id ذخیره می‌شود و هیچ‌جا به‌صورت متن ساده نگه‌داری نمی‌شود."
                : "رمز عبور جدید خود را وارد کنید. با این کار همهٔ نشست‌های قبلی شما باطل می‌شوند."}
            </p>
            <label className="form-field">
              <span>رمز عبور</span>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  dir="ltr"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  autoFocus
                  required
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
            <ul className="password-rules">
              {checks.map((rule) => (
                <li key={rule.key} className={rule.ok ? "ok" : ""}>
                  <Check size={12} /> {rule.label}
                </li>
              ))}
            </ul>
            <label className="form-field">
              <span>تکرار رمز عبور</span>
              <input
                type={showPassword ? "text" : "password"}
                dir="ltr"
                autoComplete="new-password"
                value={passwordConfirm}
                onChange={(event) => setPasswordConfirm(event.target.value)}
                placeholder="••••••••"
                required
              />
            </label>
            <button className="primary-button modal-submit" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}
              {mode === "register" ? "تکمیل ثبت‌نام" : "ثبت رمز عبور جدید"}
            </button>
            <div className="otp-footer-actions">
              <button type="button" className="text-button" disabled={busy} onClick={() => switchMode(mode === "register" ? "login" : "recover")}>
                <ArrowRight size={13} /> بازگشت
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
