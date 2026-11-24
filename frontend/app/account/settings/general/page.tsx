"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, Globe, LoaderCircle, Sparkles } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import SettingsShell from "@/components/SettingsShell";
import { TIMEZONE_OPTIONS } from "@/lib/preferences";
import type { AppLanguage, TutorMode } from "@/lib/types";

export default function GeneralSettingsPage() {
  const { user, preferences, updatePreferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";

  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const saveGeneral = async (patch: Partial<typeof preferences.general>) => {
    setSaving(true);
    setFeedback("");
    setError("");
    try {
      await updatePreferences({ general: patch });
      setFeedback(
        (patch.language ?? lang) === "en"
          ? "General preferences saved."
          : "تنظیمات عمومی ذخیره شد."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Failed to save settings."
          : "ذخیره تنظیمات انجام نشد."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsShell>
      <div className="settings-stack">
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Globe size={16} />{" "}
                {lang === "en" ? "Language & Region" : "زبان و منطقهٔ زمانی"}
              </h2>
              <p>
                {lang === "en"
                  ? "Switching language updates interface copy, number formatting, and RTL/LTR layout direction immediately."
                  : "تغییر زبان، متن رابط کاربری، فرمت اعداد و جهت چیدمان راست‌به‌چپ یا چپ‌به‌راست را فوراً تغییر می‌دهد."}
              </p>
            </div>
            {saving && <LoaderCircle className="spin" size={16} />}
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Interface Language" : "زبان رابط کاربری"}</b>
              <small>
                {lang === "en"
                  ? "Supports Persian (RTL) and English (LTR)"
                  : "پشتیبانی کامل از فارسی (راست‌چین) و انگلیسی (چپ‌چین)"}
              </small>
            </div>
            <div className="segmented-control">
              <button
                type="button"
                className={preferences.general.language === "fa" ? "active" : ""}
                onClick={() => void saveGeneral({ language: "fa" as AppLanguage })}
              >
                فارسی (RTL)
              </button>
              <button
                type="button"
                className={preferences.general.language === "en" ? "active" : ""}
                onClick={() => void saveGeneral({ language: "en" as AppLanguage })}
              >
                English (LTR)
              </button>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Timezone" : "منطقهٔ زمانی"}</b>
              <small>
                {lang === "en"
                  ? "Used to format timestamps across sessions, exams, and billing history."
                  : "برای نمایش دقیق تاریخ و ساعت آزمون‌ها، تراکنش‌ها و نشست‌ها استفاده می‌شود."}
              </small>
            </div>
            <select
              className="settings-select"
              value={preferences.general.timezone}
              onChange={(e) => void saveGeneral({ timezone: e.target.value })}
            >
              {TIMEZONE_OPTIONS.map((tz) => (
                <option key={tz.value} value={tz.value}>
                  {lang === "en" ? tz.labelEn : tz.labelFa}
                </option>
              ))}
            </select>
          </div>
        </section>

        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Sparkles size={16} />{" "}
                {lang === "en" ? "Learning Defaults" : "پیش‌فرض‌های کلاس درس"}
              </h2>
              <p>
                {lang === "en"
                  ? "Choose which tutoring mode opens by default when starting a fresh session."
                  : "حالت پیش‌فرض معلم خصوصی هنگام ورود به کلاس درس."}
              </p>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Default Tutor Mode" : "حالت پیش‌فرض تدریس"}</b>
              <small>
                {lang === "en"
                  ? "You can still switch modes anytime inside the classroom toolbar."
                  : "در هر زمان می‌توانید در نوار ابزار کلاس حالت را تغییر دهید."}
              </small>
            </div>
            <select
              className="settings-select"
              value={preferences.general.default_tutor_mode}
              onChange={(e) =>
                void saveGeneral({ default_tutor_mode: e.target.value as TutorMode })
              }
            >
              <option value="tutor">
                {lang === "en" ? "Personal Tutor" : "معلم خصوصی"}
              </option>
              <option value="problem_solver">
                {lang === "en" ? "Problem Solver" : "حل تمرین"}
              </option>
              <option value="question_designer">
                {lang === "en" ? "Question Designer" : "طراحی سؤال"}
              </option>
            </select>
          </div>
        </section>

        {user && (
          <section className="account-card">
            <div className="account-card-head">
              <h2>{lang === "en" ? "Account Summary" : "خلاصه حساب کاربری"}</h2>
            </div>
            <div className="readonly-info-list">
              <div className="readonly-info-row">
                <span>{lang === "en" ? "Display Name" : "نام نمایشی"}</span>
                <b>{user.full_name || user.masked_phone}</b>
              </div>
              <div className="readonly-info-row">
                <span>{lang === "en" ? "Verified Mobile" : "شماره موبایل"}</span>
                <b dir="ltr">{user.phone_number}</b>
              </div>
              <div className="readonly-info-row">
                <span>{lang === "en" ? "Active Plan" : "اشتراک فعال"}</span>
                <b>{user.plan_title}</b>
              </div>
            </div>
            <div className="account-inline-links">
              <Link href="/account/profile" className="outline-button">
                {lang === "en" ? "Edit Profile" : "ویرایش پروفایل"}
              </Link>
              <Link href="/account/upgrade" className="outline-button">
                {lang === "en" ? "Manage Subscription" : "مدیریت اشتراک"}
              </Link>
            </div>
          </section>
        )}

        {feedback && (
          <div className="success-note">
            <Check size={16} />
            <span>{feedback}</span>
          </div>
        )}
        {error && <div className="inline-error">{error}</div>}
      </div>
    </SettingsShell>
  );
}
