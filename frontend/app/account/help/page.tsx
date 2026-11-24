"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  ChevronDown,
  CircleHelp,
  Crown,
  HardDrive,
  Keyboard,
  Palette,
  Search,
  ShieldCheck,
} from "lucide-react";
import AccountShell from "@/components/AccountShell";
import { useAppContext } from "@/components/AppProvider";

type FaqItem = {
  id: string;
  category: "learning" | "billing" | "storage" | "security";
  qFa: string;
  qEn: string;
  aFa: string;
  aEn: string;
};

const FAQS: FaqItem[] = [
  {
    id: "grounding",
    category: "learning",
    qFa: "چگونه درسیار پاسخ‌ها را مستند به کتاب درسی ارائه می‌دهد؟",
    qEn: "How does Darsyar ground answers in official textbooks?",
    aFa: "پس از انتخاب پایه، رشته (برای پایه‌های دهم تا دوازدهم) و کتاب درسی، موتور جست‌وجوی درسیار تنها در صفحه‌های تأییدشدهٔ همان کتاب جست‌وجو می‌کند و همراه هر پاسخ شماره فصل و صفحه چاپی را نمایش می‌دهد.",
    aEn: "After you choose Grade, Major (for grades 10–12), and Textbook, Darsyar retrieves exclusively from the approved pages of that exact book and cites chapter and printed page numbers.",
  },
  {
    id: "modes",
    category: "learning",
    qFa: "تفاوت حالت‌های «معلم خصوصی»، «حل تمرین»، «طراحی سؤال» و «آزمون زمان‌دار» چیست؟",
    qEn: "What is the difference between the four classroom modes?",
    aFa: "حالت «معلم خصوصی» مفاهیم را قدم‌به‌قدم آموزش می‌دهد؛ «حل تمرین» راه‌حل کامل پرسش یا تصویر تمرین را می‌نویسد؛ «طراحی سؤال» پرسش‌های تمرینی تازه با کلید می‌سازد؛ و «آزمون زمان‌دار» آزمون کنکوری (با نمره منفی یک‌سوم) یا تمرینی (نمره از ۲۰) همراه با کارنامه تحلیلی برگزار می‌کند.",
    aEn: "Personal Tutor explains concepts step-by-step; Problem Solver works through text or photo exercises; Question Designer creates fresh practice questions; Timed Exam generates scored Konkoor (1/3 negative marking) or Final-style (out of 20) exams.",
  },
  {
    id: "tokens",
    category: "billing",
    qFa: "مصرف توکن و تمدید پلن چگونه محاسبه می‌شود؟",
    qEn: "How are tokens consumed and carried over when upgrading?",
    aFa: "هر پرسش متنی، تصویری، صوتی یا ساخت آزمون بر اساس تعداد واقعی توکن مصرفی از اعتبار شما کسر می‌شود. هنگام ارتقا یا تمدید پیش از تاریخ انقضا، توکن‌های باقی‌ماندهٔ معتبر به دورهٔ جدید منتقل می‌شوند. تاریخچهٔ دقیق مصرف و پرداخت در صفحه «ارتقای پلن» قابل مشاهده است.",
    aEn: "Each text, image, voice question, or exam generation deducts its actual token usage. When you upgrade before your current plan expires, remaining valid tokens carry over into the new billing period.",
  },
  {
    id: "storage",
    category: "storage",
    qFa: "چه فایل‌هایی از فضای ذخیره‌سازی شخصی من مصرف می‌کنند؟",
    qEn: "Which files count toward my personal storage quota?",
    aFa: "سهمیه فضای ذخیره‌سازی پلن شما تنها برای فایل‌های شخصی، تصویر پروفایل و پیوست‌های تصویر/صوت ذخیره‌شدهٔ خودتان محاسبه می‌شود. کتاب‌های درسی رسمی منابع اشتراکی سامانه هستند و از فضای شما کم نمی‌شوند. در تنظیمات «حافظه و داده‌ها» می‌توانید تمام فایل‌های خود را ببینید، دانلود یا حذف کنید.",
    aEn: "Only your personal uploads, profile avatar, and saved tutor attachments count toward your storage quota. Official textbooks are shared curriculum assets and never consume user quota.",
  },
  {
    id: "privacy-attachments",
    category: "security",
    qFa: "چطور مانع ذخیره خودکار تاریخچه یا پیوست‌های پرسش شوم؟",
    qEn: "How can I stop Darsyar from saving chat history or attachments?",
    aFa: "در بخش «تنظیمات ← حریم خصوصی و امنیت» می‌توانید گزینه‌های «ذخیره خودکار تاریخچه گفت‌وگوها» و «نگهداری پیوست‌های تصویر و صدای معلم» را خاموش کنید. همچنین می‌توانید در همان صفحه نشست‌های فعال خود را بررسی و باطل کنید.",
    aEn: "Visit Settings → Privacy & Security to disable automatic chat history saving or attachment storage, and inspect or revoke active device sessions.",
  },
  {
    id: "phone-change",
    category: "security",
    qFa: "چگونه شماره موبایل حساب کاربری خود را تغییر دهم؟",
    qEn: "How do I change my registered mobile number?",
    aFa: "برای امنیت حساب، شماره موبایل مستقیماً تغییر نمی‌کند. از صفحهٔ «پروفایل» شماره جدید را وارد کنید، کد تأیید ۶ رقمی پیامکی را دریافت و تأیید نمایید تا شماره حساب شما با احراز هویت معتبر جایگزین شود.",
    aEn: "Open Profile, enter your new Iranian mobile number, and verify the 6-digit SMS OTP sent to the new number.",
  },
];

export default function HelpPage() {
  const { preferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";

  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>("grounding");

  const filteredFaqs = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return FAQS;
    return FAQS.filter((item) => {
      const text = `${item.qFa} ${item.aFa} ${item.qEn} ${item.aEn}`.toLowerCase();
      return text.includes(q);
    });
  }, [query]);

  return (
    <AccountShell
      title={lang === "en" ? "Help & Documentation" : "راهنما و مستندات درسیار"}
      subtitle={
        lang === "en"
          ? "Verified documentation on how Darsyar's textbook tutor, exams, token plans, personal storage, and account security work."
          : "راهنمای کامل کار با معلم خصوصی کتاب‌محور درسیار، آزمون‌های زمان‌دار، پلن‌های توکن، حافظه و امنیت حساب."
      }
      requireAuth={false}
    >
      <div className="help-stack">
        {/* Quick Navigation Guides */}
        <section className="help-guides-grid">
          <Link href="/account/upgrade" className="help-guide-card">
            <Crown size={20} />
            <div>
              <b>{lang === "en" ? "Plans & Billing" : "اشتراک، توکن و پرداخت"}</b>
              <p>
                {lang === "en"
                  ? "View active plans, compare token & storage limits, and check usage logs."
                  : "مشاهده پلن‌های فعال، مقایسه سهمیه توکن و فضا و بررسی تاریخچه مصرف."}
              </p>
            </div>
          </Link>

          <Link href="/account/settings/appearance" className="help-guide-card">
            <Palette size={20} />
            <div>
              <b>{lang === "en" ? "Theme & Readability" : "ظاهر، تم روشن/تاریک و خوانایی"}</b>
              <p>
                {lang === "en"
                  ? "Customize Light & Dark modes separately, adjust UI/code font size, motion, and contrast."
                  : "تنظیم مستقل حالت روشن و تاریک، اندازه فونت، کاهش حرکت و کنترل کنتراست."}
              </p>
            </div>
          </Link>

          <Link href="/account/settings/storage" className="help-guide-card">
            <HardDrive size={20} />
            <div>
              <b>{lang === "en" ? "Storage & Data" : "مدیریت حافظه و فایل‌ها"}</b>
              <p>
                {lang === "en"
                  ? "Inspect used bytes by category, preview or download personal files, and free space safely."
                  : "بررسی تفکیکی مصرف فضا، پیش‌نمایش، دانلود یا حذف امن فایل‌های شخصی."}
              </p>
            </div>
          </Link>

          <Link href="/account/settings/privacy" className="help-guide-card">
            <ShieldCheck size={20} />
            <div>
              <b>{lang === "en" ? "Sessions & Security" : "نشست‌های فعال و امنیت"}</b>
              <p>
                {lang === "en"
                  ? "Manage chat/attachment retention and revoke active sessions across devices."
                  : "کنترل ذخیره تاریخچه، پیوست‌ها و لغو نشست‌های فعال در دستگاه‌های دیگر."}
              </p>
            </div>
          </Link>
        </section>

        {/* Keyboard Shortcuts */}
        <section className="account-card">
          <div className="account-card-head">
            <h2>
              <Keyboard size={16} />{" "}
              {lang === "en" ? "Classroom Keyboard Shortcuts" : "کلیدهای میانبر کلاس درس"}
            </h2>
          </div>
          <div className="shortcuts-grid">
            <div className="shortcut-item">
              <span>{lang === "en" ? "Send question" : "ارسال پرسش"}</span>
              <kbd dir="ltr">Enter</kbd>
            </div>
            <div className="shortcut-item">
              <span>{lang === "en" ? "New line in composer" : "خط جدید در متن پرسش"}</span>
              <kbd dir="ltr">Shift + Enter</kbd>
            </div>
            <div className="shortcut-item">
              <span>{lang === "en" ? "Start a fresh chat" : "شروع گفت‌وگوی تازه"}</span>
              <kbd dir="ltr">Ctrl / ⌘ + K</kbd>
            </div>
            <div className="shortcut-item">
              <span>{lang === "en" ? "Open global quick search" : "باز کردن جستجوی سریع"}</span>
              <kbd dir="ltr">/  یا  Ctrl + /</kbd>
            </div>
            <div className="shortcut-item">
              <span>{lang === "en" ? "Close open menu / dialog" : "بستن منو یا پنجره باز"}</span>
              <kbd dir="ltr">Esc</kbd>
            </div>
          </div>
        </section>

        {/* Searchable FAQ */}
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <CircleHelp size={16} />{" "}
                {lang === "en" ? "Frequently Asked Questions" : "پرسش‌های متداول"}
              </h2>
              <p>
                {lang === "en"
                  ? "Search Darsyar's verified feature behavior and account policies."
                  : "پاسخ دقیق به پرسش‌های رایج دربارهٔ عملکرد واقعی سامانه درسیار."}
              </p>
            </div>
          </div>

          <div className="users-search" style={{ marginBottom: 14 }}>
            <Search size={15} />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                lang === "en" ? "Search help topics..." : "جستجو در راهنما..."
              }
            />
          </div>

          <div className="faq-list">
            {filteredFaqs.length === 0 ? (
              <div className="history-empty">
                <BookOpen size={22} />
                <span>
                  {lang === "en"
                    ? "No help articles matched your query."
                    : "موردی مطابق جستجوی شما یافت نشد."}
                </span>
              </div>
            ) : (
              filteredFaqs.map((item) => {
                const isOpen = openId === item.id;
                return (
                  <div key={item.id} className={`faq-item ${isOpen ? "open" : ""}`}>
                    <button
                      type="button"
                      className="faq-trigger"
                      aria-expanded={isOpen}
                      onClick={() => setOpenId(isOpen ? null : item.id)}
                    >
                      <span>{lang === "en" ? item.qEn : item.qFa}</span>
                      <ChevronDown size={16} className={isOpen ? "rotated" : ""} />
                    </button>
                    {isOpen && (
                      <div className="faq-answer">
                        <p>{lang === "en" ? item.aEn : item.aFa}</p>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>
    </AccountShell>
  );
}
