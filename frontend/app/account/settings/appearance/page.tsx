"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  LoaderCircle,
  Monitor,
  Moon,
  Palette,
  RotateCcw,
  Sparkles,
  Sun,
} from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import SettingsShell from "@/components/SettingsShell";
import {
  ACCENT_SWATCHES,
  applyContrastAdjustment,
  contrastGrade,
  FONT_FAMILY_OPTIONS,
  normalizeHex,
  resolveEffectiveColorMode,
  THEME_PRESETS,
} from "@/lib/preferences";
import type {
  AppearanceModePalette,
  ColorMode,
  FontFamilyChoice,
  ReduceMotionMode,
  ThemePresetId,
  VisualStyle,
} from "@/lib/types";

export default function AppearanceSettingsPage() {
  const { preferences, systemIsDark, updatePreferences, resetPreferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const ap = preferences.appearance;

  const effectiveMode = resolveEffectiveColorMode(preferences, systemIsDark);
  const [selectedEditMode, setSelectedEditMode] = useState<"light" | "dark">(effectiveMode);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");

  const editingMode = ap.separate_mode_themes ? selectedEditMode : effectiveMode;
  const activePalette = editingMode === "dark" ? ap.dark : ap.light;
  const computedPreview = applyContrastAdjustment(
    activePalette,
    ap.contrast,
    editingMode === "dark"
  );
  const grade = contrastGrade(computedPreview.ratio);

  const persistPatch = async (patch: Parameters<typeof updatePreferences>[0]) => {
    setSaving(true);
    setFeedback("");
    setError("");
    try {
      await updatePreferences(patch);
      setFeedback(
        lang === "en"
          ? "Appearance updated & persisted."
          : "تنظیمات ظاهری اعمال و ذخیره شد."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Failed to save appearance."
          : "ذخیره تنظیمات ظاهری انجام نشد."
      );
    } finally {
      setSaving(false);
    }
  };

  const updateActivePalette = (palettePatch: Partial<AppearanceModePalette>) => {
    if (!ap.separate_mode_themes) {
      // When separate mode themes is OFF, keep theme preset / accent / font synced while keeping mode-appropriate bg/fg if switching preset
      const otherMode = editingMode === "dark" ? "light" : "dark";
      const otherPatch: Partial<AppearanceModePalette> = {};
      if (palettePatch.accent) otherPatch.accent = palettePatch.accent;
      if (palettePatch.font_family) otherPatch.font_family = palettePatch.font_family;
      if (palettePatch.theme) otherPatch.theme = palettePatch.theme;

      void persistPatch({
        appearance: {
          [editingMode]: palettePatch,
          ...(Object.keys(otherPatch).length > 0 ? { [otherMode]: otherPatch } : {}),
        },
      });
      return;
    }

    void persistPatch({
      appearance: {
        [editingMode]: palettePatch,
      },
    });
  };

  const handleSelectPreset = (presetId: ThemePresetId) => {
    const preset = THEME_PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    if (!ap.separate_mode_themes) {
      void persistPatch({
        appearance: {
          light: { ...preset.light },
          dark: { ...preset.dark },
        },
      });
    } else {
      void persistPatch({
        appearance: {
          [editingMode]: editingMode === "dark" ? { ...preset.dark } : { ...preset.light },
        },
      });
    }
  };

  const handleColorModeChange = (mode: ColorMode) => {
    if (mode === "light" || mode === "dark") {
      setSelectedEditMode(mode);
    } else {
      setSelectedEditMode(systemIsDark ? "dark" : "light");
    }
    void persistPatch({ appearance: { color_mode: mode } });
  };

  const handleAutoFixContrast = () => {
    const safeFg = editingMode === "dark" ? "#f1f6f5" : "#111b1e";
    const safeBg = editingMode === "dark" ? "#0c1316" : "#f7f9f8";
    void persistPatch({
      appearance: {
        contrast: Math.max(55, ap.contrast),
        [editingMode]: {
          background: safeBg,
          foreground: safeFg,
        },
      },
    });
  };

  const handleReset = async () => {
    setSaving(true);
    setFeedback("");
    setError("");
    try {
      await resetPreferences("appearance");
      setFeedback(
        lang === "en"
          ? "Appearance reset to Darsyar defaults."
          : "تنظیمات ظاهری به حالت پیش‌فرض درسیار بازگردانده شد."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Reset failed."
          : "بازنشانی تنظیمات انجام نشد."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingsShell>
      <div className="settings-stack">
        {/* Visual Style & Color Mode */}
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Palette size={16} />{" "}
                {lang === "en" ? "Visual Style & Color Mode" : "سبک بصری و حالت رنگ"}
              </h2>
              <p>
                {lang === "en"
                  ? "Applied globally via CSS design tokens and saved to your account."
                  : "تغییرات از طریق متغیرهای طراحی در کل سایت اعمال و در حساب کاربری شما ذخیره می‌شوند."}
              </p>
            </div>
            <div className="appearance-head-actions">
              {saving && <LoaderCircle className="spin" size={16} />}
              <button
                type="button"
                className="outline-button"
                disabled={saving}
                onClick={() => void handleReset()}
              >
                <RotateCcw size={14} />
                <span>{lang === "en" ? "Reset Defaults" : "بازگردانی پیش‌فرض"}</span>
              </button>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Visual Style" : "سبک چیدمان"}</b>
              <small>
                {lang === "en"
                  ? "Controls corner radius, card padding, and density."
                  : "میزان انحنای گوشه‌ها، فاصله‌ها و فشردگی عناصر رابط کاربری."}
              </small>
            </div>
            <div className="segmented-control">
              {(
                [
                  { id: "standard", fa: "استاندارد", en: "Standard" },
                  { id: "modern", fa: "مدرن و باز", en: "Modern" },
                  { id: "compact", fa: "فشرده", en: "Compact" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  className={ap.visual_style === opt.id ? "active" : ""}
                  onClick={() =>
                    void persistPatch({
                      appearance: { visual_style: opt.id as VisualStyle },
                    })
                  }
                >
                  {lang === "en" ? opt.en : opt.fa}
                </button>
              ))}
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Color Mode" : "حالت رنگ"}</b>
              <small>
                {lang === "en"
                  ? "Follow Light, Dark, or your operating system preference."
                  : "انتخاب حالت روشن، تاریک یا همگام با تنظیم سیستم‌عامل."}
              </small>
            </div>
            <div className="segmented-control">
              <button
                type="button"
                className={ap.color_mode === "light" ? "active" : ""}
                onClick={() => handleColorModeChange("light")}
              >
                <Sun size={14} />
                <span>{lang === "en" ? "Light" : "روشن"}</span>
              </button>
              <button
                type="button"
                className={ap.color_mode === "dark" ? "active" : ""}
                onClick={() => handleColorModeChange("dark")}
              >
                <Moon size={14} />
                <span>{lang === "en" ? "Dark" : "تاریک"}</span>
              </button>
              <button
                type="button"
                className={ap.color_mode === "system" ? "active" : ""}
                onClick={() => handleColorModeChange("system")}
              >
                <Monitor size={14} />
                <span>{lang === "en" ? "System" : "سیستم"}</span>
              </button>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>
                {lang === "en"
                  ? "Separate Light & Dark Customization"
                  : "تنظیم مستقل حالت روشن و تاریک"}
              </b>
              <small>
                {lang === "en"
                  ? "Keep separate presets, accents, backgrounds, foregrounds, and fonts for Light and Dark modes."
                  : "پالت رنگ، پس‌زمینه، رنگ متن و فونت حالت روشن و تاریک را مستقل از یکدیگر ذخیره کنید."}
              </small>
            </div>
            <label className="switch-control">
              <input
                type="checkbox"
                checked={ap.separate_mode_themes}
                onChange={(e) =>
                  void persistPatch({
                    appearance: { separate_mode_themes: e.target.checked },
                  })
                }
              />
              <span className="switch-track" />
            </label>
          </div>
        </section>

        {/* Independent Light / Dark Mode Theme & Colors */}
        <section className="account-card">
          <div className="account-card-head">
            <div>
              <h2>
                <Sparkles size={16} />{" "}
                {lang === "en" ? "Theme Presets & Colors" : "تم‌های آماده و رنگ‌بندی"}
              </h2>
              <p>
                {ap.separate_mode_themes
                  ? lang === "en"
                    ? `Currently editing ${editingMode.toUpperCase()} mode palette independently.`
                    : `در حال ویرایش مستقل پالت حالت «${
                        editingMode === "dark" ? "تاریک" : "روشن"
                      }».`
                  : lang === "en"
                  ? "Editing theme & accent across modes."
                  : "تم و رنگ تاکیدی به‌صورت هماهنگ تنظیم می‌شوند."}
              </p>
            </div>

            {ap.separate_mode_themes && (
              <div className="segmented-control" aria-label="Editing mode palette">
                <button
                  type="button"
                  className={editingMode === "light" ? "active" : ""}
                  onClick={() => setSelectedEditMode("light")}
                >
                  <Sun size={14} />
                  <span>{lang === "en" ? "Edit Light" : "پالت روشن"}</span>
                </button>
                <button
                  type="button"
                  className={editingMode === "dark" ? "active" : ""}
                  onClick={() => setSelectedEditMode("dark")}
                >
                  <Moon size={14} />
                  <span>{lang === "en" ? "Edit Dark" : "پالت تاریک"}</span>
                </button>
              </div>
            )}
          </div>

          <div className="theme-preset-grid">
            {THEME_PRESETS.map((preset) => {
              const modePal = editingMode === "dark" ? preset.dark : preset.light;
              const selected = activePalette.theme === preset.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  className={`theme-preset-card ${selected ? "selected" : ""}`}
                  onClick={() => handleSelectPreset(preset.id)}
                >
                  <div
                    className="theme-preset-preview"
                    style={{
                      background: modePal.background,
                      color: modePal.foreground,
                      borderColor: modePal.accent,
                    }}
                  >
                    <span
                      className="theme-preset-dot"
                      style={{ background: modePal.accent }}
                    />
                    <span className="theme-preset-aa">Aa</span>
                  </div>
                  <b>{lang === "en" ? preset.nameEn : preset.nameFa}</b>
                  {selected && (
                    <span className="theme-preset-check">
                      <Check size={12} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="appearance-colors-grid">
            <div className="color-control-block">
              <label>{lang === "en" ? "Accent Color" : "رنگ تاکیدی (Accent)"}</label>
              <div className="swatch-row">
                {ACCENT_SWATCHES.map((sw) => (
                  <button
                    key={sw.hex}
                    type="button"
                    className={`color-swatch ${
                      normalizeHex(activePalette.accent, "") === sw.hex ? "active" : ""
                    }`}
                    style={{ background: sw.hex }}
                    title={lang === "en" ? sw.labelEn : sw.labelFa}
                    onClick={() => updateActivePalette({ accent: sw.hex })}
                  />
                ))}
                <label className="color-picker-chip">
                  <input
                    type="color"
                    value={normalizeHex(activePalette.accent, "#177e77")}
                    onChange={(e) => updateActivePalette({ accent: e.target.value })}
                  />
                  <span dir="ltr">{normalizeHex(activePalette.accent, "#177e77")}</span>
                </label>
              </div>
            </div>

            <div className="color-pair-row">
              <div className="color-control-block">
                <label>
                  {lang === "en" ? "Background Color" : "رنگ پس‌زمینه (Background)"}
                </label>
                <div className="color-input-box">
                  <input
                    type="color"
                    value={normalizeHex(activePalette.background, "#f7f9f8")}
                    onChange={(e) => updateActivePalette({ background: e.target.value })}
                  />
                  <input
                    type="text"
                    dir="ltr"
                    value={activePalette.background}
                    onChange={(e) => {
                      if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
                        updateActivePalette({ background: e.target.value });
                      }
                    }}
                  />
                </div>
              </div>

              <div className="color-control-block">
                <label>
                  {lang === "en" ? "Foreground / Text Color" : "رنگ متن (Foreground)"}
                </label>
                <div className="color-input-box">
                  <input
                    type="color"
                    value={normalizeHex(activePalette.foreground, "#202b35")}
                    onChange={(e) => updateActivePalette({ foreground: e.target.value })}
                  />
                  <input
                    type="text"
                    dir="ltr"
                    value={activePalette.foreground}
                    onChange={(e) => {
                      if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
                        updateActivePalette({ foreground: e.target.value });
                      }
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Contrast Slider + Live Readability Check */}
          <div className="contrast-panel">
            <div className="contrast-head">
              <div>
                <b>{lang === "en" ? "Contrast & Readability" : "کنتراست و خوانایی"}</b>
                <small>
                  {lang === "en"
                    ? "Adjust contrast between foreground text, borders, and surfaces (0–100)."
                    : "شدت تفکیک متن، کادرها و پس‌زمینه را بین ۰ تا ۱۰۰ تنظیم کنید."}
                </small>
              </div>
              <div className={`contrast-badge ${grade.passesAA ? "ok" : "warn"}`}>
                <span>
                  {computedPreview.ratio.toFixed(1)}:1 · {grade.level}
                </span>
              </div>
            </div>

            <div className="slider-control-row">
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={ap.contrast}
                onChange={(e) =>
                  void persistPatch({
                    appearance: { contrast: Number(e.target.value) },
                  })
                }
              />
              <span className="slider-value-pill" dir="ltr">
                {ap.contrast}%
              </span>
            </div>

            {!grade.passesAA && (
              <div className="warning-banner">
                <AlertTriangle size={16} />
                <span>
                  {lang === "en"
                    ? `Current contrast (${computedPreview.ratio.toFixed(1)}:1) is below WCAG AA (4.5:1) and may be hard to read.`
                    : `کنتراست فعلی (${computedPreview.ratio.toFixed(1)}:1) کمتر از استاندارد خوانایی AA است و ممکن است متن کم‌رنگ دیده شود.`}
                </span>
                <button
                  type="button"
                  className="outline-button"
                  onClick={handleAutoFixContrast}
                >
                  {lang === "en" ? "Auto-fix Contrast" : "اصلاح خودکار"}
                </button>
              </div>
            )}
          </div>
        </section>

        {/* Typography & Motion */}
        <section className="account-card">
          <div className="account-card-head">
            <h2>
              {lang === "en" ? "Typography & Motion" : "تایپوگرافی و انیمیشن‌ها"}
            </h2>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "UI Font Family" : "فونت رابط کاربری"}</b>
              <small>
                {lang === "en"
                  ? "Stored per mode when separate light/dark customization is active."
                  : "در حالت مستقل، برای روشن و تاریک جداگانه ذخیره می‌شود."}
              </small>
            </div>
            <select
              className="settings-select"
              value={activePalette.font_family}
              onChange={(e) =>
                updateActivePalette({ font_family: e.target.value as FontFamilyChoice })
              }
            >
              {FONT_FAMILY_OPTIONS.map((f) => (
                <option key={f.id} value={f.id}>
                  {lang === "en" ? f.labelEn : f.labelFa}
                </option>
              ))}
            </select>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "UI Font Size (px)" : "اندازه فونت رابط کاربری (px)"}</b>
              <small>
                {lang === "en" ? "Range: 12px to 20px" : "بازه مجاز: ۱۲ تا ۲۰ پیکسل"}
              </small>
            </div>
            <div className="slider-with-number">
              <input
                type="range"
                min={12}
                max={20}
                step={1}
                value={ap.ui_font_size}
                onChange={(e) =>
                  void persistPatch({
                    appearance: { ui_font_size: Number(e.target.value) },
                  })
                }
              />
              <span className="slider-value-pill" dir="ltr">
                {ap.ui_font_size}px
              </span>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Code & Formula Font Size (px)" : "اندازه فونت کد و فرمول (px)"}</b>
              <small>
                {lang === "en"
                  ? "Applies to inline code, LaTeX/math snippets, and structured outputs (11px–20px)."
                  : "برای بلوک‌های کد و خروجی‌های فنی در پاسخ‌های معلم (۱۱ تا ۲۰ پیکسل)."}
              </small>
            </div>
            <div className="slider-with-number">
              <input
                type="range"
                min={11}
                max={20}
                step={1}
                value={ap.code_font_size}
                onChange={(e) =>
                  void persistPatch({
                    appearance: { code_font_size: Number(e.target.value) },
                  })
                }
              />
              <span className="slider-value-pill" dir="ltr">
                {ap.code_font_size}px
              </span>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-label">
              <b>{lang === "en" ? "Reduce Motion" : "کاهش حرکت و انیمیشن"}</b>
              <small>
                {lang === "en"
                  ? "Minimize transitions and animations for comfort or accessibility."
                  : "کاهش یا غیرفعال‌سازی انیمیشن‌ها و جابه‌جایی‌های سریع رابط کاربری."}
              </small>
            </div>
            <div className="segmented-control">
              {(
                [
                  { id: "off", fa: "خاموش", en: "Off" },
                  { id: "on", fa: "روشن", en: "On" },
                  { id: "system", fa: "سیستم", en: "System" },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  className={ap.reduce_motion === opt.id ? "active" : ""}
                  onClick={() =>
                    void persistPatch({
                      appearance: { reduce_motion: opt.id as ReduceMotionMode },
                    })
                  }
                >
                  {lang === "en" ? opt.en : opt.fa}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Live Preview */}
        <section className="account-card">
          <div className="account-card-head">
            <h2>{lang === "en" ? "Live Preview" : "پیش‌نمایش زنده"}</h2>
          </div>
          <div
            className="appearance-live-preview"
            style={{
              background: computedPreview.bg,
              color: computedPreview.fg,
              borderColor: computedPreview.borderStrong,
              fontSize: `${ap.ui_font_size}px`,
            }}
          >
            <div
              className="preview-bubble-card"
              style={{
                background: computedPreview.cardBg,
                borderColor: computedPreview.borderSubtle,
              }}
            >
              <b>
                {lang === "en"
                  ? "Darsyar Physics Assistant"
                  : "پاسخ نمونه معلم خصوصی درسیار"}
              </b>
              <p style={{ color: computedPreview.secondaryInk }}>
                {lang === "en"
                  ? "Uniformly accelerated motion connects velocity, time, and displacement clearly:"
                  : "در حرکت با شتاب ثابت، رابطهٔ بین جابه‌جایی و زمان به‌صورت دقیق برقرار است:"}
              </p>
              <code
                dir="ltr"
                style={{
                  fontSize: `${ap.code_font_size}px`,
                  background: computedPreview.mutedBg,
                  color: computedPreview.fg,
                }}
              >
                x(t) = 0.5 * a * t^2 + v0 * t + x0
              </code>
              <div className="preview-action-row">
                <span
                  className="preview-cta-chip"
                  style={{ background: activePalette.accent, color: "#fff" }}
                >
                  {lang === "en" ? "Accent Action" : "دکمه اصلی"}
                </span>
                <small style={{ color: computedPreview.mutedInk }}>
                  {lang === "en" ? "Border & muted ink sample" : "نمونه متن کم‌رنگ و کادر"}
                </small>
              </div>
            </div>
          </div>
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
