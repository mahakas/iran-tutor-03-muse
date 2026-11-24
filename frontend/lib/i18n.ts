import type { AppLanguage } from "./types";

export function formatNumber(value: number, lang: AppLanguage): string {
  try {
    return new Intl.NumberFormat(lang === "en" ? "en-US" : "fa-IR").format(value);
  } catch {
    return String(value);
  }
}

export function formatDateTime(
  iso: string | null | undefined,
  lang: AppLanguage,
  timezone = "Asia/Tehran"
): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  try {
    return new Intl.DateTimeFormat(lang === "en" ? "en-US" : "fa-IR", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone || "Asia/Tehran",
    }).format(ms);
  } catch {
    return new Intl.DateTimeFormat(lang === "en" ? "en-US" : "fa-IR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(ms);
  }
}

export function formatBytes(bytes: number, lang: AppLanguage): string {
  const safe = Math.max(0, Number.isFinite(bytes) ? bytes : 0);
  const units =
    lang === "en"
      ? ["B", "KB", "MB", "GB"]
      : ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  if (safe < 1024) return `${formatNumber(safe, lang)} ${units[0]}`;
  let idx = 0;
  let value = safe;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  const rounded = value >= 100 || idx === 0 ? Math.round(value) : Number(value.toFixed(1));
  return `${formatNumber(rounded, lang)} ${units[idx]}`;
}

export const COPY = {
  fa: {
    brandName: "درسیار",
    brandTagline: "معلم خصوصی هوشمند",
    backToClassroom: "بازگشت به کلاس درس",
    accountSectionTitle: "حساب کاربری",
    menu: {
      upgradePlan: "ارتقای پلن",
      profile: "پروفایل",
      settings: "تنظیمات",
      help: "کمک",
      logOut: "خروج از حساب کاربری",
      accountMenuAria: "منوی حساب کاربری",
      remainingTokens: "توکن باقی‌مانده",
      expired: "منقضی‌شده",
      daysLeft: "روز اعتبار",
    },
    auth: {
      loginPromptTitle: "ورود به حساب کاربری درسیار",
      loginPromptBody:
        "برای دسترسی به پروفایل، تنظیمات، فضای ذخیره‌سازی و اشتراک خود با شماره موبایل وارد شوید.",
      loginCta: "ورود / ثبت‌نام پیامکی",
      logoutConfirmTitle: "خروج از حساب کاربری",
      logoutConfirmBody:
        "با خروج از حساب، نشست فعلی شما در سرور باطل می‌شود و برای دسترسی دوباره به اطلاعات حساب باید مجدداً وارد شوید.",
      logoutConfirmYes: "بله، خارج می‌شوم",
      logoutConfirmNo: "انصراف",
      loggingOut: "در حال خروج...",
    },
    nav: {
      upgrade: "ارتقای پلن",
      profile: "پروفایل",
      settings: "تنظیمات",
      help: "کمک",
      general: "عمومی",
      appearance: "ظاهر و نمایش",
      storage: "حافظه و داده‌ها",
      notifications: "اعلان‌ها",
      privacy: "حریم خصوصی و امنیت",
    },
  },
  en: {
    brandName: "Darsyar",
    brandTagline: "AI Textbook Tutor",
    backToClassroom: "Back to Classroom",
    accountSectionTitle: "Account",
    menu: {
      upgradePlan: "Upgrade Plan",
      profile: "Profile",
      settings: "Settings",
      help: "Help",
      logOut: "Log Out",
      accountMenuAria: "Account menu",
      remainingTokens: "tokens left",
      expired: "Expired",
      daysLeft: "days left",
    },
    auth: {
      loginPromptTitle: "Sign in to your Darsyar account",
      loginPromptBody:
        "Sign in with your mobile number to view and manage your profile, preferences, personal storage, and subscription.",
      loginCta: "Sign in with SMS",
      logoutConfirmTitle: "Log out of Darsyar",
      logoutConfirmBody:
        "Logging out immediately revokes your current server session and clears local account state.",
      logoutConfirmYes: "Log Out",
      logoutConfirmNo: "Cancel",
      loggingOut: "Logging out...",
    },
    nav: {
      upgrade: "Upgrade Plan",
      profile: "Profile",
      settings: "Settings",
      help: "Help",
      general: "General",
      appearance: "Appearance",
      storage: "Storage & Data",
      notifications: "Notifications",
      privacy: "Privacy & Security",
    },
  },
} as const;
