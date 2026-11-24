"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  CreditCard,
  Database,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Zap,
} from "lucide-react";

export type RuntimeConfigValues = {
  demo_mode: boolean;
  llm_base_url: string;
  llm_timeout: number;
  max_concurrency: number;
  vision_model_a: string;
  vision_model_b: string;
  vision_model_primary: string;
  vision_model_escalation: string | null;
  tutor_model: string | null;
  speech_to_text_model: string | null;
  audio_base_url: string | null;
  escalate_figures: boolean;
  vector_backend: "qdrant" | "pgvector";
  qdrant_url: string;
  qdrant_collection: string;
  embedding_base_url: string | null;
  embedding_model: string;
  embedding_dimension: number;
  sms_provider: "demo" | "kavenegar" | "sms_ir" | "webhook";
  sms_sender: string | null;
  sms_template: string | null;
  sms_webhook_url: string | null;
  otp_ttl_seconds: number;
  otp_resend_seconds: number;
  otp_max_attempts: number;
  user_session_ttl_seconds: number;
  admin_session_ttl_seconds: number;
  payment_provider: "demo" | "zarinpal";
  zarinpal_sandbox: boolean;
  public_app_url: string | null;
};

export type SecretStatusItem = {
  configured: boolean;
  masked: string;
  source: "admin" | "env" | "unset";
};

export type ProviderPresetItem = {
  id: string;
  label: string;
  llm_base_url: string;
  suggested_tutor_model: string;
  suggested_vision_model: string;
  suggested_stt_model: string;
  suggested_embedding_model: string;
};

export type AdminSystemSettingsPayload = {
  config: RuntimeConfigValues;
  secrets: {
    llm_api_key: SecretStatusItem;
    audio_api_key: SecretStatusItem;
    embedding_api_key: SecretStatusItem;
    sms_api_key: SecretStatusItem;
    zarinpal_merchant_id: SecretStatusItem;
  };
  env_defaults: RuntimeConfigValues;
  overridden_keys: string[];
  auth_info: {
    admin_username: string;
    has_custom_auth_secret: boolean;
  };
  provider_presets: ProviderPresetItem[];
};

type AiTestResult = {
  ok: boolean;
  base_url: string;
  status_code: number | null;
  latency_ms: number;
  models: string[];
  models_count: number;
  error: string | null;
  prompt_test?: {
    ok: boolean;
    model?: string;
    latency_ms?: number;
    reply?: string;
    error?: string;
  } | null;
};

type VectorTestResult = {
  ok: boolean;
  backend: string;
  latency_ms: number;
  detail: string;
};

type SmsTestResult = {
  ok: boolean;
  provider: string;
  detail: string;
};

type AdminIntegrationsPanelProps = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
  onSettingsApplied?: (payload: AdminSystemSettingsPayload) => void;
};

type SecretKeyName =
  | "llm_api_key"
  | "audio_api_key"
  | "embedding_api_key"
  | "sms_api_key"
  | "zarinpal_merchant_id";

const SECRET_SOURCE_LABELS: Record<SecretStatusItem["source"], string> = {
  admin: "ذخیره‌شده در پنل",
  env: "مقدار .env سرور",
  unset: "تنظیم‌نشده",
};

export default function AdminIntegrationsPanel({
  authHeaders,
  onUnauthorized,
  onSettingsApplied,
}: AdminIntegrationsPanelProps) {
  const [data, setData] = useState<AdminSystemSettingsPayload | null>(null);
  const [draft, setDraft] = useState<RuntimeConfigValues | null>(null);
  const [secretInputs, setSecretInputs] = useState<Record<SecretKeyName, string>>({
    llm_api_key: "",
    audio_api_key: "",
    embedding_api_key: "",
    sms_api_key: "",
    zarinpal_merchant_id: "",
  });
  const [clearSecrets, setClearSecrets] = useState<Set<SecretKeyName>>(new Set());
  const [showSecrets, setShowSecrets] = useState<Record<SecretKeyName, boolean>>({
    llm_api_key: false,
    audio_api_key: false,
    embedding_api_key: false,
    sms_api_key: false,
    zarinpal_merchant_id: false,
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState<string | null>(null);
  const [bannerMessage, setBannerMessage] = useState("");
  const [bannerError, setBannerError] = useState("");

  // Live diagnostics state
  const [aiTesting, setAiTesting] = useState(false);
  const [runPromptProbe, setRunPromptProbe] = useState(true);
  const [aiTestResult, setAiTestResult] = useState<AiTestResult | null>(null);
  const [modelSearchFilter, setModelSearchFilter] = useState("");

  const [vectorTesting, setVectorTesting] = useState(false);
  const [vectorTestResult, setVectorTestResult] = useState<VectorTestResult | null>(null);

  const [smsTesting, setSmsTesting] = useState(false);
  const [smsTestPhone, setSmsTestPhone] = useState("");
  const [smsTestResult, setSmsTestResult] = useState<SmsTestResult | null>(null);

  const onUnauthorizedRef = useRef(onUnauthorized);
  const onSettingsAppliedRef = useRef(onSettingsApplied);
  useEffect(() => {
    onUnauthorizedRef.current = onUnauthorized;
    onSettingsAppliedRef.current = onSettingsApplied;
  }, [onSettingsApplied, onUnauthorized]);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setBannerError("");
    try {
      const res = await fetch("/api/v1/admin/settings", {
        cache: "no-store",
        credentials: "same-origin",
        headers: authHeaders,
      });
      if (res.status === 401) {
        onUnauthorizedRef.current();
        return;
      }
      const payload = (await res.json()) as AdminSystemSettingsPayload & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "خطا در دریافت تنظیمات سیستم");
      setData(payload);
      setDraft(payload.config);
      setClearSecrets(new Set());
      onSettingsAppliedRef.current?.(payload);
    } catch (cause) {
      setBannerError(cause instanceof Error ? cause.message : "خطا در دریافت تنظیمات");
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSettings();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadSettings]);

  const updateDraft = <K extends keyof RuntimeConfigValues>(key: K, value: RuntimeConfigValues[K]) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const handleApplyPreset = (preset: ProviderPresetItem) => {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            llm_base_url: preset.llm_base_url,
            tutor_model: prev.tutor_model || preset.suggested_tutor_model,
            vision_model_primary: preset.suggested_vision_model || prev.vision_model_primary,
            speech_to_text_model: prev.speech_to_text_model || preset.suggested_stt_model,
            embedding_model: preset.suggested_embedding_model || prev.embedding_model,
          }
        : prev
    );
    setBannerMessage(
      `پیش‌تنظیم «${preset.label}» روی فرم اعمال شد. کلید API را وارد کرده و برای ثبت نهایی ذخیره کنید.`
    );
    setBannerError("");
  };

  const handleSaveAll = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!draft) return;
    setSaving(true);
    setBannerMessage("");
    setBannerError("");
    try {
      const configPatch: Record<string, unknown> = { ...draft };
      for (const secretKey of Object.keys(secretInputs) as SecretKeyName[]) {
        const val = secretInputs[secretKey].trim();
        if (val) {
          configPatch[secretKey] = val;
        }
      }
      const res = await fetch("/api/v1/admin/settings", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          config: configPatch,
          clear_secrets: Array.from(clearSecrets),
        }),
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      const payload = (await res.json()) as AdminSystemSettingsPayload & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "ذخیره تنظیمات سیستم انجام نشد");
      setData(payload);
      setDraft(payload.config);
      setSecretInputs({
        llm_api_key: "",
        audio_api_key: "",
        embedding_api_key: "",
        sms_api_key: "",
        zarinpal_merchant_id: "",
      });
      setClearSecrets(new Set());
      onSettingsApplied?.(payload);
      setBannerMessage(
        "تمام تنظیمات هوش مصنوعی، مدل‌ها و درگاه‌ها ذخیره شد و بدون نیاز به ری‌استارت فوراً اعمال گردید."
      );
    } catch (cause) {
      setBannerError(cause instanceof Error ? cause.message : "خطا در ذخیره تنظیمات");
    } finally {
      setSaving(false);
    }
  };

  const handleResetSection = async (section: "all" | "ai" | "vector" | "sms" | "payment") => {
    setResetting(section);
    setBannerMessage("");
    setBannerError("");
    try {
      const res = await fetch("/api/v1/admin/settings/reset", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ section }),
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      const payload = (await res.json()) as AdminSystemSettingsPayload & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "بازنشانی تنظیمات انجام نشد");
      setData(payload);
      setDraft(payload.config);
      setSecretInputs({
        llm_api_key: "",
        audio_api_key: "",
        embedding_api_key: "",
        sms_api_key: "",
        zarinpal_merchant_id: "",
      });
      setClearSecrets(new Set());
      onSettingsApplied?.(payload);
      setBannerMessage(
        section === "all"
          ? "تمامی تنظیمات به مقادیر پایهٔ سرور (.env) بازگردانی شد."
          : `تنظیمات بخش «${section}» به مقادیر پایهٔ سرور بازگردانی شد.`
      );
    } catch (cause) {
      setBannerError(cause instanceof Error ? cause.message : "خطا در بازنشانی تنظیمات");
    } finally {
      setResetting(null);
    }
  };

  const handleTestAi = async () => {
    if (!draft) return;
    setAiTesting(true);
    setAiTestResult(null);
    setBannerError("");
    try {
      const res = await fetch("/api/v1/admin/settings/test-ai", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          llm_base_url: draft.llm_base_url,
          llm_api_key: secretInputs.llm_api_key.trim() || undefined,
          test_model: draft.tutor_model || draft.vision_model_primary,
          run_prompt: runPromptProbe,
        }),
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      const payload = (await res.json()) as AiTestResult & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "تست اتصال AI با خطا مواجه شد");
      setAiTestResult(payload);
    } catch (cause) {
      setBannerError(cause instanceof Error ? cause.message : "خطا در تست اتصال AI");
    } finally {
      setAiTesting(false);
    }
  };

  const handleTestVector = async () => {
    if (!draft) return;
    setVectorTesting(true);
    setVectorTestResult(null);
    try {
      const res = await fetch("/api/v1/admin/settings/test-vector", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          vector_backend: draft.vector_backend,
          qdrant_url: draft.qdrant_url,
          qdrant_collection: draft.qdrant_collection,
        }),
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      const payload = (await res.json()) as VectorTestResult & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "تست پایگاه برداری ناموفق بود");
      setVectorTestResult(payload);
    } catch (cause) {
      setVectorTestResult({
        ok: false,
        backend: draft.vector_backend,
        latency_ms: 0,
        detail: cause instanceof Error ? cause.message : "خطا در تست جستجوی برداری",
      });
    } finally {
      setVectorTesting(false);
    }
  };

  const handleTestSms = async () => {
    if (!draft) return;
    setSmsTesting(true);
    setSmsTestResult(null);
    try {
      const res = await fetch("/api/v1/admin/settings/test-sms", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          sms_provider: draft.sms_provider,
          sms_api_key: secretInputs.sms_api_key.trim() || undefined,
          sms_sender: draft.sms_sender,
          sms_template: draft.sms_template,
          sms_webhook_url: draft.sms_webhook_url,
          test_phone: smsTestPhone.trim() || undefined,
        }),
      });
      if (res.status === 401) {
        onUnauthorized();
        return;
      }
      const payload = (await res.json()) as SmsTestResult & { detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "بررسی درگاه پیامک ناموفق بود");
      setSmsTestResult(payload);
    } catch (cause) {
      setSmsTestResult({
        ok: false,
        provider: draft.sms_provider,
        detail: cause instanceof Error ? cause.message : "خطا در بررسی درگاه پیامک",
      });
    } finally {
      setSmsTesting(false);
    }
  };

  const renderSecretField = (
    key: SecretKeyName,
    label: string,
    placeholder: string,
    hint?: string
  ) => {
    const status = data?.secrets[key];
    const isMarkedClear = clearSecrets.has(key);
    return (
      <div className="form-field">
        <div className="secret-label-row">
          <span>{label}</span>
          {status && (
            <span className={`secret-status-pill ${isMarkedClear ? "unset" : status.source}`}>
              {isMarkedClear
                ? "در انتظار حذف تنظیم پنل"
                : status.configured
                ? `${SECRET_SOURCE_LABELS[status.source]} (${status.masked})`
                : "تنظیم‌نشده"}
            </span>
          )}
        </div>
        <div className="password-input-wrap">
          <input
            type={showSecrets[key] ? "text" : "password"}
            dir="ltr"
            value={secretInputs[key]}
            onChange={(e) => {
              const val = e.target.value;
              setSecretInputs((prev) => ({ ...prev, [key]: val }));
              if (val.trim()) {
                setClearSecrets((prev) => {
                  const next = new Set(prev);
                  next.delete(key);
                  return next;
                });
              }
            }}
            placeholder={
              status?.configured
                ? `برای تغییر کلید جدید را وارد کنید (فعلی: ${status.masked})`
                : placeholder
            }
            autoComplete="off"
          />
          <button
            type="button"
            className="password-toggle"
            onClick={() => setShowSecrets((prev) => ({ ...prev, [key]: !prev[key] }))}
            aria-label={showSecrets[key] ? "مخفی کردن کلید" : "نمایش کلید"}
          >
            {showSecrets[key] ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        </div>
        <div className="secret-field-meta">
          {hint && <small>{hint}</small>}
          {status?.source === "admin" && (
            <button
              type="button"
              className="secret-clear-btn"
              onClick={() => {
                setSecretInputs((prev) => ({ ...prev, [key]: "" }));
                setClearSecrets((prev) => {
                  const next = new Set(prev);
                  if (next.has(key)) next.delete(key);
                  else next.add(key);
                  return next;
                });
              }}
            >
              <Trash2 size={12} />
              {isMarkedClear ? "لغو حذف" : "پاک‌کردن کلید پنل و بازگشت به .env"}
            </button>
          )}
        </div>
      </div>
    );
  };

  if (loading || !draft || !data) {
    return (
      <section className="admin-card">
        <div className="review-loading">
          <LoaderCircle className="spin" size={20} />
          <span>در حال بارگذاری مرکز کنترل API هوش مصنوعی و درگاه‌ها...</span>
        </div>
      </section>
    );
  }

  const filteredDiscoveredModels = (aiTestResult?.models ?? []).filter((id) =>
    !modelSearchFilter.trim() ? true : id.toLowerCase().includes(modelSearchFilter.trim().toLowerCase())
  );

  return (
    <form className="admin-billing-stack" onSubmit={handleSaveAll}>
      {bannerMessage && (
        <div className="success-note admin-banner">
          <CheckCircle2 size={15} />
          <span>{bannerMessage}</span>
        </div>
      )}
      {bannerError && (
        <div className="inline-error admin-banner">
          <span>{bannerError}</span>
        </div>
      )}

      {/* Section 1: Execution Mode & Main AI API Endpoint */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>اتصال اصلی هوش مصنوعی (AI API Gateway) و حالت اجرا</h2>
            <p>
              کلید API، نشانی سرویس‌دهندهٔ سازگار با OpenAI و سوئیچ بین حالت نمایشی (Demo) و تولید واقعی (Live AI) را مدیریت کنید.
            </p>
          </div>
          <span className="step-badge">
            <Cpu size={15} />
          </span>
        </div>

        {/* Mode Switcher */}
        <div className="admin-mode-selector">
          <button
            type="button"
            className={`admin-mode-option ${draft.demo_mode ? "active demo" : ""}`}
            onClick={() => updateDraft("demo_mode", true)}
          >
            <Sparkles size={16} />
            <div>
              <b>حالت نمایشی (Demo Mode)</b>
              <small>پاسخ‌های ثابت آموزشی بدون مصرف توکن و بدون نیاز به اتصال API خارجی</small>
            </div>
          </button>
          <button
            type="button"
            className={`admin-mode-option ${!draft.demo_mode ? "active live" : ""}`}
            onClick={() => updateDraft("demo_mode", false)}
          >
            <Zap size={16} />
            <div>
              <b>حالت تولید واقعی (Live AI Mode)</b>
              <small>اجرای واقعی مدل‌های معلم، بینایی PDF/تصویر، تبدیل صدا، و جستجوی برداری</small>
            </div>
          </button>
        </div>

        {/* Quick Provider Presets */}
        <div className="admin-preset-bar">
          <span>پیش‌تنظیم سریع ارائه‌دهنده:</span>
          <div className="admin-preset-chips">
            {data.provider_presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`admin-preset-chip ${
                  draft.llm_base_url.replace(/\/$/, "") === preset.llm_base_url ? "active" : ""
                }`}
                onClick={() => handleApplyPreset(preset)}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <div className="admin-form" style={{ marginTop: 14 }}>
          <div className="form-row">
            <label className="form-field">
              <span>آدرس پایه API هوش مصنوعی (LLM Base URL)</span>
              <input
                dir="ltr"
                value={draft.llm_base_url}
                onChange={(e) => updateDraft("llm_base_url", e.target.value)}
                placeholder="https://api.openai.com/v1"
                required
              />
            </label>
            {renderSecretField(
              "llm_api_key",
              "کلید API اصلی (LLM API Key)",
              "sk-...",
              "کلید در سرور با امنیت نگهداری می‌شود و پس از ذخیره فقط به‌صورت ماسک‌شده نمایش داده می‌شود."
            )}
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>مهلت پاسخ API (ثانیه — Timeout)</span>
              <input
                type="number"
                min={1}
                max={600}
                value={draft.llm_timeout}
                onChange={(e) => updateDraft("llm_timeout", Number(e.target.value))}
              />
            </label>
            <label className="form-field">
              <span>حداکثر درخواست هم‌زمان (Max Concurrency)</span>
              <input
                type="number"
                min={1}
                max={64}
                value={draft.max_concurrency}
                onChange={(e) => updateDraft("max_concurrency", Number(e.target.value))}
              />
            </label>
          </div>

          {/* Live AI API Connection & Model Discovery Tester */}
          <div className="admin-tester-box">
            <div className="admin-tester-head">
              <div>
                <b>آزمایش زنده اتصال و دریافت لیست مدل‌های قابل دسترس</b>
                <small>با کلید واردشده (یا کلید ذخیره‌شده فعلی) به مسیر /models متصل می‌شود.</small>
              </div>
              <div className="admin-tester-controls">
                <label className="plan-active-toggle">
                  <input
                    type="checkbox"
                    checked={runPromptProbe}
                    onChange={(e) => setRunPromptProbe(e.target.checked)}
                  />
                  <span>تست پرامپت واقعی با مدل معلم</span>
                </label>
                <button
                  type="button"
                  className="outline-button"
                  disabled={aiTesting}
                  onClick={() => void handleTestAi()}
                >
                  {aiTesting ? <LoaderCircle className="spin" size={15} /> : <Zap size={15} />}
                  تست اتصال و کشف مدل‌ها
                </button>
              </div>
            </div>

            {aiTestResult && (
              <div className={`admin-test-result ${aiTestResult.ok ? "ok" : "err"}`}>
                <div className="admin-test-result-head">
                  {aiTestResult.ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                  <b>
                    {aiTestResult.ok
                      ? `اتصال برقرار شد (${aiTestResult.latency_ms} میلی‌ثانیه · ${aiTestResult.models_count} مدل یافت شد)`
                      : `اتصال برقرار نشد (${aiTestResult.latency_ms} میلی‌ثانیه)`}
                  </b>
                  {aiTestResult.status_code && (
                    <span className="badge-pill done" dir="ltr">
                      HTTP {aiTestResult.status_code}
                    </span>
                  )}
                </div>
                {aiTestResult.error && <p className="admin-test-error" dir="ltr">{aiTestResult.error}</p>}

                {aiTestResult.prompt_test && (
                  <div className={`admin-prompt-probe ${aiTestResult.prompt_test.ok ? "ok" : "err"}`}>
                    <b>
                      تست پرامپت ({aiTestResult.prompt_test.model}):{" "}
                      {aiTestResult.prompt_test.ok
                        ? `موفق (${aiTestResult.prompt_test.latency_ms}ms)`
                        : "ناموفق"}
                    </b>
                    {aiTestResult.prompt_test.reply && (
                      <span>پاسخ مدل: «{aiTestResult.prompt_test.reply}»</span>
                    )}
                    {aiTestResult.prompt_test.error && (
                      <small dir="ltr">{aiTestResult.prompt_test.error}</small>
                    )}
                  </div>
                )}

                {aiTestResult.models.length > 0 && (
                  <div className="admin-models-discovery">
                    <div className="admin-models-filter">
                      <span>مدل‌های در دسترس (کلیک برای انتخاب سریع):</span>
                      <input
                        dir="ltr"
                        placeholder="فیلتر نام مدل (مثلاً gpt-4o, gemini, qwen)..."
                        value={modelSearchFilter}
                        onChange={(e) => setModelSearchFilter(e.target.value)}
                      />
                    </div>
                    <div className="admin-models-list">
                      {filteredDiscoveredModels.slice(0, 40).map((modelId) => (
                        <div key={modelId} className="admin-discovered-model">
                          <code dir="ltr">{modelId}</code>
                          <div className="admin-model-assign-btns">
                            <button
                              type="button"
                              onClick={() => updateDraft("tutor_model", modelId)}
                              title="انتخاب به عنوان مدل معلم"
                            >
                              معلم
                            </button>
                            <button
                              type="button"
                              onClick={() => updateDraft("vision_model_primary", modelId)}
                              title="انتخاب به عنوان مدل بینایی اصلی"
                            >
                              بینایی
                            </button>
                            <button
                              type="button"
                              onClick={() => updateDraft("embedding_model", modelId)}
                              title="انتخاب به عنوان مدل بردارسازی"
                            >
                              امبدینگ
                            </button>
                            <button
                              type="button"
                              onClick={() => updateDraft("speech_to_text_model", modelId)}
                              title="انتخاب به عنوان مدل تبدیل صدا"
                            >
                              صدا
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Section 2: Specialized Model Routing Matrix */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>مسیریابی مدل‌های تخصصی (Tutor، Vision، Audio و Embedding)</h2>
            <p>برای هر وظیفه مدل دلخواه را تنظیم کنید؛ قابلیت تغییر در لحظه بدون توقف سیستم.</p>
          </div>
          <button
            type="button"
            className="outline-button"
            disabled={resetting === "ai"}
            onClick={() => void handleResetSection("ai")}
          >
            <RotateCcw size={14} /> بازنشانی بخش AI
          </button>
        </div>

        <div className="admin-form">
          <div className="form-row">
            <label className="form-field">
              <span>مدل معلم خصوصی و آزمون‌ساز (Tutor Model)</span>
              <input
                dir="ltr"
                value={draft.tutor_model ?? ""}
                onChange={(e) => updateDraft("tutor_model", e.target.value || null)}
                placeholder="gpt-4o"
              />
            </label>
            <label className="form-field">
              <span>مدل بینایی اصلی (OCR کتاب و عکس تمرین)</span>
              <input
                dir="ltr"
                value={draft.vision_model_primary}
                onChange={(e) => updateDraft("vision_model_primary", e.target.value)}
                placeholder="gpt-4o"
                required
              />
            </label>
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>مدل بینایی پشتیبان برای نمودارهای دشوار (Escalation)</span>
              <input
                dir="ltr"
                value={draft.vision_model_escalation ?? ""}
                onChange={(e) => updateDraft("vision_model_escalation", e.target.value || null)}
                placeholder="اختیاری — مثلاً openai/gpt-4.1"
              />
            </label>
            <div className="form-field" style={{ justifyContent: "center" }}>
              <label className="plan-active-toggle" style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  checked={draft.escalate_figures}
                  onChange={(e) => updateDraft("escalate_figures", e.target.checked)}
                />
                <span>ارسال خودکار صفحه‌های دارای شکل و نمودار به مدل پشتیبان (Escalate Figures)</span>
              </label>
            </div>
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>مدل مقایسه استخراج A (Vision A)</span>
              <input
                dir="ltr"
                value={draft.vision_model_a}
                onChange={(e) => updateDraft("vision_model_a", e.target.value)}
                required
              />
            </label>
            <label className="form-field">
              <span>مدل مقایسه استخراج B (Vision B)</span>
              <input
                dir="ltr"
                value={draft.vision_model_b}
                onChange={(e) => updateDraft("vision_model_b", e.target.value)}
                required
              />
            </label>
          </div>

          <div className="admin-sub-divider" />

          <div className="form-row">
            <label className="form-field">
              <span>مدل تبدیل گفتار به متن (Speech-to-Text)</span>
              <input
                dir="ltr"
                value={draft.speech_to_text_model ?? ""}
                onChange={(e) => updateDraft("speech_to_text_model", e.target.value || null)}
                placeholder="whisper-1"
              />
            </label>
            <label className="form-field">
              <span>آدرس API اختصاصی صدا (Audio Base URL — اختیاری)</span>
              <input
                dir="ltr"
                value={draft.audio_base_url ?? ""}
                onChange={(e) => updateDraft("audio_base_url", e.target.value || null)}
                placeholder="خالی = استفاده از آدرس API اصلی"
              />
            </label>
          </div>
          {renderSecretField(
            "audio_api_key",
            "کلید API اختصاصی صدا (Audio API Key — اختیاری)",
            "خالی = استفاده از کلید اصلی LLM"
          )}

          <div className="admin-sub-divider" />

          <div className="form-row">
            <label className="form-field">
              <span>مدل بردارسازی متن (Embedding Model)</span>
              <input
                dir="ltr"
                value={draft.embedding_model}
                onChange={(e) => updateDraft("embedding_model", e.target.value)}
                placeholder="text-embedding-3-small"
                required
              />
            </label>
            <label className="form-field">
              <span>ابعاد بردار (Embedding Dimension)</span>
              <input
                type="number"
                min={1}
                max={16384}
                value={draft.embedding_dimension}
                onChange={(e) => updateDraft("embedding_dimension", Number(e.target.value))}
              />
            </label>
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>آدرس API اختصاصی بردارسازی (Embedding Base URL — اختیاری)</span>
              <input
                dir="ltr"
                value={draft.embedding_base_url ?? ""}
                onChange={(e) => updateDraft("embedding_base_url", e.target.value || null)}
                placeholder="خالی = استفاده از آدرس API اصلی"
              />
            </label>
            {renderSecretField(
              "embedding_api_key",
              "کلید API اختصاصی بردارسازی (Embedding API Key — اختیاری)",
              "خالی = استفاده از کلید اصلی LLM"
            )}
          </div>
        </div>
      </section>

      {/* Section 3: Vector Search Backend */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>موتور جستجوی برداری و RAG کتاب‌های درسی</h2>
            <p>انتخاب بین pgvector داخل PostgreSQL/Supabase یا سرور مجزای Qdrant.</p>
          </div>
          <span className="step-badge">
            <Database size={15} />
          </span>
        </div>

        <div className="admin-form">
          <div className="form-row">
            <label className="form-field">
              <span>موتور جستجوی برداری (Vector Backend)</span>
              <select
                value={draft.vector_backend}
                onChange={(e) =>
                  updateDraft("vector_backend", e.target.value as "qdrant" | "pgvector")
                }
              >
                <option value="pgvector">pgvector (Supabase / PostgreSQL)</option>
                <option value="qdrant">Qdrant Server</option>
              </select>
            </label>
            <label className="form-field">
              <span>نشانی سرور Qdrant</span>
              <input
                dir="ltr"
                value={draft.qdrant_url}
                onChange={(e) => updateDraft("qdrant_url", e.target.value)}
                placeholder="http://127.0.0.1:6333"
              />
            </label>
            <label className="form-field">
              <span>نام کالکشن Qdrant</span>
              <input
                dir="ltr"
                value={draft.qdrant_collection}
                onChange={(e) => updateDraft("qdrant_collection", e.target.value)}
                placeholder="iran_textbooks"
              />
            </label>
          </div>

          <div className="admin-tester-box">
            <div className="admin-tester-head">
              <div>
                <b>تست سلامت پایگاه برداری</b>
                <small>بررسی اتصال و وضعیت جدول pgvector یا کالکشن‌های Qdrant</small>
              </div>
              <button
                type="button"
                className="outline-button"
                disabled={vectorTesting}
                onClick={() => void handleTestVector()}
              >
                {vectorTesting ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />}
                تست موتور برداری
              </button>
            </div>
            {vectorTestResult && (
              <div className={`admin-test-result ${vectorTestResult.ok ? "ok" : "err"}`}>
                <div className="admin-test-result-head">
                  {vectorTestResult.ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                  <b>{vectorTestResult.detail}</b>
                  <span className="badge-pill done" dir="ltr">
                    {vectorTestResult.backend} · {vectorTestResult.latency_ms}ms
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Section 4: SMS OTP Gateway & Session Security */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>درگاه پیامک احراز هویت (SMS OTP) و سیاست نشست‌ها</h2>
            <p>تنظیم سرویس‌دهنده پیامک (آزمایشی، کاوه‌نگار، sms.ir یا Webhook) و زمان‌بندی کد یک‌بارمصرف.</p>
          </div>
          <span className="step-badge">
            <MessageCircle size={15} />
          </span>
        </div>

        <div className="admin-form">
          <div className="form-row">
            <label className="form-field">
              <span>سرویس‌دهنده پیامک (SMS Provider)</span>
              <select
                value={draft.sms_provider}
                onChange={(e) =>
                  updateDraft(
                    "sms_provider",
                    e.target.value as "demo" | "kavenegar" | "sms_ir" | "webhook"
                  )
                }
              >
                <option value="demo">آزمایشی (Demo — نمایش کد روی صفحه)</option>
                <option value="kavenegar">کاوه‌نگار (Kavenegar)</option>
                <option value="sms_ir">اس‌ام‌اس.آی‌آر (sms.ir)</option>
                <option value="webhook">وب‌هوک سفارشی (Custom Webhook)</option>
              </select>
            </label>
            {renderSecretField(
              "sms_api_key",
              "کلید API پیامک (SMS API Key)",
              "کلید درگاه پیامک..."
            )}
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>شماره فرستنده (SMS Sender)</span>
              <input
                dir="ltr"
                value={draft.sms_sender ?? ""}
                onChange={(e) => updateDraft("sms_sender", e.target.value || null)}
                placeholder="مثلاً 2000500666"
              />
            </label>
            <label className="form-field">
              <span>الگو / پترن تأیید (SMS Template / Verify ID)</span>
              <input
                dir="ltr"
                value={draft.sms_template ?? ""}
                onChange={(e) => updateDraft("sms_template", e.target.value || null)}
                placeholder="مثلاً otp-login یا TemplateId"
              />
            </label>
            <label className="form-field">
              <span>نشانی وب‌هوک (برای حالت Webhook)</span>
              <input
                dir="ltr"
                value={draft.sms_webhook_url ?? ""}
                onChange={(e) => updateDraft("sms_webhook_url", e.target.value || null)}
                placeholder="https://example.com/sms-hook"
              />
            </label>
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>اعتبار کد OTP (ثانیه)</span>
              <input
                type="number"
                min={30}
                max={3600}
                value={draft.otp_ttl_seconds}
                onChange={(e) => updateDraft("otp_ttl_seconds", Number(e.target.value))}
              />
            </label>
            <label className="form-field">
              <span>فاصله ارسال مجدد (ثانیه)</span>
              <input
                type="number"
                min={0}
                max={600}
                value={draft.otp_resend_seconds}
                onChange={(e) => updateDraft("otp_resend_seconds", Number(e.target.value))}
              />
            </label>
            <label className="form-field">
              <span>حداکثر تلاش مجاز کد</span>
              <input
                type="number"
                min={1}
                max={20}
                value={draft.otp_max_attempts}
                onChange={(e) => updateDraft("otp_max_attempts", Number(e.target.value))}
              />
            </label>
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>اعتبار نشست دانش‌آموز (ثانیه — پیش‌فرض ۳۰ روز = 2592000)</span>
              <input
                type="number"
                min={300}
                value={draft.user_session_ttl_seconds}
                onChange={(e) => updateDraft("user_session_ttl_seconds", Number(e.target.value))}
              />
            </label>
            <label className="form-field">
              <span>اعتبار نشست مدیر (ثانیه — پیش‌فرض ۱۲ ساعت = 43200)</span>
              <input
                type="number"
                min={300}
                value={draft.admin_session_ttl_seconds}
                onChange={(e) => updateDraft("admin_session_ttl_seconds", Number(e.target.value))}
              />
            </label>
          </div>

          <div className="admin-tester-box">
            <div className="admin-tester-head">
              <div>
                <b>بررسی تنظیمات درگاه پیامک</b>
                <small>برای ارسال واقعی تست OTP شماره موبایل بنویسید؛ اگر خالی باشد فقط پیکربندی بررسی می‌شود.</small>
              </div>
              <div className="admin-tester-controls">
                <input
                  dir="ltr"
                  className="admin-compact-input"
                  placeholder="0912... (اختیاری)"
                  value={smsTestPhone}
                  onChange={(e) => setSmsTestPhone(e.target.value)}
                />
                <button
                  type="button"
                  className="outline-button"
                  disabled={smsTesting}
                  onClick={() => void handleTestSms()}
                >
                  {smsTesting ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}
                  بررسی / تست پیامک
                </button>
              </div>
            </div>
            {smsTestResult && (
              <div className={`admin-test-result ${smsTestResult.ok ? "ok" : "err"}`}>
                <div className="admin-test-result-head">
                  {smsTestResult.ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                  <b>{smsTestResult.detail}</b>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Section 5: Payment Gateway & Security Summary */}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>درگاه پرداخت (Payment Gateway) و نشانی عمومی اپلیکیشن</h2>
            <p>تنظیم درگاه پرداخت زرین‌پال یا درگاه آزمایشی و نشانی بازگشت از بانک.</p>
          </div>
          <span className="step-badge">
            <CreditCard size={15} />
          </span>
        </div>

        <div className="admin-form">
          <div className="form-row">
            <label className="form-field">
              <span>درگاه پرداخت (Payment Provider)</span>
              <select
                value={draft.payment_provider}
                onChange={(e) =>
                  updateDraft("payment_provider", e.target.value as "demo" | "zarinpal")
                }
              >
                <option value="demo">درگاه آزمایشی (Demo — پرداخت آنی تستی)</option>
                <option value="zarinpal">زرین‌پال (Zarinpal)</option>
              </select>
            </label>
            {renderSecretField(
              "zarinpal_merchant_id",
              "کد پذیرنده زرین‌پال (Merchant ID)",
              "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            )}
          </div>

          <div className="form-row">
            <label className="form-field">
              <span>نشانی عمومی اپلیکیشن برای بازگشت از درگاه (Public App URL)</span>
              <input
                dir="ltr"
                value={draft.public_app_url ?? ""}
                onChange={(e) => updateDraft("public_app_url", e.target.value || null)}
                placeholder="https://darsyar.example.com"
              />
            </label>
            <div className="form-field" style={{ justifyContent: "center" }}>
              <label className="plan-active-toggle" style={{ marginTop: 18 }}>
                <input
                  type="checkbox"
                  checked={draft.zarinpal_sandbox}
                  onChange={(e) => updateDraft("zarinpal_sandbox", e.target.checked)}
                />
                <span>استفاده از محیط آزمایشی زرین‌پال (Zarinpal Sandbox)</span>
              </label>
            </div>
          </div>

          <div className="review-tip" style={{ marginTop: 4 }}>
            <ShieldCheck size={16} />
            <span>
              حساب مدیریت فعال: <b dir="ltr">{data.auth_info.admin_username}</b> ·{" "}
              {data.auth_info.has_custom_auth_secret
                ? "کلید امضای توکن‌ها (AUTH_SECRET) اختصاصی است."
                : "توصیه: در محیط عملیاتی مقدار AUTH_SECRET و ADMIN_PASSWORD را در .env تنظیم کنید."}{" "}
              تغییر کلید API هوش مصنوعی در پنل، نشست مدیر و دانش‌آموزان را قطع نمی‌کند.
            </span>
          </div>
        </div>
      </section>

      {/* Bottom Save & Global Reset Actions */}
      <section className="admin-card admin-integrations-footer">
        <div className="admin-integrations-meta">
          <KeyRound size={16} />
          <span>
            {data.overridden_keys.length > 0
              ? `${data.overridden_keys.length} تنظیم در پایگاه‌داده جایگزین مقادیر پیش‌فرض شده است.`
              : "همهٔ تنظیمات از مقادیر پیش‌فرض .env سرور استفاده می‌کنند."}
          </span>
        </div>
        <div className="report-head-actions">
          <button
            type="button"
            className="outline-button"
            onClick={() => void loadSettings()}
            disabled={loading || saving}
          >
            <RefreshCw size={15} /> بارگذاری مجدد
          </button>
          <button
            type="button"
            className="outline-button"
            disabled={resetting !== null || saving}
            onClick={() => void handleResetSection("all")}
          >
            {resetting === "all" ? <LoaderCircle className="spin" size={15} /> : <RotateCcw size={15} />}
            بازنشانی کل تنظیمات به .env
          </button>
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
            ذخیره تمام تنظیمات و اعمال آنی
          </button>
        </div>
      </section>
    </form>
  );
}
