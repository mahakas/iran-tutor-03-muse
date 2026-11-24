"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  HardDrive,
  Palette,
  Shield,
  SlidersHorizontal,
} from "lucide-react";
import AccountShell from "@/components/AccountShell";
import { useAppContext } from "@/components/AppProvider";
import { COPY } from "@/lib/i18n";

type SettingsShellProps = {
  children: React.ReactNode;
};

export default function SettingsShell({ children }: SettingsShellProps) {
  const pathname = usePathname();
  const { preferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];

  const tabs = [
    {
      href: "/account/settings/general",
      label: copy.nav.general,
      descFa: "زبان رابط کاربری، منطقهٔ زمانی و پیش‌فرض معلم",
      descEn: "Language, timezone, and default tutor mode",
      icon: SlidersHorizontal,
    },
    {
      href: "/account/settings/appearance",
      label: copy.nav.appearance,
      descFa: "تم‌های مستقل روشن/تاریک، فونت، کنتراست و حرکت",
      descEn: "Independent Light/Dark themes, fonts, contrast & motion",
      icon: Palette,
    },
    {
      href: "/account/settings/storage",
      label: copy.nav.storage,
      descFa: "سهمیه فضا، تفکیک فایل‌ها، پیش‌نمایش و مدیریت حذف",
      descEn: "Storage quota, file breakdown, preview & cleanup",
      icon: HardDrive,
    },
    {
      href: "/account/settings/notifications",
      label: copy.nav.notifications,
      descFa: "هشدارهای مصرف توکن، فضای ذخیره‌سازی و انقضا",
      descEn: "Token usage alerts, storage warnings & reminders",
      icon: Bell,
    },
    {
      href: "/account/settings/privacy",
      label: copy.nav.privacy,
      descFa: "ذخیرهٔ تاریخچه و پیوست‌ها، نشست‌های فعال و خروج",
      descEn: "History & attachment retention, active sessions & logout",
      icon: Shield,
    },
  ];

  return (
    <AccountShell
      title={copy.menu.settings}
      subtitle={
        lang === "en"
          ? "Manage your Darsyar workspace preferences, appearance tokens, storage, and active sessions."
          : "تنظیمات محیط کاربری درسیار، ظاهر، حافظه و امنیت حساب خود را مدیریت کنید."
      }
      requireAuth
    >
      <div className="settings-layout">
        <aside className="settings-nav" aria-label={copy.menu.settings}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = pathname === tab.href;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`settings-nav-item ${active ? "active" : ""}`}
              >
                <span className="settings-nav-icon">
                  <Icon size={17} />
                </span>
                <span className="settings-nav-text">
                  <b>{tab.label}</b>
                  <small>{lang === "en" ? tab.descEn : tab.descFa}</small>
                </span>
              </Link>
            );
          })}
        </aside>
        <section className="settings-content-pane">{children}</section>
      </div>
    </AccountShell>
  );
}
