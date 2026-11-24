"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, Check, LoaderCircle, MailWarning } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import SettingsShell from "@/components/SettingsShell";

export default function NotificationSettingsPage() {
  const { user, preferences, updatePreferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const notif = preferences.notifications;

  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const toggle = async (key: keyof typeof notif, value: boolean) => {
    setSaving(true);
    setFeedback("");
    setError("");
    try {
      await updatePreferences({ notifications: { [key]: value } });
      setFeedback(
        lang === "en" ? "Notification settings updated." : "تنظیمات اعلان‌ها ذخیره شد."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Failed to save notification preferences."
          : "ذخیره تنظیمات اعلان انجام نشد."
      );
    } finally {
      setSaving(false);
    }
  };

  const rows: Array<{
    key: keyof typeof notif;
    titleFa: string;
    titleEn: string;
    descFa: string;
    descEn: string;
  }> = [
    {
      key: "usage_alerts",
      titleFa: "هشدار مصرف توکن و فضای ذخیره‌سازی",
      titleEn: "Token & storage threshold warnings",
      descFa: "نمایش هشدار هنگام کاهش توکن‌ها یا رسیدن فضای شخصی به بالای ۸۰٪.",
      descEn: "Warn inside Darsyar when tokens run low or personal storage exceeds 80%.",
    },
    {
      key: "plan_expiry_reminders",
      titleFa: "یادآوری نزدیک شدن به انقضای اشتراک",
      titleEn: "Subscription expiry reminders",
      descFa: "اطلاع‌رسانی پیش از پایان مهلت اعتبار پلن فعال.",
      descEn: "Notify when your active plan is approaching expiration.",
    },
    {
      key: "exam_reminders",
      titleFa: "یادآوری آزمون‌های زمان‌دار و کارنامه",
      titleEn: "Exam timer & report alerts",
      descFa: "نمایش هشدارهای زمان آزمون و آماده‌شدن کارنامه.",
      descEn: "Highlight active exam deadlines and completed report cards.",
    },
    {
      key: "security_alerts",
      titleFa: "هشدارهای امنیتی و نشست‌های تازه",
      titleEn: "Security & new session alerts",
      descFa: "اطلاع‌رسانی دربارهٔ ورودهای جدید و تغییرات شماره موبایل.",
      descEn: "Track new sign-ins and verified phone number changes.",
    },
    {
      key: "email_updates",
      titleFa: "گزارش‌های ایمیلی (نیازمند ثبت ایمیل در پروفایل)",
      titleEn: "Email summaries (requires email on Profile)",
      descFa: "ارسال خلاصه وضعیت اشتراک در صورت تکمیل ایمیل در پروفایل.",
      descEn: "Opt in to receive account summaries if an email address is saved on your profile.",
    },
  ];

  return (
    <SettingsShell>
      <div className="settings-stack">
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Bell size={16} />{" "}
                {lang === "en" ? "Notification Preferences" : "مدیریت اعلان‌ها"}
              </h2>
              <p>
                {lang === "en"
                  ? "Control which account alerts and reminders are enabled for your account."
                  : "مشخص کنید کدام هشدارها و یادآورها برای حساب کاربری شما فعال باشند."}
              </p>
            </div>
            {saving && <LoaderCircle className="spin" size={16} />}
          </div>

          {notif.email_updates && !user?.email && (
            <div className="warning-banner">
              <MailWarning size={16} />
              <span>
                {lang === "en"
                  ? "Email updates are turned on, but you have not added an email address in your Profile yet."
                  : "دریافت گزارش ایمیلی روشن است، اما هنوز ایمیلی در پروفایل ثبت نکرده‌اید."}
              </span>
              <Link href="/account/profile" className="outline-button">
                {lang === "en" ? "Add Email" : "ثبت ایمیل"}
              </Link>
            </div>
          )}

          {rows.map((row) => (
            <div key={row.key} className="settings-row">
              <div className="settings-row-label">
                <b>{lang === "en" ? row.titleEn : row.titleFa}</b>
                <small>{lang === "en" ? row.descEn : row.descFa}</small>
              </div>
              <label className="switch-control">
                <input
                  type="checkbox"
                  checked={Boolean(notif[row.key])}
                  onChange={(e) => void toggle(row.key, e.target.checked)}
                />
                <span className="switch-track" />
              </label>
            </div>
          ))}
        </section>

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
