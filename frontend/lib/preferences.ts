import type {
  AppearanceModePalette,
  FontFamilyChoice,
  ThemePresetId,
  UserPreferences,
} from "./types";

export const PREFERENCES_STORAGE_KEY = "darsyar_preferences_cache_v1";
export const ADMIN_PREFERENCES_STORAGE_KEY = "darsyar_admin_preferences_cache_v1";

export type ThemePreset = {
  id: ThemePresetId;
  nameFa: string;
  nameEn: string;
  light: AppearanceModePalette;
  dark: AppearanceModePalette;
};

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: "darsyar",
    nameFa: "درسیار کلاسیک",
    nameEn: "Darsyar Classic",
    light: {
      theme: "darsyar",
      accent: "#0f766e",
      background: "#f8f6f1",
      foreground: "#202b35",
      font_family: "vazir",
    },
    dark: {
      theme: "darsyar",
      accent: "#2dd4bf",
      background: "#0f171a",
      foreground: "#e8f1ef",
      font_family: "vazir",
    },
  },
  {
    id: "emerald",
    nameFa: "زمردی روشن",
    nameEn: "Emerald Study",
    light: {
      theme: "emerald",
      accent: "#059669",
      background: "#f4faf7",
      foreground: "#142921",
      font_family: "vazir",
    },
    dark: {
      theme: "emerald",
      accent: "#34d399",
      background: "#0c1915",
      foreground: "#e6f5ee",
      font_family: "vazir",
    },
  },
  {
    id: "ocean",
    nameFa: "اقیانوس آرام",
    nameEn: "Ocean Breeze",
    light: {
      theme: "ocean",
      accent: "#0284c7",
      background: "#f5f9fc",
      foreground: "#162636",
      font_family: "system",
    },
    dark: {
      theme: "ocean",
      accent: "#38bdf8",
      background: "#0d1622",
      foreground: "#e7f1fa",
      font_family: "system",
    },
  },
  {
    id: "warm",
    nameFa: "کاغذی گرم",
    nameEn: "Warm Paper",
    light: {
      theme: "warm",
      accent: "#b45309",
      background: "#fbf8f3",
      foreground: "#2c241b",
      font_family: "sahel",
    },
    dark: {
      theme: "warm",
      accent: "#f59e0b",
      background: "#1b1712",
      foreground: "#f5ede2",
      font_family: "sahel",
    },
  },
  {
    id: "slate",
    nameFa: "سربی مدرن",
    nameEn: "Calm Slate",
    light: {
      theme: "slate",
      accent: "#475569",
      background: "#f8fafc",
      foreground: "#0f172a",
      font_family: "system",
    },
    dark: {
      theme: "slate",
      accent: "#94a3b8",
      background: "#0f172a",
      foreground: "#f1f5f9",
      font_family: "system",
    },
  },
  {
    id: "violet",
    nameFa: "بنفش خلاق",
    nameEn: "Violet Focus",
    light: {
      theme: "violet",
      accent: "#7c3aed",
      background: "#faf8ff",
      foreground: "#1e1633",
      font_family: "system",
    },
    dark: {
      theme: "violet",
      accent: "#a78bfa",
      background: "#131021",
      foreground: "#f1ecfe",
      font_family: "system",
    },
  },
  {
    id: "graphite",
    nameFa: "گرافیتی خالص",
    nameEn: "Pure Graphite",
    light: {
      theme: "graphite",
      accent: "#111827",
      background: "#f9fafb",
      foreground: "#111827",
      font_family: "system",
    },
    dark: {
      theme: "graphite",
      accent: "#e5e7eb",
      background: "#121212",
      foreground: "#f3f4f6",
      font_family: "system",
    },
  },
  {
    id: "midnight",
    nameFa: "شب نیمه‌تاریک",
    nameEn: "Midnight Ink",
    light: {
      theme: "midnight",
      accent: "#2563eb",
      background: "#f5f7fb",
      foreground: "#111827",
      font_family: "system",
    },
    dark: {
      theme: "midnight",
      accent: "#60a5fa",
      background: "#090d16",
      foreground: "#e5ecf7",
      font_family: "system",
    },
  },
];

export const ACCENT_SWATCHES = [
  { labelFa: "سبز آبی", labelEn: "Teal", hex: "#177e77" },
  { labelFa: "زمردی", labelEn: "Emerald", hex: "#059669" },
  { labelFa: "آبی اقیانوسی", labelEn: "Ocean", hex: "#0284c7" },
  { labelFa: "نیلی", labelEn: "Indigo", hex: "#4f46e5" },
  { labelFa: "بنفش", labelEn: "Violet", hex: "#7c3aed" },
  { labelFa: "کهربایی", labelEn: "Amber", hex: "#b45309" },
  { labelFa: "مرجانی", labelEn: "Coral", hex: "#d74e42" },
  { labelFa: "سربی", labelEn: "Slate", hex: "#334155" },
];

export const FONT_FAMILY_OPTIONS: Array<{
  id: FontFamilyChoice;
  labelFa: string;
  labelEn: string;
  cssStack: string;
}> = [
  {
    id: "vazir",
    labelFa: "خوانای فارسی (Tahoma / Vazirmatn)",
    labelEn: "Persian Clean (Tahoma / Vazirmatn)",
    cssStack: '"Vazirmatn", Tahoma, "Segoe UI", Arial, sans-serif',
  },
  {
    id: "system",
    labelFa: "فونت سیستم (System UI)",
    labelEn: "System UI",
    cssStack: 'system-ui, -apple-system, "Segoe UI", Tahoma, Arial, sans-serif',
  },
  {
    id: "sahel",
    labelFa: "نسخ مدرن (Segoe / Arial)",
    labelEn: "Modern Sans (Segoe / Arial)",
    cssStack: '"Segoe UI", Tahoma, Arial, sans-serif',
  },
  {
    id: "mono",
    labelFa: "تک‌عرض فنی (Monospace)",
    labelEn: "Technical Monospace",
    cssStack: 'ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace',
  },
];

export const TIMEZONE_OPTIONS = [
  { value: "Asia/Tehran", labelFa: "تهران (Asia/Tehran — UTC+3:30)", labelEn: "Tehran (Asia/Tehran)" },
  { value: "UTC", labelFa: "زمان هماهنگ جهانی (UTC)", labelEn: "UTC" },
  { value: "Asia/Dubai", labelFa: "دبی (Asia/Dubai)", labelEn: "Dubai (Asia/Dubai)" },
  { value: "Europe/Berlin", labelFa: "برلین (Europe/Berlin)", labelEn: "Berlin (Europe/Berlin)" },
  { value: "Europe/London", labelFa: "لندن (Europe/London)", labelEn: "London (Europe/London)" },
  { value: "America/New_York", labelFa: "نیویورک (America/New_York)", labelEn: "New York (America/New_York)" },
];

export const DEFAULT_PREFERENCES: UserPreferences = {
  general: {
    language: "fa",
    timezone: "Asia/Tehran",
    default_tutor_mode: "tutor",
  },
  appearance: {
    visual_style: "standard",
    color_mode: "light",
    separate_mode_themes: true,
    light: { ...THEME_PRESETS[0].light },
    dark: { ...THEME_PRESETS[0].dark },
    ui_font_size: 14,
    code_font_size: 13,
    reduce_motion: "system",
    contrast: 50,
    diff_markers: true,
  },
  notifications: {
    email_updates: false,
    usage_alerts: true,
    plan_expiry_reminders: true,
    exam_reminders: true,
    security_alerts: true,
  },
  privacy: {
    save_chat_history: true,
    store_uploaded_attachments: true,
    show_phone_masked: true,
  },
};

export function normalizeHex(hex: string, fallback: string): string {
  const cleaned = (hex || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(cleaned)) return cleaned.toLowerCase();
  if (/^#[0-9a-fA-F]{3}$/.test(cleaned)) {
    const [, r, g, b] = cleaned;
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return fallback;
}

export function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const normalized = normalizeHex(hex, "#000000");
  return {
    r: parseInt(normalized.slice(1, 3), 16),
    g: parseInt(normalized.slice(3, 5), 16),
    b: parseInt(normalized.slice(5, 7), 16),
  };
}

export function rgbToHex(r: number, g: number, b: number): string {
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return (
    "#" +
    [clamp(r), clamp(g), clamp(b)]
      .map((n) => n.toString(16).padStart(2, "0"))
      .join("")
  );
}

export function mixHex(hexA: string, hexB: string, weightB: number): string {
  const a = hexToRgb(hexA);
  const b = hexToRgb(hexB);
  const t = Math.max(0, Math.min(1, weightB));
  return rgbToHex(
    a.r + (b.r - a.r) * t,
    a.g + (b.g - a.g) * t,
    a.b + (b.b - a.b) * t
  );
}

export function relativeLuminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const linear = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

export function contrastRatio(fgHex: string, bgHex: string): number {
  const l1 = relativeLuminance(fgHex);
  const l2 = relativeLuminance(bgHex);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

export function contrastGrade(ratio: number): {
  level: "AAA" | "AA" | "AA-Large" | "Low";
  passesAA: boolean;
} {
  if (ratio >= 7) return { level: "AAA", passesAA: true };
  if (ratio >= 4.5) return { level: "AA", passesAA: true };
  if (ratio >= 3) return { level: "AA-Large", passesAA: false };
  return { level: "Low", passesAA: false };
}

export function pickReadableInk(bgHex: string): string {
  return relativeLuminance(bgHex) > 0.36 ? "#111827" : "#ffffff";
}

export function resolveEffectiveColorMode(
  prefs: UserPreferences,
  systemIsDark: boolean
): "light" | "dark" {
  const mode = prefs.appearance.color_mode;
  if (mode === "dark") return "dark";
  if (mode === "light") return "light";
  return systemIsDark ? "dark" : "light";
}

export function applyContrastAdjustment(
  palette: AppearanceModePalette,
  contrast: number,
  isDark: boolean
): {
  bg: string;
  fg: string;
  cardBg: string;
  sidebarBg: string;
  elevatedBg: string;
  mutedBg: string;
  borderSubtle: string;
  borderStrong: string;
  mutedInk: string;
  secondaryInk: string;
  ratio: number;
} {
  const baseBg = normalizeHex(palette.background, isDark ? "#0f171a" : "#f7f9f8");
  const baseFg = normalizeHex(palette.foreground, isDark ? "#e8f1ef" : "#202b35");
  const accentHex = normalizeHex(palette.accent, isDark ? "#2dd4bf" : "#177e77");
  const delta = (Math.max(0, Math.min(100, contrast)) - 50) / 50; // -1 .. +1

  let bg = baseBg;
  let fg = baseFg;

  if (delta > 0) {
    const pushFg = isDark ? "#ffffff" : "#060b0d";
    const pushBg = isDark ? "#05090b" : "#ffffff";
    fg = mixHex(baseFg, pushFg, delta * 0.6);
    bg = mixHex(baseBg, pushBg, delta * 0.45);
  } else if (delta < 0) {
    const softTarget = mixHex(baseBg, baseFg, 0.5);
    fg = mixHex(baseFg, softTarget, Math.abs(delta) * 0.25);
    bg = mixHex(baseBg, softTarget, Math.abs(delta) * 0.08);
  }

  const bgIsDark = isDark || relativeLuminance(bg) < 0.25;

  const cardBg = bgIsDark
    ? mixHex(bg, "#ffffff", 0.055 + Math.max(0, delta) * 0.02)
    : mixHex(bg, "#ffffff", 0.35);
  const sidebarBg = bgIsDark
    ? mixHex(bg, "#000000", 0.16)
    : mixHex(bg, accentHex, 0.055);
  const elevatedBg = bgIsDark
    ? mixHex(cardBg, "#ffffff", 0.05)
    : mixHex(mixHex(cardBg, bg, 0.65), accentHex, 0.045);
  const mutedBg = bgIsDark
    ? mixHex(cardBg, "#ffffff", 0.085)
    : mixHex(cardBg, accentHex, 0.09);

  const borderFactor = 0.12 + Math.max(0, delta) * 0.22;
  const borderSubtle = bgIsDark
    ? mixHex(bg, fg, borderFactor * 0.85)
    : mixHex(bg, fg, borderFactor * 0.72);
  const borderStrong = bgIsDark
    ? mixHex(bg, fg, Math.min(0.55, borderFactor * 1.55))
    : mixHex(bg, fg, Math.min(0.45, borderFactor * 1.35));

  const secondaryInk = mixHex(fg, bg, 0.24);
  const mutedInk = mixHex(fg, bg, 0.42);
  const ratio = contrastRatio(fg, bg);

  return {
    bg,
    fg,
    cardBg,
    sidebarBg,
    elevatedBg,
    mutedBg,
    borderSubtle,
    borderStrong,
    mutedInk,
    secondaryInk,
    ratio,
  };
}

export function normalizePreferencesClient(raw?: Partial<UserPreferences> | null): UserPreferences {
  const input = raw ?? {};
  return {
    general: {
      ...DEFAULT_PREFERENCES.general,
      ...(input.general ?? {}),
    },
    appearance: {
      ...DEFAULT_PREFERENCES.appearance,
      ...(input.appearance ?? {}),
      light: {
        ...DEFAULT_PREFERENCES.appearance.light,
        ...(input.appearance?.light ?? {}),
      },
      dark: {
        ...DEFAULT_PREFERENCES.appearance.dark,
        ...(input.appearance?.dark ?? {}),
      },
    },
    notifications: {
      ...DEFAULT_PREFERENCES.notifications,
      ...(input.notifications ?? {}),
    },
    privacy: {
      ...DEFAULT_PREFERENCES.privacy,
      ...(input.privacy ?? {}),
    },
  };
}

export function applyPreferencesToDocument(
  prefs: UserPreferences,
  systemIsDark: boolean
): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const effectiveMode = resolveEffectiveColorMode(prefs, systemIsDark);
  const isDark = effectiveMode === "dark";
  const palette = isDark ? prefs.appearance.dark : prefs.appearance.light;
  const computed = applyContrastAdjustment(palette, prefs.appearance.contrast, isDark);

  const bgIsDark = isDark || relativeLuminance(computed.bg) < 0.25;
  const accent = normalizeHex(palette.accent, isDark ? "#2dd4bf" : "#177e77");
  const accentHover = bgIsDark ? mixHex(accent, "#ffffff", 0.16) : mixHex(accent, "#000000", 0.18);
  const accentSoft = bgIsDark ? mixHex(computed.bg, accent, 0.22) : mixHex(computed.cardBg, accent, 0.12);
  const accentBorder = bgIsDark ? mixHex(computed.bg, accent, 0.42) : mixHex(computed.cardBg, accent, 0.3);
  const accentInk = pickReadableInk(accent);
  const cardRgb = hexToRgb(computed.cardBg);

  const fontStack =
    FONT_FAMILY_OPTIONS.find((f) => f.id === palette.font_family)?.cssStack ??
    FONT_FAMILY_OPTIONS[0].cssStack;

  const reduceMotionPref = prefs.appearance.reduce_motion;
  const systemReduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const reduceMotion =
    reduceMotionPref === "on" || (reduceMotionPref === "system" && systemReduced);

  const lang = prefs.general.language === "en" ? "en" : "fa";
  const dir = lang === "en" ? "ltr" : "rtl";

  root.setAttribute("lang", lang);
  root.setAttribute("dir", dir);
  root.setAttribute("data-theme", bgIsDark ? "dark" : effectiveMode);
  root.setAttribute("data-visual-style", prefs.appearance.visual_style);
  root.setAttribute("data-reduce-motion", reduceMotion ? "true" : "false");
  root.setAttribute(
    "data-diff-markers",
    prefs.appearance.diff_markers !== false ? "true" : "false"
  );
  root.style.colorScheme = bgIsDark ? "dark" : "light";

  const highContrastShift = Math.max(0, (prefs.appearance.contrast - 50) / 50);
  const diffAddBg = bgIsDark
    ? mixHex(computed.cardBg, "#10b981", 0.16 + highContrastShift * 0.1)
    : mixHex(computed.cardBg, "#10b981", 0.12 + highContrastShift * 0.08);
  const diffAddBorder = bgIsDark ? "#34d399" : "#059669";
  const diffAddInk = bgIsDark ? "#a7f3d0" : "#065f46";

  const diffDelBg = bgIsDark
    ? mixHex(computed.cardBg, "#ef4444", 0.17 + highContrastShift * 0.1)
    : mixHex(computed.cardBg, "#ef4444", 0.11 + highContrastShift * 0.08);
  const diffDelBorder = bgIsDark ? "#f87171" : "#dc2626";
  const diffDelInk = bgIsDark ? "#fecaca" : "#991b1b";

  const diffModBg = bgIsDark
    ? mixHex(computed.cardBg, "#f59e0b", 0.16 + highContrastShift * 0.1)
    : mixHex(computed.cardBg, "#f59e0b", 0.12 + highContrastShift * 0.08);
  const diffModBorder = bgIsDark ? "#fbbf24" : "#d97706";
  const diffModInk = bgIsDark ? "#fde68a" : "#92400e";

  root.style.setProperty("--ink", computed.fg);
  root.style.setProperty("--ink-secondary", computed.secondaryInk);
  root.style.setProperty("--muted", computed.mutedInk);
  root.style.setProperty("--line", computed.borderSubtle);
  root.style.setProperty("--line-strong", computed.borderStrong);
  root.style.setProperty("--canvas", computed.bg);
  root.style.setProperty("--sidebar-bg", computed.sidebarBg);
  root.style.setProperty("--card", computed.cardBg);
  root.style.setProperty("--elevated", computed.elevatedBg);
  root.style.setProperty("--surface-muted", computed.mutedBg);
  root.style.setProperty(
    "--topbar-bg",
    `rgba(${cardRgb.r}, ${cardRgb.g}, ${cardRgb.b}, 0.88)`
  );
  root.style.setProperty("--teal", accent);
  root.style.setProperty("--teal-dark", accentHover);
  root.style.setProperty("--teal-soft", accentSoft);
  root.style.setProperty("--mint", accentBorder);
  root.style.setProperty("--accent-ink", accentInk);
  root.style.setProperty("--diff-add-bg", diffAddBg);
  root.style.setProperty("--diff-add-border", diffAddBorder);
  root.style.setProperty("--diff-add-ink", diffAddInk);
  root.style.setProperty("--diff-del-bg", diffDelBg);
  root.style.setProperty("--diff-del-border", diffDelBorder);
  root.style.setProperty("--diff-del-ink", diffDelInk);
  root.style.setProperty("--diff-mod-bg", diffModBg);
  root.style.setProperty("--diff-mod-border", diffModBorder);
  root.style.setProperty("--diff-mod-ink", diffModInk);
  root.style.setProperty("--ui-font-family", fontStack);
  root.style.setProperty("--ui-font-size", `${prefs.appearance.ui_font_size}px`);
  root.style.setProperty("--code-font-size", `${prefs.appearance.code_font_size}px`);
  root.style.setProperty(
    "--shadow",
    isDark
      ? "0 14px 40px rgba(0, 0, 0, 0.42)"
      : "0 12px 36px rgba(34, 58, 62, .07)"
  );
}

export function readCachedPreferences(): UserPreferences | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (!raw) return null;
    return normalizePreferencesClient(JSON.parse(raw) as Partial<UserPreferences>);
  } catch {
    return null;
  }
}

export function writeCachedPreferences(prefs: UserPreferences | null): void {
  if (typeof window === "undefined") return;
  try {
    if (prefs) {
      window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(prefs));
    } else {
      window.localStorage.removeItem(PREFERENCES_STORAGE_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

export function readCachedAdminPreferences(): UserPreferences | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(ADMIN_PREFERENCES_STORAGE_KEY);
    if (!raw) return null;
    return normalizePreferencesClient(JSON.parse(raw) as Partial<UserPreferences>);
  } catch {
    return null;
  }
}

export function writeCachedAdminPreferences(prefs: UserPreferences | null): void {
  if (typeof window === "undefined") return;
  try {
    if (prefs) {
      window.localStorage.setItem(ADMIN_PREFERENCES_STORAGE_KEY, JSON.stringify(prefs));
    } else {
      window.localStorage.removeItem(ADMIN_PREFERENCES_STORAGE_KEY);
    }
  } catch {
    // ignore storage errors
  }
}
