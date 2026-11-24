"use client";

import { useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  Crown,
  LoaderCircle,
  LogIn,
  LogOut,
  Phone,
  Settings,
  ShieldCheck,
  User as UserIcon,
} from "lucide-react";
import AccountAvatar from "@/components/AccountAvatar";
import { useAppContext } from "@/components/AppProvider";
import GlobalSearch, { type SearchItem } from "@/components/GlobalSearch";
import { COPY } from "@/lib/i18n";

type AccountShellProps = {
  title: string;
  subtitle?: string;
  requireAuth?: boolean;
  children: React.ReactNode;
};

export default function AccountShell({
  title,
  subtitle,
  requireAuth = true,
  children,
}: AccountShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, token, authReady, preferences, openLoginModal, requestLogout } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];
  const BackArrow = lang === "en" ? ArrowLeft : ArrowRight;

  const accountQuickCommands = useMemo<SearchItem[]>(
    () => [
      {
        id: "acc-cmd-classroom",
        category: "chats",
        title: lang === "en" ? "Start New Tutor Chat" : "شروع گفت‌وگوی تازه در کلاس درس",
        subtitle: lang === "en" ? "Go to classroom & ask tutor" : "بازگشت به کلاس درس و پرسش از معلم",
        badge: lang === "en" ? "Classroom" : "کلاس درس",
        icon: "chat",
        onSelect: () => router.push("/?action=new-chat"),
      },
      {
        id: "acc-cmd-new-exam",
        category: "exams",
        title: lang === "en" ? "Create New Timed Exam" : "ساخت آزمون زمان‌دار جدید",
        subtitle: lang === "en" ? "Configure and start an exam" : "طراحی آزمون از کتاب درسی در کلاس درس",
        badge: lang === "en" ? "New exam" : "آزمون جدید",
        icon: "exam",
        onSelect: () => router.push("/?action=new-exam"),
      },
      {
        id: "acc-cmd-exam-history",
        category: "exams",
        title: lang === "en" ? "My Exam History" : "آزمون‌های من و کارنامه‌ها",
        subtitle: lang === "en" ? "View previous exam results" : "مشاهده آزمون‌های قبلی در کلاس",
        badge: lang === "en" ? "Archive" : "آرشیو",
        icon: "exam",
        onSelect: () => router.push("/?action=exams"),
      },
      {
        id: "acc-cmd-storage",
        category: "files",
        title: lang === "en" ? "Storage & Files" : "حافظه و فایل‌های شخصی",
        subtitle: lang === "en" ? "Inspect quota & manage uploads" : "بررسی فضا و مدیریت فایل‌ها",
        badge: lang === "en" ? "Storage" : "حافظه",
        icon: "file",
        onSelect: () => router.push("/account/settings/storage"),
      },
      {
        id: "acc-cmd-appearance",
        category: "commands",
        title: lang === "en" ? "Appearance & Theme" : "تنظیمات ظاهر و تم",
        subtitle: lang === "en" ? "Light/Dark, presets, contrast, fonts" : "تم روشن/تاریک، رنگ‌ها و فونت",
        badge: lang === "en" ? "Settings" : "تنظیمات",
        icon: "appearance",
        onSelect: () => router.push("/account/settings/appearance"),
      },
      {
        id: "acc-cmd-upgrade",
        category: "commands",
        title: lang === "en" ? "Upgrade Plan & Tokens" : "ارتقای پلن و مصرف توکن",
        subtitle: lang === "en" ? "Compare plans & payment logs" : "مشاهده پلن‌ها و تراکنش‌ها",
        badge: lang === "en" ? "Billing" : "اشتراک",
        icon: "plan",
        onSelect: () => router.push("/account/upgrade"),
      },
      {
        id: "acc-cmd-profile",
        category: "commands",
        title: lang === "en" ? "Profile" : "پروفایل کاربری",
        subtitle: lang === "en" ? "Edit personal info & phone" : "ویرایش نام، ایمیل و موبایل",
        badge: lang === "en" ? "Profile" : "حساب",
        icon: "nav",
        onSelect: () => router.push("/account/profile"),
      },
      {
        id: "acc-cmd-help",
        category: "commands",
        title: lang === "en" ? "Help & Docs" : "راهنما و مستندات",
        subtitle: lang === "en" ? "FAQ & shortcuts" : "سوالات متداول و میانبرها",
        badge: lang === "en" ? "Help" : "راهنما",
        icon: "help",
        onSelect: () => router.push("/account/help"),
      },
    ],
    [lang, router]
  );

  const navLinks = [
    { href: "/account/upgrade", label: copy.nav.upgrade, icon: Crown, match: "/account/upgrade" },
    { href: "/account/profile", label: copy.nav.profile, icon: UserIcon, match: "/account/profile" },
    {
      href: "/account/settings/general",
      label: copy.nav.settings,
      icon: Settings,
      match: "/account/settings",
    },
    { href: "/account/help", label: copy.nav.help, icon: CircleHelp, match: "/account/help" },
  ];

  return (
    <div className="account-page-shell" dir={lang === "en" ? "ltr" : "rtl"}>
      <header className="account-topbar">
        <div className="account-topbar-inner">
          <div className="account-topbar-left">
            <Link href="/" className="account-back-link">
              <BackArrow size={16} />
              <span>{copy.backToClassroom}</span>
            </Link>
            <div className="account-topbar-divider" />
            <Link href="/" className="account-brand-chip">
              <span className="brand-mark small-mark">{lang === "en" ? "D" : "د"}</span>
              <div>
                <b>{copy.brandName}</b>
                <span>{copy.accountSectionTitle}</span>
              </div>
            </Link>
          </div>

          <nav className="account-top-nav" aria-label={copy.accountSectionTitle}>
            {navLinks.map((item) => {
              const Icon = item.icon;
              const isActive = pathname?.startsWith(item.match);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`account-top-nav-item ${isActive ? "active" : ""}`}
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="account-topbar-right">
            {user ? (
              <div className="account-topbar-user">
                <AccountAvatar size={30} />
                <span className="account-topbar-name">
                  {user.full_name ||
                    (preferences.privacy.show_phone_masked
                      ? user.masked_phone
                      : user.phone_number)}
                </span>
                <button
                  type="button"
                  className="account-topbar-logout"
                  onClick={requestLogout}
                  title={copy.menu.logOut}
                >
                  <LogOut size={15} />
                  <span>{copy.menu.logOut}</span>
                </button>
              </div>
            ) : authReady ? (
              <button
                type="button"
                className="primary-button"
                onClick={() => openLoginModal()}
              >
                <LogIn size={15} />
                <span>{copy.auth.loginCta}</span>
              </button>
            ) : null}
            <GlobalSearch
              mode="student"
              lang={lang}
              authToken={token}
              isAuthenticated={Boolean(user)}
              quickCommands={accountQuickCommands}
              onStudentSelectBook={({ bookId, gradeNumber, majorCode, topicTitle }) => {
                const qp = new URLSearchParams({
                  bookId: String(bookId),
                  grade: String(gradeNumber),
                  major: majorCode,
                });
                if (topicTitle) qp.set("topic", topicTitle);
                router.push(`/?${qp.toString()}`);
              }}
              onStudentSelectChat={(chatId) => router.push(`/?chatId=${encodeURIComponent(chatId)}`)}
              onStudentSelectExam={(examId) => router.push(`/?examId=${encodeURIComponent(examId)}`)}
              onNavigateRoute={(href) => router.push(href)}
              onRequestLogin={() => openLoginModal()}
            />
          </div>
        </div>
      </header>

      <main className="account-main">
        {requireAuth && !authReady ? (
          <div className="account-guard-card">
            <LoaderCircle className="spin" size={26} />
            <p>{lang === "en" ? "Verifying your session..." : "در حال بررسی نشست کاربری..."}</p>
          </div>
        ) : requireAuth && !user ? (
          <div className="account-guard-card">
            <div className="modal-icon">
              <ShieldCheck size={24} />
            </div>
            <h1>{copy.auth.loginPromptTitle}</h1>
            <p>{copy.auth.loginPromptBody}</p>
            <div className="account-guard-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => openLoginModal()}
              >
                <Phone size={16} />
                <span>{copy.auth.loginCta}</span>
              </button>
              <Link href="/" className="outline-button">
                {copy.backToClassroom}
              </Link>
            </div>
          </div>
        ) : (
          <div className="account-container">
            <div className="account-page-header">
              <h1>{title}</h1>
              {subtitle && <p>{subtitle}</p>}
            </div>
            {children}
          </div>
        )}
      </main>
    </div>
  );
}
