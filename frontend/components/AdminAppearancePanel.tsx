"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Eye,
  GitCompareArrows,
  LoaderCircle,
  Monitor,
  Moon,
  Palette,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";
import DiffViewer from "@/components/DiffViewer";
import {
  ACCENT_SWATCHES,
  applyContrastAdjustment,
  contrastGrade,
  contrastRatio,
  FONT_FAMILY_OPTIONS,
  normalizeHex,
  pickReadableInk,
  resolveEffectiveColorMode,
  THEME_PRESETS,
} from "@/lib/preferences";
import type {
  AppearanceModePalette,
  ColorMode,
  FontFamilyChoice,
  ReduceMotionMode,
  ThemePresetId,
  UserPreferences,
  VisualStyle,
} from "@/lib/types";

export type AdminPreferencesPatch = Partial<{
  general: Partial<UserPreferences["general"]>;
  appearance: Partial<
    Omit<UserPreferences["appearance"], "light" | "dark"> & {
      light: Partial<UserPreferences["appearance"]["light"]>;
      dark: Partial<UserPreferences["appearance"]["dark"]>;
    }
  >;
}>;

type AdminAppearancePanelProps = {
  preferences: UserPreferences;
  systemIsDark: boolean;
  saving: boolean;
  onPatchPreferences: (patch: AdminPreferencesPatch) => Promise<void>;
  onResetPreferences: () => Promise<void>;
};

const SAMPLE_BEFORE_MD = `# فصل ۱: حرکت بر خط راست
سرعت متوسط برابر نسبت جابه‌جایی به زمان است.
فرمول: v_avg = dx / dt`;

const SAMPLE_AFTER_MD = `# فصل ۱: حرکت بر خط راست
سرعت متوسط برابر نسبت جابه‌جایی به بازهٔ زمانی است:
$$v_{avg} = \\frac{\\Delta x}{\\Delta t}$$
واحد SI سرعت، متر بر ثانیه (m/s) است.`;

export default function AdminAppearancePanel({
  preferences,
  systemIsDark,
  saving,
  onPatchPreferences,
  onResetPreferences,
}: AdminAppearancePanelProps) {
  const ap = preferences.appearance;
  const effectiveMode = resolveEffectiveColorMode(preferences, systemIsDark);
  const [selectedEditMode, setSelectedEditMode] = useState<"light" | "dark">(effectiveMode);
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

  const accentContrastRatio = (() => {
    const accentHex = normalizeHex(activePalette.accent, "#177e77");
    const inkHex = pickReadableInk(accentHex);
    return contrastRatio(inkHex, accentHex);
  })();

  const runPatch = async (patch: AdminPreferencesPatch) => {
    setFeedback("");
    setError("");
    try {
      await onPatchPreferences(patch);
      setFeedback("تنظیمات ظاهری پنل مدیریت ذخیره و در کل پنل اعمال شد.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ذخیره تنظیمات ظاهری انجام نشد.");
    }
  };

  const updateActivePalette = (palettePatch: Partial<AppearanceModePalette>) => {
    if (!ap.separate_mode_themes) {
      const otherMode = editingMode === "dark" ? "light" : "dark";
      const otherPatch: Partial<AppearanceModePalette> = {};
      if (palettePatch.accent) otherPatch.accent = palettePatch.accent;
      if (palettePatch.font_family) otherPatch.font_family = palettePatch.font_family;
      if (palettePatch.theme) otherPatch.theme = palettePatch.theme;

      void runPatch({
        appearance: {
          [editingMode]: palettePatch,
          ...(Object.keys(otherPatch).length > 0 ? { [otherMode]: otherPatch } : {}),
        },
      });
      return;
    }

    void runPatch({
      appearance: {
        [editingMode]: palettePatch,
      },
    });
  };

  const handleSelectPreset = (presetId: ThemePresetId) => {
    const preset = THEME_PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    if (!ap.separate_mode_themes) {
      void runPatch({
        appearance: {
          light: { ...preset.light },
          dark: { ...preset.dark },
        },
      });
    } else {
      void runPatch({
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
    void runPatch({ appearance: { color_mode: mode } });
  };

  const handleAutoFixContrast = () => {
    const safeFg = editingMode === "dark" ? "#f1f6f5" : "#111b1e";
    const safeBg = editingMode === "dark" ? "#0c1316" : "#f7f9f8";
    void runPatch({
      appearance: {
        contrast: Math.max(58, ap.contrast),
        [editingMode]: {
          background: safeBg,
          foreground: safeFg,
        },
      },
    });
  };

  const handleReset = async () => {
    setFeedback("");
    setError("");
    try {
      await onResetPreferences();
      setFeedback("ظاهر پنل مدیریت به حالت پیش‌فرض درسیار بازگردانده شد.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "بازنشانی تنظیمات انجام نشد.");
    }
  };

  return (
    <div className="admin-billing-stack">
      {feedback && (
        <div className="success-note admin-banner" role="status">
          <Check size={15} />
          <span>{feedback}</span>
        </div>
      )}
      {error && (
        <div className="inline-error admin-banner" role="alert">
          {error}
        </div>
      )}

      {/* Mode, Layout & Separate Customization */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>
              <Palette size={16} /> سبک بصری، حالت رنگ و شخصی‌سازی مجزا
            </h2>
            <p>
              تنظیمات ظاهری پنل مدیریت در سرور ذخیره می‌شوند و پس از رفرش صفحه یا خروج و ورود مجدد دقیقاً بازیابی می‌گردند.
            </p>
          </div>
          <div className="appearance-head-actions">
            {saving && <LoaderCircle className="spin" size={16} aria-label="در حال ذخیره" />}
            <button
              type="button"
              className="outline-button"
              disabled={saving}
              onClick={() => void handleReset()}
            >
              <RotateCcw size={14} />
              <span>بازنشانی پیش‌فرض</span>
            </button>
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>حالت رنگ (Light / Dark / System Default)</b>
            <small>
              حالت فعال فعلی:{" "}
              <b>{effectiveMode === "dark" ? "تاریک (Dark)" : "روشن (Light)"}</b>
              {ap.color_mode === "system" ? " — هماهنگ با سیستم‌عامل" : ""}
            </small>
          </div>
          <div className="segmented-control" role="group" aria-label="حالت رنگ پنل مدیریت">
            <button
              type="button"
              aria-pressed={ap.color_mode === "light"}
              className={ap.color_mode === "light" ? "active" : ""}
              onClick={() => handleColorModeChange("light")}
            >
              <Sun size={14} />
              <span>روشن</span>
            </button>
            <button
              type="button"
              aria-pressed={ap.color_mode === "dark"}
              className={ap.color_mode === "dark" ? "active" : ""}
              onClick={() => handleColorModeChange("dark")}
            >
              <Moon size={14} />
              <span>تاریک</span>
            </button>
            <button
              type="button"
              aria-pressed={ap.color_mode === "system"}
              className={ap.color_mode === "system" ? "active" : ""}
              onClick={() => handleColorModeChange("system")}
            >
              <Monitor size={14} />
              <span>پیش‌فرض سیستم</span>
            </button>
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>سبک چیدمان (Visual Style)</b>
            <small>انحنای کارت‌ها، کنترل‌ها و تراکم عناصر در تمام تب‌های پنل مدیریت.</small>
          </div>
          <div className="segmented-control" role="group" aria-label="سبک چیدمان">
            {(
              [
                { id: "standard", label: "استاندارد" },
                { id: "modern", label: "مدرن و باز" },
                { id: "compact", label: "فشرده" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                aria-pressed={ap.visual_style === opt.id}
                className={ap.visual_style === opt.id ? "active" : ""}
                onClick={() =>
                  void runPatch({
                    appearance: { visual_style: opt.id as VisualStyle },
                  })
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>شخصی‌سازی مجزای حالت روشن و تاریک</b>
            <small>
              پالت تم، Accent، رنگ پس‌زمینه، رنگ متن و فونت برای حالت روشن و حالت تاریک مستقل از هم ذخیره شوند.
            </small>
          </div>
          <label className="switch-control">
            <input
              type="checkbox"
              aria-label="شخصی‌سازی مجزای حالت روشن و تاریک"
              checked={ap.separate_mode_themes}
              onChange={(e) =>
                void runPatch({
                  appearance: { separate_mode_themes: e.target.checked },
                })
              }
            />
            <span className="switch-track" />
          </label>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>نشانگرهای تفاوت خطوط (Diff Markers)</b>
            <small>
              نمایش نشانگرهای رنگی و نمادی (<code>+</code> افزوده، <code>-</code> حذف، <code>~</code> تغییر) هنگام بازبینی و ویرایش متن کتاب‌ها و پیش‌نمایش Diff.
            </small>
          </div>
          <label className="switch-control">
            <input
              type="checkbox"
              aria-label="فعال‌سازی نشانگرهای تفاوت (Diff Markers)"
              checked={ap.diff_markers !== false}
              onChange={(e) =>
                void runPatch({
                  appearance: { diff_markers: e.target.checked },
                })
              }
            />
            <span className="switch-track" />
          </label>
        </div>
      </section>

      {/* Presets, Accent, Background, Foreground & Contrast */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>
              <Sparkles size={16} /> تم‌ها، Accent، رنگ پس‌زمینه و رنگ متن
            </h2>
            <p>
              {ap.separate_mode_themes
                ? `در حال ویرایش پالت مستقل حالت «${editingMode === "dark" ? "تاریک" : "روشن"}».`
                : "تغییرات تم و رنگ تاکیدی به‌صورت هماهنگ تنظیم می‌شوند."}
            </p>
          </div>

          {ap.separate_mode_themes && (
            <div className="segmented-control" role="group" aria-label="انتخاب پالت برای ویرایش">
              <button
                type="button"
                aria-pressed={editingMode === "light"}
                className={editingMode === "light" ? "active" : ""}
                onClick={() => setSelectedEditMode("light")}
              >
                <Sun size={14} />
                <span>پالت روشن</span>
              </button>
              <button
                type="button"
                aria-pressed={editingMode === "dark"}
                className={editingMode === "dark" ? "active" : ""}
                onClick={() => setSelectedEditMode("dark")}
              >
                <Moon size={14} />
                <span>پالت تاریک</span>
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
                aria-pressed={selected}
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
                  <span className="theme-preset-dot" style={{ background: modePal.accent }} />
                  <span className="theme-preset-aa">Aa</span>
                </div>
                <b>{preset.nameFa}</b>
                {selected && (
                  <span className="theme-preset-check" aria-hidden="true">
                    <Check size={12} />
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="appearance-colors-grid">
          <div className="color-control-block">
            <label>رنگ تاکیدی (Accent Color)</label>
            <div className="swatch-row">
              {ACCENT_SWATCHES.map((sw) => (
                <button
                  key={sw.hex}
                  type="button"
                  aria-label={`انتخاب رنگ تاکیدی ${sw.labelFa}`}
                  className={`color-swatch ${
                    normalizeHex(activePalette.accent, "") === sw.hex ? "active" : ""
                  }`}
                  style={{ background: sw.hex }}
                  title={sw.labelFa}
                  onClick={() => updateActivePalette({ accent: sw.hex })}
                />
              ))}
              <label className="color-picker-chip">
                <input
                  type="color"
                  aria-label="انتخابگر رنگ تاکیدی دلخواه"
                  value={normalizeHex(activePalette.accent, "#177e77")}
                  onChange={(e) => updateActivePalette({ accent: e.target.value })}
                />
                <span dir="ltr">{normalizeHex(activePalette.accent, "#177e77")}</span>
              </label>
            </div>
          </div>

          <div className="color-pair-row">
            <div className="color-control-block">
              <label htmlFor="admin-bg-color-text">رنگ پس‌زمینه (Background)</label>
              <div className="color-input-box">
                <input
                  type="color"
                  aria-label="انتخابگر رنگ پس‌زمینه"
                  value={normalizeHex(activePalette.background, "#f7f9f8")}
                  onChange={(e) => updateActivePalette({ background: e.target.value })}
                />
                <input
                  id="admin-bg-color-text"
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
              <label htmlFor="admin-fg-color-text">رنگ متن (Text / Foreground)</label>
              <div className="color-input-box">
                <input
                  type="color"
                  aria-label="انتخابگر رنگ متن"
                  value={normalizeHex(activePalette.foreground, "#202b35")}
                  onChange={(e) => updateActivePalette({ foreground: e.target.value })}
                />
                <input
                  id="admin-fg-color-text"
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

        {/* Contrast Slider + Readability Check */}
        <div className="contrast-panel">
          <div className="contrast-head">
            <div>
              <b>تنظیم کنتراست و خوانایی (Contrast)</b>
              <small>شدت تفکیک متن، کادرها و سطوح در محدوده ۰ تا ۱۰۰.</small>
            </div>
            <div className={`contrast-badge ${grade.passesAA ? "ok" : "warn"}`}>
              <span dir="ltr">
                {computedPreview.ratio.toFixed(1)}:1 · WCAG {grade.level}
              </span>
            </div>
          </div>

          <div className="slider-control-row">
            <input
              type="range"
              aria-label="میزان کنتراست"
              min={0}
              max={100}
              step={1}
              value={ap.contrast}
              onChange={(e) =>
                void runPatch({
                  appearance: { contrast: Number(e.target.value) },
                })
              }
            />
            <span className="slider-value-pill" dir="ltr">
              {ap.contrast}%
            </span>
          </div>

          {!grade.passesAA && (
            <div className="warning-banner" role="alert">
              <AlertTriangle size={16} />
              <span>
                کنتراست فعلی ({computedPreview.ratio.toFixed(1)}:1) کمتر از استاندارد WCAG AA (4.5:1) است و ممکن است خوانایی متن کاهش یابد.
              </span>
              <button type="button" className="outline-button" onClick={handleAutoFixContrast}>
                اصلاح خودکار کنتراست
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Typography & Reduce Motion */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>تایپوگرافی (فونت UI و کد) و کاهش حرکت (Reduce Motion)</h2>
            <p>اندازه فونت رابط کاربری و اندازه فونت ویرایشگر Markdown/کد به‌صورت مجزا کنترل می‌شوند.</p>
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>فونت رابط کاربری (UI Font Family)</b>
            <small>در حالت شخصی‌سازی مجزا، برای حالت روشن و تاریک جداگانه ذخیره می‌شود.</small>
          </div>
          <select
            className="settings-select"
            aria-label="فونت رابط کاربری"
            value={activePalette.font_family}
            onChange={(e) =>
              updateActivePalette({ font_family: e.target.value as FontFamilyChoice })
            }
          >
            {FONT_FAMILY_OPTIONS.map((f) => (
              <option key={f.id} value={f.id}>
                {f.labelFa}
              </option>
            ))}
          </select>
        </div>

        <div className="settings-row">
          <div className="settings-row-label">
            <b>اندازه فونت رابط کاربری (UI Font Size)</b>
            <small>بازه مجاز: ۱۲ تا ۲۰ پیکسل</small>
          </div>
          <div className="slider-with-number">
            <input
              type="range"
              aria-label="اندازه فونت رابط کاربری"
              min={12}
              max={20}
              step={1}
              value={ap.ui_font_size}
              onChange={(e) =>
                void runPatch({
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
            <b>اندازه فونت کد و Markdown (Code Font Size)</b>
            <small>اعمال مستقیم روی ویرایشگر متن صفحه‌ها، Diff خطوط و بلوک‌های کد (۱۱ تا ۲۰ پیکسل).</small>
          </div>
          <div className="slider-with-number">
            <input
              type="range"
              aria-label="اندازه فونت کد"
              min={11}
              max={20}
              step={1}
              value={ap.code_font_size}
              onChange={(e) =>
                void runPatch({
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
            <b>کاهش حرکت و انیمیشن (Reduce Motion)</b>
            <small>برای راحتی بصری و دسترس‌پذیری، انیمیشن‌ها و ترنزیشن‌ها را به حداقل می‌رساند.</small>
          </div>
          <div className="segmented-control" role="group" aria-label="کاهش حرکت">
            {(
              [
                { id: "off", label: "خاموش" },
                { id: "on", label: "روشن" },
                { id: "system", label: "سیستم" },
              ] as const
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                aria-pressed={ap.reduce_motion === opt.id}
                className={ap.reduce_motion === opt.id ? "active" : ""}
                onClick={() =>
                  void runPatch({
                    appearance: { reduce_motion: opt.id as ReduceMotionMode },
                  })
                }
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Live Preview & Accessibility / Readability Audit */}
      <div className="admin-appearance-bottom-grid">
        <section className="admin-card">
          <div className="card-heading">
            <div>
              <h2>
                <Eye size={16} /> پیش‌نمایش زنده ظاهر و Diff Markers
              </h2>
              <p>تم، اندازه فونت UI/کد، کنتراست و نشانگرهای Diff به‌صورت زنده نمایش داده می‌شوند.</p>
            </div>
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
              <b>نمونه کارت و کنترل پنل مدیریت</b>
              <p style={{ color: computedPreview.secondaryInk }}>
                متن راهنما و توضیح وضعیت کتاب‌ها با فونت {ap.ui_font_size}px و کنتراست{" "}
                {computedPreview.ratio.toFixed(1)}:1 نمایش داده می‌شود.
              </p>
              <code
                dir="ltr"
                style={{
                  fontSize: `${ap.code_font_size}px`,
                  background: computedPreview.mutedBg,
                  color: computedPreview.fg,
                }}
              >
                {`GET /api/v1/admin/preferences -> code_font_size: ${ap.code_font_size}px`}
              </code>
              <div className="preview-action-row">
                <span
                  className="preview-cta-chip"
                  style={{
                    background: activePalette.accent,
                    color: "var(--accent-ink)",
                  }}
                >
                  دکمه اصلی با Accent
                </span>
                <small style={{ color: computedPreview.mutedInk }}>متن کم‌اهمیت / حاشیه</small>
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <DiffViewer
                beforeText={SAMPLE_BEFORE_MD}
                afterText={SAMPLE_AFTER_MD}
                diffMarkersEnabled={ap.diff_markers !== false}
                codeFontSize={ap.code_font_size}
                title="پیش‌نمایش نشانگرهای Diff در بازبینی صفحه"
              />
            </div>
          </div>
        </section>

        <section className="admin-card">
          <div className="card-heading">
            <div>
              <h2>
                <ShieldCheck size={16} /> بررسی خوانایی و دسترس‌پذیری (A11y Audit)
              </h2>
              <p>ارزیابی خودکار کنتراست WCAG 2.1، تایپوگرافی، انیمیشن و نشانگرهای غیررنگی.</p>
            </div>
          </div>

          <div className="admin-a11y-list">
            <div className={`admin-a11y-item ${grade.passesAA ? "pass" : "warn"}`}>
              {grade.passesAA ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <div>
                <b>کنتراست متن روی پس‌زمینه: {computedPreview.ratio.toFixed(1)}:1</b>
                <small>
                  {grade.passesAA
                    ? `استاندارد WCAG ${grade.level} برقرار است و متن‌ها با وضوح بالا خوانا هستند.`
                    : "نسبت کنتراست کمتر از ۴.۵:۱ است؛ از دکمه اصلاح خودکار کنتراست استفاده کنید."}
                </small>
              </div>
            </div>

            <div className={`admin-a11y-item ${accentContrastRatio >= 4.5 ? "pass" : "warn"}`}>
              {accentContrastRatio >= 4.5 ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <div>
                <b>کنتراست دکمه‌های تاکیدی (Accent): {accentContrastRatio.toFixed(1)}:1</b>
                <small>رنگ متن روی دکمه‌های اصلی به‌صورت خودکار برای حداکثر خوانایی انتخاب می‌شود.</small>
              </div>
            </div>

            <div className="admin-a11y-item pass">
              <GitCompareArrows size={16} />
              <div>
                <b>نشانگرهای غیررنگی Diff Markers: {ap.diff_markers !== false ? "فعال" : "خاموش"}</b>
                <small>
                  علاوه بر رنگ، نمادهای متنی (<code>+</code> و <code>-</code>) و برچسب‌های صفحه‌خوان (SR) تعبیه شده‌اند.
                </small>
              </div>
            </div>

            <div className="admin-a11y-item pass">
              <CheckCircle2 size={16} />
              <div>
                <b>مقیاس‌پذیری فونت و حرکت</b>
                <small>
                  فونت UI ({ap.ui_font_size}px)، فونت کد ({ap.code_font_size}px) و وضعیت Reduce Motion ({ap.reduce_motion}) روی کل پنل مدیریت اعمال می‌شوند.
                </small>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
