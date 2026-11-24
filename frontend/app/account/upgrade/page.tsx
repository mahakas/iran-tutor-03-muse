"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarClock,
  Check,
  Clock3,
  Coins,
  Crown,
  HardDrive,
  LoaderCircle,
  ReceiptText,
  Zap,
} from "lucide-react";
import AccountShell from "@/components/AccountShell";
import { useAppContext } from "@/components/AppProvider";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/i18n";
import type {
  PaymentTransactionItem,
  PublicPlansPayload,
  StudentUser,
  TokenUsageLogItem,
} from "@/lib/types";

function actionLabel(action: string, lang: "fa" | "en"): string {
  if (lang === "en") {
    switch (action) {
      case "tutor_ask":
        return "Text Question";
      case "tutor_image":
        return "Image Problem";
      case "tutor_audio":
        return "Voice Question";
      case "exam_create":
        return "Timed Exam";
      default:
        return action;
    }
  }
  switch (action) {
    case "tutor_ask":
      return "پرسش متنی از معلم";
    case "tutor_image":
      return "حل تمرین تصویری";
    case "tutor_audio":
      return "پرسش صوتی";
    case "exam_create":
      return "طراحی آزمون زمان‌دار";
    default:
      return action;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

export default function UpgradePlanPage() {
  const { user, preferences, authFetch, setUser, refreshAccount } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const tz = preferences.general.timezone || "Asia/Tehran";
  const userId = user?.id ?? null;

  const [plansPayload, setPlansPayload] = useState<PublicPlansPayload | null>(null);
  const [usageLogs, setUsageLogs] = useState<TokenUsageLogItem[]>([]);
  const [paymentTxs, setPaymentTxs] = useState<PaymentTransactionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [checkoutCode, setCheckoutCode] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const fetchPlansAndUsage = useCallback(async () => {
    const [plansRes, usageRes] = await Promise.all([
      fetch("/api/v1/plans", { cache: "no-store" }),
      userId ? authFetch("/api/v1/plans/usage") : Promise.resolve(null),
    ]);
    const plansJson = plansRes.ok ? ((await plansRes.json()) as PublicPlansPayload) : null;
    const usageJson =
      usageRes && usageRes.ok
        ? ((await usageRes.json()) as {
            user?: StudentUser;
            logs?: TokenUsageLogItem[];
            transactions?: PaymentTransactionItem[];
          })
        : null;
    return { plansJson, usageJson };
  }, [authFetch, userId]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const { plansJson, usageJson } = await fetchPlansAndUsage();
      if (plansJson) setPlansPayload(plansJson);
      if (usageJson) {
        if (usageJson.user) setUser(usageJson.user);
        setUsageLogs(usageJson.logs ?? []);
        setPaymentTxs(usageJson.transactions ?? []);
      }
    } catch {
      setError(
        lang === "en"
          ? "Failed to load subscription plans from the server."
          : "دریافت اطلاعات پلن‌ها از سرور انجام نشد."
      );
    } finally {
      setLoading(false);
    }
  }, [fetchPlansAndUsage, lang, setUser]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { plansJson, usageJson } = await fetchPlansAndUsage();
        if (!active) return;
        if (plansJson) setPlansPayload(plansJson);
        if (usageJson) {
          if (usageJson.user) setUser(usageJson.user);
          setUsageLogs(usageJson.logs ?? []);
          setPaymentTxs(usageJson.transactions ?? []);
        }
      } catch {
        if (active) {
          setError(
            lang === "en"
              ? "Failed to load subscription plans from the server."
              : "دریافت اطلاعات پلن‌ها از سرور انجام نشد."
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [fetchPlansAndUsage, lang, setUser]);

  // Handle gateway callback query params if returning from payment
  useEffect(() => {
    if (!userId || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const authority = params.get("Authority");
    const status = params.get("Status");
    const paymentTx = params.get("payment_tx");
    if (!authority) return;

    void (async () => {
      setError("");
      try {
        const qs = new URLSearchParams({ Authority: authority });
        if (status) qs.set("Status", status);
        if (paymentTx) qs.set("payment_tx", paymentTx);
        const res = await authFetch(`/api/v1/plans/verify?${qs.toString()}`);
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(
            errorMessage(
              payload,
              lang === "en" ? "Payment verification failed." : "تأیید پرداخت انجام نشد."
            )
          );
        }
        if (payload.user) setUser(payload.user as StudentUser);
        setFeedback(
          lang === "en"
            ? `Payment verified (Ref: ${payload.ref_id ?? "—"}). Plan updated.`
            : `پرداخت با موفقیت تأیید شد (کد پیگیری: ${payload.ref_id ?? "—"}). پلن شما فعال شد.`
        );
        window.history.replaceState({}, "", "/account/upgrade");
        await loadData();
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : lang === "en"
            ? "Payment verification failed."
            : "تأیید پرداخت با خطا مواجه شد."
        );
      }
    })();
  }, [authFetch, lang, loadData, setUser, userId]);

  const handleCheckout = async (planCode: string) => {
    setError("");
    setFeedback("");
    setCheckoutCode(planCode);
    try {
      const res = await authFetch("/api/v1/plans/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_code: planCode,
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Unable to start checkout." : "ایجاد درخواست پرداخت انجام نشد."
          )
        );
      }
      if (payload.status === "paid") {
        if (payload.user) {
          setUser(payload.user as StudentUser);
        } else {
          await refreshAccount();
        }
        setFeedback(
          lang === "en"
            ? `Plan "${payload.plan?.name ?? planCode}" activated successfully (Ref: ${payload.ref_id ?? "DEMO"}).`
            : `پلن «${payload.plan?.name ?? planCode}» با موفقیت فعال شد (کد پیگیری: ${payload.ref_id ?? "DEMO"}).`
        );
        await loadData();
      } else if (payload.mode === "demo" && payload.authority) {
        const verifyRes = await authFetch("/api/v1/plans/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            authority: payload.authority,
            transaction_id: payload.transaction_id,
            status: "OK",
          }),
        });
        const verifyPayload = await verifyRes.json().catch(() => ({}));
        if (!verifyRes.ok) {
          throw new Error(
            errorMessage(
              verifyPayload,
              lang === "en" ? "Plan activation failed." : "فعال‌سازی پلن انجام نشد."
            )
          );
        }
        if (verifyPayload.user) {
          setUser(verifyPayload.user as StudentUser);
        } else {
          await refreshAccount();
        }
        setFeedback(
          lang === "en"
            ? `Plan "${payload.plan?.name ?? planCode}" activated successfully (Ref: ${verifyPayload.ref_id ?? "DEMO"}).`
            : `پلن «${payload.plan?.name ?? planCode}» با موفقیت فعال شد (کد پیگیری: ${verifyPayload.ref_id ?? "DEMO"}).`
        );
        await loadData();
      } else if (payload.payment_url) {
        window.location.assign(String(payload.payment_url));
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Checkout failed."
          : "خطا در فرآیند خرید پلن"
      );
    } finally {
      setCheckoutCode(null);
    }
  };

  const tokenPct =
    user && user.tokens_total > 0
      ? Math.min(100, Math.max(0, Math.round((user.tokens_remaining / user.tokens_total) * 100)))
      : 0;

  return (
    <AccountShell
      title={lang === "en" ? "Upgrade Plan & Billing" : "ارتقای پلن و اشتراک"}
      subtitle={
        lang === "en"
          ? "Compare active Darsyar plans, inspect live token & storage quotas, and activate or renew your subscription."
          : "پلن‌های فعال درسیار را مقایسه کنید، اعتبار توکن و سهمیهٔ فضای ذخیره‌سازی را ببینید و اشتراک خود را ارتقا دهید."
      }
      requireAuth
    >
      {user && (
        <section className="account-card subscription-summary-card">
          <div className="subscription-summary-head">
            <div>
              <span className="eyebrow">
                {lang === "en" ? "Current Subscription" : "اشتراک فعلی شما"}
              </span>
              <div className="subscription-title-row">
                <h2>{user.plan_title}</h2>
                <span className={`plan-pill ${user.plan_code}`}>
                  {user.is_expired
                    ? lang === "en"
                      ? "Expired"
                      : "منقضی‌شده"
                    : lang === "en"
                    ? "Active"
                    : "فعال"}
                </span>
              </div>
            </div>
            <div className="subscription-dates">
              <div>
                <CalendarClock size={14} />
                <span>
                  {lang === "en" ? "Started:" : "شروع:"}{" "}
                  <b>{formatDateTime(user.plan_started_at, lang, tz)}</b>
                </span>
              </div>
              <div>
                <Clock3 size={14} />
                <span>
                  {lang === "en" ? "Expires:" : "انقضا:"}{" "}
                  <b>{formatDateTime(user.plan_expires_at, lang, tz)}</b>
                </span>
              </div>
            </div>
          </div>

          <div className="subscription-metrics-grid">
            <div className="metric-box">
              <span>{lang === "en" ? "Tokens Remaining" : "توکن باقی‌مانده"}</span>
              <strong>
                {formatNumber(user.tokens_remaining, lang)}{" "}
                <small>/ {formatNumber(user.tokens_total, lang)}</small>
              </strong>
              <div className="account-quota-bar">
                <span style={{ width: `${tokenPct}%` }} />
              </div>
            </div>
            <div className="metric-box">
              <span>{lang === "en" ? "Days Remaining" : "روز باقی‌مانده"}</span>
              <strong>
                {user.is_expired
                  ? lang === "en"
                    ? "0 (Expired)"
                    : "۰ (منقضی)"
                  : `${formatNumber(user.days_remaining, lang)} ${lang === "en" ? "days" : "روز"}`}
              </strong>
              <small>
                {lang === "en"
                  ? "Valid tokens carry over on upgrade before expiry."
                  : "در ارتقای پیش از انقضا، توکن‌های معتبر به دورهٔ جدید منتقل می‌شوند."}
              </small>
            </div>
            <div className="metric-box">
              <span>{lang === "en" ? "Personal Storage Quota" : "سهمیه فضای ذخیره‌سازی"}</span>
              <strong>{formatBytes(user.storage_quota_bytes, lang)}</strong>
              <Link href="/account/settings/storage" className="account-mini-link">
                {lang === "en" ? "Inspect Storage & Data" : "مدیریت حافظه و فایل‌ها"}
              </Link>
            </div>
          </div>

          {user.is_expired && (
            <div className="warning-banner">
              <AlertTriangle size={16} />
              <span>
                {lang === "en"
                  ? "Your current plan has expired. Select a plan below to restore full access."
                  : "مهلت اعتبار اشتراک فعلی به پایان رسیده است. برای ادامه استفاده یکی از پلن‌ها را فعال کنید."}
              </span>
            </div>
          )}
        </section>
      )}

      {feedback && (
        <div className="success-note plans-notice account-notice-box">
          <Check size={16} />
          <span>{feedback}</span>
        </div>
      )}
      {error && <div className="inline-error plans-notice">{error}</div>}

      {loading && !plansPayload ? (
        <div className="account-card account-loading-box">
          <LoaderCircle className="spin" size={22} />
          <span>{lang === "en" ? "Loading plans..." : "در حال دریافت پلن‌ها..."}</span>
        </div>
      ) : (
        <>
          <section className="plans-grid account-plans-grid">
            {(plansPayload?.plans ?? []).map((plan) => {
              const isCurrent = user?.plan_code === plan.code && !user.is_expired;
              return (
                <article
                  key={plan.code}
                  className={`plan-card ${plan.code === "pro" ? "featured" : ""}`}
                >
                  <div className="plan-card-top">
                    <h3>
                      {lang === "en" ? plan.name : `پلن ${plan.name}`}
                    </h3>
                    {plan.code === "pro" && (
                      <span className="plan-tag">
                        {lang === "en" ? "Recommended" : "پیشنهادی"}
                      </span>
                    )}
                    {isCurrent && (
                      <span className="plan-tag active">
                        {lang === "en" ? "Current Plan" : "پلن فعلی"}
                      </span>
                    )}
                  </div>
                  <div className="plan-price">
                    <strong>{formatNumber(plan.price_toman, lang)}</strong>
                    <span>{lang === "en" ? "Toman" : "تومان"}</span>
                  </div>
                  <p className="plan-desc">{plan.description}</p>
                  <ul className="plan-specs">
                    <li>
                      <Coins size={14} />
                      {lang === "en" ? "Token quota:" : "سهمیه:"}{" "}
                      <b>
                        {formatNumber(plan.token_quota, lang)}{" "}
                        {lang === "en" ? "tokens" : "توکن"}
                      </b>
                    </li>
                    <li>
                      <HardDrive size={14} />
                      {lang === "en" ? "Personal storage:" : "فضای ذخیره‌سازی:"}{" "}
                      <b>{formatBytes(plan.storage_quota_bytes, lang)}</b>
                    </li>
                    <li>
                      <Clock3 size={14} />
                      {lang === "en" ? "Validity:" : "مدت اعتبار:"}{" "}
                      <b>
                        {formatNumber(plan.duration_days, lang)}{" "}
                        {lang === "en" ? "days" : "روز"}
                      </b>
                    </li>
                    <li>
                      <Zap size={14} />
                      {lang === "en" ? "Effective rate:" : "تعرفهٔ مؤثر:"}{" "}
                      <b>
                        {formatNumber(plan.effective_toman_per_1k, lang)}{" "}
                        {lang === "en" ? "Toman / 1K" : "تومان / ۱٬۰۰۰ توکن"}
                      </b>
                    </li>
                  </ul>
                  <button
                    type="button"
                    className="primary-button plan-buy-btn"
                    disabled={checkoutCode !== null}
                    onClick={() => void handleCheckout(plan.code)}
                  >
                    {checkoutCode === plan.code ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Crown size={16} />
                    )}
                    {plansPayload?.payment_mode === "demo"
                      ? lang === "en"
                        ? isCurrent
                          ? "Renew Plan (Demo)"
                          : "Activate Plan (Demo)"
                        : isCurrent
                        ? "تمدید آنی پلن (دمو)"
                        : "فعال‌سازی آنی پلن (دمو)"
                      : lang === "en"
                      ? isCurrent
                        ? "Renew & Pay"
                        : "Pay & Activate"
                      : isCurrent
                      ? "تمدید و پرداخت"
                      : "پرداخت و فعال‌سازی"}
                  </button>
                </article>
              );
            })}
          </section>

          {plansPayload && plansPayload.plans.length > 0 && (
            <section className="account-card">
              <div className="account-card-head">
                <h2>{lang === "en" ? "Plan Comparison" : "جدول مقایسه پلن‌ها"}</h2>
                <small>
                  {lang === "en"
                    ? `Base token rate: ${formatNumber(plansPayload.token_price_per_1k_toman, lang)} Toman / 1K tokens`
                    : `نرخ پایه محاسبه توکن: هر ۱٬۰۰۰ توکن = ${formatNumber(plansPayload.token_price_per_1k_toman, lang)} تومان`}
                </small>
              </div>
              <div className="admin-users-table-wrap">
                <table className="admin-users-table">
                  <thead>
                    <tr>
                      <th>{lang === "en" ? "Plan" : "پلن"}</th>
                      <th>{lang === "en" ? "Price" : "قیمت"}</th>
                      <th>{lang === "en" ? "Tokens" : "سهمیه توکن"}</th>
                      <th>{lang === "en" ? "Storage Quota" : "سهمیه فضا"}</th>
                      <th>{lang === "en" ? "Duration" : "مدت اعتبار"}</th>
                      <th>{lang === "en" ? "Effective / 1K" : "هر ۱٬۰۰۰ توکن"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plansPayload.plans.map((p) => (
                      <tr key={p.code}>
                        <td>
                          <b>{p.name}</b>
                        </td>
                        <td>
                          {formatNumber(p.price_toman, lang)}{" "}
                          {lang === "en" ? "Toman" : "تومان"}
                        </td>
                        <td>{formatNumber(p.token_quota, lang)}</td>
                        <td>{formatBytes(p.storage_quota_bytes, lang)}</td>
                        <td>
                          {formatNumber(p.duration_days, lang)}{" "}
                          {lang === "en" ? "days" : "روز"}
                        </td>
                        <td>
                          {formatNumber(p.effective_toman_per_1k, lang)}{" "}
                          {lang === "en" ? "Toman" : "تومان"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="account-card">
            <div className="account-card-head">
              <h2>
                <ReceiptText size={16} />{" "}
                {lang === "en" ? "Usage & Payment History" : "گزارش مصرف توکن و تراکنش‌ها"}
              </h2>
            </div>
            <div className="usage-lists-grid">
              <div>
                <h4>{lang === "en" ? "Recent Token Usage" : "آخرین مصرف‌های توکن"}</h4>
                {usageLogs.length === 0 ? (
                  <p className="usage-empty">
                    {lang === "en" ? "No usage logs recorded yet." : "هنوز مصرفی ثبت نشده است."}
                  </p>
                ) : (
                  <div className="usage-list">
                    {usageLogs.map((log) => (
                      <div key={log.id} className="usage-item">
                        <div>
                          <b>{actionLabel(log.action, lang)}</b>
                          <small>{formatDateTime(log.created_at, lang, tz)}</small>
                        </div>
                        <div className="usage-item-num">
                          <b>
                            {formatNumber(log.total_tokens, lang)}{" "}
                            {lang === "en" ? "tokens" : "توکن"}
                          </b>
                          <small>
                            {formatNumber(log.cost_toman, lang)}{" "}
                            {lang === "en" ? "Toman" : "تومان"}
                          </small>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <h4>{lang === "en" ? "Payment Transactions" : "تراکنش‌های پرداخت"}</h4>
                {paymentTxs.length === 0 ? (
                  <p className="usage-empty">
                    {lang === "en" ? "No transactions recorded yet." : "هنوز پرداختی ثبت نشده است."}
                  </p>
                ) : (
                  <div className="usage-list">
                    {paymentTxs.map((tx) => (
                      <div key={tx.id} className="usage-item">
                        <div>
                          <b>{tx.plan_name}</b>
                          <small>
                            {tx.provider} · {tx.status} ·{" "}
                            {formatDateTime(tx.paid_at ?? tx.created_at, lang, tz)}
                          </small>
                        </div>
                        <div className="usage-item-num">
                          <b>
                            {formatNumber(tx.tokens_granted, lang)}{" "}
                            {lang === "en" ? "tokens" : "توکن"}
                          </b>
                          <small>
                            {tx.amount_toman
                              ? `${formatNumber(tx.amount_toman, lang)} ${
                                  lang === "en" ? "Toman" : "تومان"
                                }`
                              : lang === "en"
                              ? "Granted"
                              : "هدیه / مدیر"}
                          </small>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </AccountShell>
  );
}
