"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/toast";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  KeyRound,
  LoaderCircle,
  Plus,
  RefreshCw,
  Route,
  Save,
  Trash2,
  Zap,
} from "lucide-react";

export type AdminProvider = {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  capabilities: string[];
  is_active: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  last_test_status: string | null;
  last_test_latency_ms: number | null;
  last_test_at: string | null;
};

export type AdminFeatureRoute = {
  id: number;
  feature_key: string;
  provider_id: number;
  model_name: string;
  temperature: number;
  max_tokens: number | null;
  fallback_provider_id: number | null;
  fallback_model_name: string | null;
  fallback_chain?: { provider_id: number; model_name: string | null }[];
  is_active: boolean;
};

type ProviderListPayload = {
  providers: AdminProvider[];
  provider_types: string[];
  capabilities: string[];
};

type RouteListPayload = {
  routes: AdminFeatureRoute[];
  providers: { id: number; name: string; is_active: boolean; capabilities: string[] }[];
  feature_keys: { key: string; label_fa: string }[];
};

const PROVIDER_TYPE_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  openai_compatible: "سازگار با OpenAI",
  local: "لوکال / سرور اختصاصی",
};

const CAPABILITY_LABELS: Record<string, string> = {
  chat: "گفت‌وگو",
  vision: "بینایی",
  stt: "گفتار به متن",
  tts: "متن به گفتار",
  embedding: "بردارسازی",
};

export default function AdminProvidersPanel({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [providers, setProviders] = useState<AdminProvider[]>([]);
  const [providerTypes, setProviderTypes] = useState<string[]>([]);
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [routePayload, setRoutePayload] = useState<RouteListPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  // New-provider form
  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState("openai");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formCaps, setFormCaps] = useState<string[]>(["chat"]);

  const handle = useCallback(
    (status: number) => {
      if (status === 401) onUnauthorized();
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [providersRes, routesRes] = await Promise.all([
        fetch("/api/v1/admin/providers", {
          credentials: "same-origin",
          headers: authHeaders,
        }),
        fetch("/api/v1/admin/routes", {
          credentials: "same-origin",
          headers: authHeaders,
        }),
      ]);
      if (!handle(providersRes.status) || !handle(routesRes.status)) {
        setError("دسترسی مدیریت منقضی شده است.");
        return;
      }
      const providerData = (await providersRes.json()) as ProviderListPayload;
      setProviders(providerData.providers);
      setProviderTypes(providerData.provider_types);
      setCapabilities(providerData.capabilities);
      setRoutePayload((await routesRes.json()) as RouteListPayload);
    } catch {
      setError("بارگذاری تنظیمات ارائه‌دهنده‌ها ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, handle]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const activeProviders = useMemo(
    () => providers.filter((provider) => provider.is_active),
    [providers],
  );

  async function createProvider(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (!formName.trim()) {
      setError("نام ارائه‌دهنده را وارد کنید.");
      return;
    }
    const response = await fetch("/api/v1/admin/providers", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        name: formName.trim(),
        provider_type: formType,
        base_url: formBaseUrl.trim() || null,
        api_key: formApiKey.trim() || null,
        capabilities: formCaps,
        is_active: true,
      }),
    });
    if (!handle(response.status)) {
      const detail = await response.json().catch(() => ({}));
      setError(detail?.detail ?? "ثبت ارائه‌دهنده ناموفق بود.");
      return;
    }
    setMessage("ارائه‌دهنده ثبت شد. کلید API فقط رمزنگاری‌شده ذخیره می‌شود.");
    setFormName("");
    setFormBaseUrl("");
    setFormApiKey("");
    setFormCaps(["chat"]);
    await load();
  }

  async function testProvider(id: number) {
    setBusyId(id);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/v1/admin/providers/${id}/test`, {
        method: "POST",
        credentials: "same-origin",
        headers: authHeaders,
      });
      if (!handle(response.status)) {
        toast.error("تست اتصال ناموفق بود.");
        return;
      }
      const payload = await response.json();
      if (payload.ok) {
        toast.success(
          `اتصال موفق (${payload.latency_ms} میلی‌ثانیه${payload.models_count ? ` · ${payload.models_count} مدل` : ""}).`,
        );
      } else {
        toast.error(`اتصال برقرار نشد: ${payload.error ?? "خطای نامشخص"}`);
      }
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function toggleProvider(provider: AdminProvider) {
    setBusyId(provider.id);
    try {
      const response = await fetch(`/api/v1/admin/providers/${provider.id}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ is_active: !provider.is_active }),
      });
      if (handle(response.status)) await load();
    } finally {
      setBusyId(null);
    }
  }

  async function deleteProvider(provider: AdminProvider) {
    setBusyId(provider.id);
    setError("");
    try {
      const response = await fetch(`/api/v1/admin/providers/${provider.id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: authHeaders,
      });
      if (!handle(response.status)) {
        const detail = await response.json().catch(() => ({}));
        setError(detail?.detail ?? "حذف ناموفق بود.");
        return;
      }
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function saveRoute(
    featureKey: string,
    providerId: number,
    modelName: string,
    temperature: number,
    fallbackChain: { provider_id: number; model_name: string | null }[],
  ) {
    setError("");
    setMessage("");
    const response = await fetch("/api/v1/admin/routes", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        feature_key: featureKey,
        provider_id: providerId,
        model_name: modelName,
        temperature,
        fallback_chain: fallbackChain,
        is_active: true,
      }),
    });
    if (!handle(response.status)) {
      const detail = await response.json().catch(() => ({}));
      setError(detail?.detail ?? "ذخیرهٔ مسیر مدل ناموفق بود.");
      return;
    }
    setMessage("مسیر اصلی و زنجیرهٔ جایگزین ذخیره شد.");
    await load();
  }

  if (loading) {
    return (
      <div className="admin-card admin-empty">
        <div>
          <LoaderCircle size={22} className="spin" />
        </div>
        <b>بارگذاری ارائه‌دهنده‌ها و مسیر مدل‌ها…</b>
      </div>
    );
  }

  return (
    <div className="admin-billing-stack">
      {message && (
        <div className="success-note admin-banner">
          <CheckCircle2 size={15} />
          {message}
        </div>
      )}
      {error && <div className="inline-error admin-banner">{error}</div>}

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>افزودن ارائه‌دهندهٔ هوش مصنوعی</h2>
            <p>
              کلید API با Fernet رمزنگاری و فقط رمزنگاری‌شده ذخیره می‌شود؛ در هیچ پاسخ API
              به‌صورت متن ساده برنمی‌گردد. دانش‌آموزان به این بخش دسترسی ندارند.
            </p>
          </div>
          <span className="step-badge">
            <KeyRound size={14} />
          </span>
        </div>

        <form className="admin-form" onSubmit={createProvider}>
          <div className="form-row">
            <label className="form-field">
              <span>نام نمایشی</span>
              <input
                value={formName}
                onChange={(event) => setFormName(event.target.value)}
                placeholder="مثلاً OpenAI اصلی"
                maxLength={120}
              />
            </label>
            <label className="form-field">
              <span>نوع ارائه‌دهنده</span>
              <select value={formType} onChange={(event) => setFormType(event.target.value)}>
                {(providerTypes.length ? providerTypes : Object.keys(PROVIDER_TYPE_LABELS)).map(
                  (type) => (
                    <option key={type} value={type}>
                      {PROVIDER_TYPE_LABELS[type] ?? type}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
          <label className="form-field">
            <span>نشانی پایه (Base URL)</span>
            <input
              dir="ltr"
              value={formBaseUrl}
              onChange={(event) => setFormBaseUrl(event.target.value)}
              placeholder="https://api.openai.com/v1"
            />
          </label>
          <label className="form-field">
            <span>کلید API</span>
            <input
              dir="ltr"
              type="password"
              value={formApiKey}
              onChange={(event) => setFormApiKey(event.target.value)}
              placeholder="sk-..."
              autoComplete="off"
            />
          </label>
          <div className="form-field">
            <span>قابلیت‌ها</span>
            <div className="admin-chip-row">
              {(capabilities.length ? capabilities : Object.keys(CAPABILITY_LABELS)).map((cap) => {
                const active = formCaps.includes(cap);
                return (
                  <button
                    key={cap}
                    type="button"
                    className={`admin-theme-chip ${active ? "active" : ""}`}
                    onClick={() =>
                      setFormCaps((prev) =>
                        prev.includes(cap) ? prev.filter((item) => item !== cap) : [...prev, cap],
                      )
                    }
                  >
                    {CAPABILITY_LABELS[cap] ?? cap}
                  </button>
                );
              })}
            </div>
          </div>
          <button className="primary-button admin-submit" type="submit">
            <Plus size={17} /> ثبت ارائه‌دهنده
          </button>
        </form>
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>ارائه‌دهنده‌های ثبت‌شده</h2>
            <p>تست اتصال زنده، فعال/غیرفعال‌سازی و حذف ارائه‌دهنده‌های بدون مسیر مدل.</p>
          </div>
          <button type="button" className="admin-theme-chip" onClick={() => void load()}>
            <RefreshCw size={14} /> بازخوانی
          </button>
        </div>

        {providers.length === 0 ? (
          <div className="admin-empty">
            <div>
              <Cpu size={22} />
            </div>
            <b>هنوز ارائه‌دهنده‌ای ثبت نشده است</b>
            <span>با فرم بالا اولین ارائه‌دهنده را اضافه کنید.</span>
          </div>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>نام</th>
                  <th>نوع</th>
                  <th>کلید</th>
                  <th>قابلیت‌ها</th>
                  <th>آخرین تست</th>
                  <th>وضعیت</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {providers.map((provider) => (
                  <tr key={provider.id}>
                    <td>
                      <b>{provider.name}</b>
                      {provider.base_url && (
                        <div className="admin-muted" dir="ltr">
                          {provider.base_url}
                        </div>
                      )}
                    </td>
                    <td>{PROVIDER_TYPE_LABELS[provider.provider_type] ?? provider.provider_type}</td>
                    <td dir="ltr">
                      {provider.has_api_key ? provider.api_key_masked : "—"}
                    </td>
                    <td>
                      {provider.capabilities.length
                        ? provider.capabilities
                            .map((cap) => CAPABILITY_LABELS[cap] ?? cap)
                            .join(" · ")
                        : "—"}
                    </td>
                    <td>
                      {provider.last_test_status ? (
                        <span
                          className={`admin-status ${provider.last_test_status === "ok" ? "ok" : "bad"}`}
                        >
                          {provider.last_test_status === "ok" ? (
                            <CheckCircle2 size={13} />
                          ) : (
                            <AlertTriangle size={13} />
                          )}
                          {provider.last_test_status === "ok" ? "موفق" : "ناموفق"}
                          {provider.last_test_latency_ms != null
                            ? ` · ${provider.last_test_latency_ms}ms`
                            : ""}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="admin-theme-chip"
                        onClick={() => void toggleProvider(provider)}
                        disabled={busyId === provider.id}
                      >
                        {provider.is_active ? "فعال" : "غیرفعال"}
                      </button>
                    </td>
                    <td>
                      <div className="admin-chip-row">
                        <button
                          type="button"
                          className="admin-theme-chip"
                          onClick={() => void testProvider(provider.id)}
                          disabled={busyId === provider.id}
                        >
                          {busyId === provider.id ? (
                            <LoaderCircle size={14} className="spin" />
                          ) : (
                            <Zap size={14} />
                          )}
                          تست
                        </button>
                        <button
                          type="button"
                          className="admin-logout-btn"
                          onClick={() => void deleteProvider(provider)}
                          disabled={busyId === provider.id}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>مسیر مدل هر قابلیت</h2>
            <p>
              برای هر قابلیت (گفت‌وگو، حل تمرین، آزمون، تصویر، گفتار، بردارسازی) مشخص کنید کدام
              ارائه‌دهنده و مدل استفاده شود. بدون مسیر، مقدار پیش‌فرض سرور به کار می‌رود.
            </p>
          </div>
          <span className="step-badge">
            <Route size={14} />
          </span>
        </div>

        <RouteMatrix
          payload={routePayload}
          providers={activeProviders}
          onSave={saveRoute}
        />
      </section>
    </div>
  );
}

function RouteMatrix({
  payload,
  providers,
  onSave,
}: {
  payload: RouteListPayload | null;
  providers: AdminProvider[];
  onSave: (
    featureKey: string,
    providerId: number,
    modelName: string,
    temperature: number,
    fallbackChain: { provider_id: number; model_name: string | null }[],
  ) => Promise<void>;
}) {
  type FallbackDraft = { providerId: string; modelName: string };
  type RouteDraft = {
    providerId: string;
    modelName: string;
    temperature: string;
    fallbackChain: FallbackDraft[];
  };
  const [drafts, setDrafts] = useState<Record<string, RouteDraft>>({});

  useEffect(() => {
    if (!payload) return;
    const next: Record<string, RouteDraft> = {};
    for (const feature of payload.feature_keys) {
      const existing = payload.routes.find((route) => route.feature_key === feature.key);
      const fallbackChain = existing?.fallback_chain?.length
        ? existing.fallback_chain.map((item) => ({
            providerId: String(item.provider_id),
            modelName: item.model_name ?? "",
          }))
        : existing?.fallback_provider_id
          ? [{
              providerId: String(existing.fallback_provider_id),
              modelName: existing.fallback_model_name ?? "",
            }]
          : [];
      next[feature.key] = {
        providerId: existing ? String(existing.provider_id) : "",
        modelName: existing?.model_name ?? "",
        temperature: existing ? String(existing.temperature) : "0.2",
        fallbackChain,
      };
    }
    const timer = window.setTimeout(() => setDrafts(next), 0);
    return () => window.clearTimeout(timer);
  }, [payload]);

  if (!payload) return <div className="admin-empty">داده‌ای برای مسیر مدل‌ها موجود نیست.</div>;
  if (providers.length === 0) {
    return <div className="admin-empty">ابتدا یک ارائه‌دهندهٔ فعال ثبت کنید.</div>;
  }

  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            <th>قابلیت</th>
            <th>ارائه‌دهندهٔ اصلی</th>
            <th>مدل اصلی</th>
            <th>زنجیرهٔ جایگزین (به‌ترتیب)</th>
            <th>دما</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {payload.feature_keys.map((feature) => {
            const draft = drafts[feature.key] ?? {
              providerId: "",
              modelName: "",
              temperature: "0.2",
              fallbackChain: [],
            };
            const fallbackOptions = providers.filter(
              (provider) =>
                String(provider.id) !== draft.providerId &&
                !draft.fallbackChain.some((item) => item.providerId === String(provider.id)),
            );
            return (
              <tr key={feature.key}>
                <td>
                  <b>{feature.label_fa}</b>
                  <div className="admin-muted" dir="ltr">{feature.key}</div>
                </td>
                <td>
                  <select
                    value={draft.providerId}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [feature.key]: {
                          ...draft,
                          providerId: event.target.value,
                          fallbackChain: draft.fallbackChain.filter(
                            (item) => item.providerId !== event.target.value,
                          ),
                        },
                      }))
                    }
                  >
                    <option value="">— انتخاب کنید —</option>
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>{provider.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    dir="ltr"
                    value={draft.modelName}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [feature.key]: { ...draft, modelName: event.target.value },
                      }))
                    }
                    placeholder="gpt-4o"
                  />
                </td>
                <td>
                  <div className="admin-billing-stack">
                    {draft.fallbackChain.map((item, index) => (
                      <div key={index} className="admin-chip-row">
                        <span className="admin-muted">{index + 1}.</span>
                        <select
                          value={item.providerId}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [feature.key]: {
                                ...draft,
                                fallbackChain: draft.fallbackChain.map((entry, itemIndex) =>
                                  itemIndex === index ? { ...entry, providerId: event.target.value } : entry,
                                ),
                              },
                            }))
                          }
                        >
                          {providers
                            .filter((provider) =>
                              String(provider.id) === item.providerId ||
                              (String(provider.id) !== draft.providerId &&
                                !draft.fallbackChain.some((entry, itemIndex) =>
                                  itemIndex !== index && entry.providerId === String(provider.id),
                                )),
                            )
                            .map((provider) => (
                              <option key={provider.id} value={provider.id}>{provider.name}</option>
                            ))}
                        </select>
                        <input
                          dir="ltr"
                          value={item.modelName}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [feature.key]: {
                                ...draft,
                                fallbackChain: draft.fallbackChain.map((entry, itemIndex) =>
                                  itemIndex === index ? { ...entry, modelName: event.target.value } : entry,
                                ),
                              },
                            }))
                          }
                          placeholder={draft.modelName || "مدل جایگزین"}
                          aria-label={`مدل جایگزین ${index + 1} برای ${feature.key}`}
                        />
                        <button
                          type="button"
                          className="admin-logout-btn"
                          aria-label="حذف ارائه‌دهندهٔ جایگزین"
                          onClick={() =>
                            setDrafts((prev) => ({
                              ...prev,
                              [feature.key]: {
                                ...draft,
                                fallbackChain: draft.fallbackChain.filter((_, itemIndex) => itemIndex !== index),
                              },
                            }))
                          }
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                    {fallbackOptions.length > 0 && draft.fallbackChain.length < 8 && (
                      <button
                        type="button"
                        className="admin-theme-chip"
                        onClick={() =>
                          setDrafts((prev) => ({
                            ...prev,
                            [feature.key]: {
                              ...draft,
                              fallbackChain: [
                                ...draft.fallbackChain,
                                { providerId: String(fallbackOptions[0].id), modelName: "" },
                              ],
                            },
                          }))
                        }
                      >
                        <Plus size={14} /> افزودن جایگزین
                      </button>
                    )}
                  </div>
                </td>
                <td>
                  <input
                    dir="ltr"
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={draft.temperature}
                    onChange={(event) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [feature.key]: { ...draft, temperature: event.target.value },
                      }))
                    }
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="admin-theme-chip"
                    disabled={!draft.providerId || !draft.modelName.trim()}
                    onClick={() =>
                      void onSave(
                        feature.key,
                        Number(draft.providerId),
                        draft.modelName.trim(),
                        Number(draft.temperature) || 0.2,
                        draft.fallbackChain
                          .filter((item) => item.providerId)
                          .map((item) => ({
                            provider_id: Number(item.providerId),
                            model_name: item.modelName.trim() || null,
                          })),
                      )
                    }
                  >
                    <Save size={14} /> ذخیره
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
