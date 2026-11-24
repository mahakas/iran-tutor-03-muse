"use client";

/**
 * Admin user & role management (hotfix 2026-11-22).
 *
 * All mutations are AJAX through `apiRequest`: no page reload, the current filters,
 * search term and page stay in place (and in the URL), loading/success/error states are
 * visible, and double submits are de-duplicated by the client itself plus the
 * server-side guards. Destructive actions require an explicit confirmation dialog and a
 * fresh admin password (re-authentication), matching the backend contract.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  KeyRound,
  LoaderCircle,
  Lock,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Trash2,
  Unlock,
  UserCog,
  X,
} from "lucide-react";
import {
  ApiError,
  apiRequest,
  describeApiError,
  rememberCsrfToken,
} from "@/lib/apiClient";
import { toast } from "@/lib/toast";
import type { AcademicProfileInfo } from "@/lib/academicProfile";

const VALIDITY_LABELS: Record<string, string> = {
  active: "فعال (مستند رسمی)",
  stopped_development: "توقف توسعه",
  redesigned: "بازطراحی",
  needs_verification: "نیازمند راستی‌آزمایی",
  expired: "منقضی",
  inactive: "غیرفعال",
  unknown: "نامشخص",
};

export type AdminUserRow = {
  id: string;
  phone_number: string;
  full_name: string | null;
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
  role: string;
  is_active: boolean;
  is_deleted?: boolean;
  has_password?: boolean;
  phone_verified_at?: string | null;
  plan_code: string;
  plan_title: string;
  tokens_remaining: number;
  tokens_total: number;
  tokens_used_total: number;
  tokens_used_today: number;
  grade_level?: number | null;
  major?: string | null;
  created_at: string | null;
  last_login_at: string | null;
  days_remaining: number;
  is_expired: boolean;
};

type Pagination = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
};

type ListResponse = {
  users: AdminUserRow[];
  pagination: Pagination;
  summary: {
    total_users: number;
    active_users: number;
    deleted_users?: number;
    paid_users?: number;
    roles?: Record<string, number>;
  };
};

type SessionRow = {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string | null;
  revoked_at: string | null;
};

type AuditRow = {
  id: number;
  actor: string;
  action: string;
  target: string;
  payload: Record<string, unknown>;
  created_at: string | null;
};

type RolesResponse = {
  roles: { code: string; rank: number; assignable: boolean }[];
  actor: { role: string; rank: number; legacy: boolean };
};

const ROLE_LABELS: Record<string, string> = {
  student: "دانش‌آموز",
  guardian: "ولی",
  teacher: "معلم",
  moderator: "ناظر",
  admin: "مدیر",
  super_admin: "مدیر ارشد",
};

const STATUS_LABELS: Record<string, string> = {
  all: "همه",
  active: "فعال",
  inactive: "غیرفعال",
  deleted: "حذف‌شده",
};

const ACTION_LABELS: Record<string, string> = {
  "user.create": "ساخت کاربر",
  "user.update": "ویرایش کاربر",
  "user.role_change": "تغییر نقش",
  "user.activate": "فعال‌سازی",
  "user.deactivate": "غیرفعال‌سازی",
  "user.delete": "حذف حساب",
  "user.password_reset": "تغییر رمز",
  "user.credits": "تغییر سهمیه",
  "session.revoke": "ابطال نشست",
  "session.revoke_all": "ابطال همهٔ نشست‌ها",
};

function formatFa(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  try {
    return new Intl.NumberFormat("fa-IR").format(value);
  } catch {
    return String(value);
  }
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return "—";
  try {
    return new Intl.DateTimeFormat("fa-IR", { dateStyle: "short", timeStyle: "short" }).format(ms);
  } catch {
    return value;
  }
}

type PanelProps = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

type FilterState = { q: string; role: string; status: string; plan: string; page: number };

// Phase 06: filters used to be only *written* to the URL (replaceState) — a
// refresh restored the tab but reset every filter. They are now also *read*
// back on mount, so /admin?tab=users&q=…&status=…&page=… is a shareable,
// refresh-safe working context. The server stays authoritative over values.
function readFiltersFromUrl(): FilterState {
  try {
    const params = new URLSearchParams(window.location.search);
    const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
    return {
      q: params.get("q") ?? "",
      role: params.get("role") ?? "all",
      status: params.get("status") ?? "all",
      plan: params.get("plan") ?? "all",
      page,
    };
  } catch {
    return { q: "", role: "all", status: "all", plan: "all", page: 1 };
  }
}

export default function AdminUsersPanel({ authHeaders, onUnauthorized }: PanelProps) {
  const initialFilters = readFiltersFromUrl();
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [searchDraft, setSearchDraft] = useState(initialFilters.q);
  const [rows, setRows] = useState<AdminUserRow[]>([]);
  const [pagination, setPagination] = useState<Pagination | null>(null);
  const [summary, setSummary] = useState<ListResponse["summary"] | null>(null);
  const [roles, setRoles] = useState<RolesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<AdminUserRow | null>(null);
  const [academicProfile, setAcademicProfile] = useState<AcademicProfileInfo | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [busyAction, setBusyAction] = useState<string>("");
  const [panelTab, setPanelTab] = useState<"profile" | "security" | "credits" | "sessions" | "audit">("profile");

  // Create-user form
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState({
    phone_number: "",
    full_name: "",
    role: "student",
    password: "",
  });

  // Edit form
  const [editDraft, setEditDraft] = useState({
    first_name: "",
    last_name: "",
    phone_number: "",
    email: "",
  });
  const [creditsDraft, setCreditsDraft] = useState({ add_tokens: "", tokens_remaining: "", plan_code: "", duration_days: "" });
  const [passwordDraft, setPasswordDraft] = useState({ password: "", confirm: "" });

  // Confirmation dialog (destructive / privileged operations)
  const [confirmState, setConfirmState] = useState<{
    title: string;
    body: string;
    confirmLabel: string;
    danger?: boolean;
    reauth?: boolean;
    onConfirm: (reauthPassword: string) => Promise<void>;
  } | null>(null);
  const [reauthPassword, setReauthPassword] = useState("");
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");

  const headers = useMemo(() => authHeaders, [authHeaders]);
  const loadSeq = useRef(0);

  const handleError = useCallback(
    (cause: unknown, fallback: string) => {
      if (cause instanceof ApiError && cause.kind === "unauthorized") {
        onUnauthorized();
        return;
      }
      const message = describeApiError(cause, fallback);
      setError(message);
      toast.error(message);
    },
    [onUnauthorized]
  );

  const load = useCallback(
    async (next: FilterState = filters) => {
      const seq = ++loadSeq.current;
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({
          page: String(next.page),
          page_size: "20",
          status: next.status,
        });
        if (next.q.trim()) params.set("q", next.q.trim());
        if (next.role !== "all") params.set("role", next.role);
        if (next.plan !== "all") params.set("plan", next.plan);
        const payload = await apiRequest<ListResponse>(`/api/v1/admin/users?${params.toString()}`, {
          headers,
          dedupe: false,
        });
        if (seq !== loadSeq.current) return;
        setRows(payload.users ?? []);
        setPagination(payload.pagination ?? null);
        setSummary(payload.summary ?? null);
      } catch (cause) {
        if (seq === loadSeq.current) handleError(cause, "بارگذاری فهرست کاربران ناموفق بود.");
      } finally {
        if (seq === loadSeq.current) setLoading(false);
      }
    },
    [filters, handleError, headers]
  );

  const loadRoles = useCallback(async () => {
    try {
      const payload = await apiRequest<RolesResponse>("/api/v1/admin/users/roles", { headers });
      setRoles(payload);
    } catch {
      // Roles are a convenience; the list still renders without them.
    }
  }, [headers]);

  useEffect(() => {
    // Defer one microtask so the load is not synchronous inside the effect
    // (React 19 cascading-render rule; microtasks run before the next paint).
    void (async () => {
      await Promise.resolve();
      await loadRoles();
    })();
  }, [loadRoles]);

  useEffect(() => {
    // Defer one microtask so the load is not synchronous inside the effect
    // (React 19 cascading-render rule; microtasks run before the next paint).
    void (async () => {
      await Promise.resolve();
      await load(filters);
    })();
    // Reflect the working context in the URL so a refresh keeps tab/filters/page.
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("tab", "users");
      params.set("page", String(filters.page));
      if (filters.q.trim()) params.set("q", filters.q.trim());
      else params.delete("q");
      if (filters.role !== "all") params.set("role", filters.role);
      else params.delete("role");
      if (filters.status !== "all") params.set("status", filters.status);
      else params.delete("status");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      // history is best-effort (SSR/privacy modes)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const applyFilters = (patch: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...patch, page: patch.page ?? 1 }));
  };

  const selectUser = useCallback(
    async (row: AdminUserRow) => {
      setSelected(row);
      setPanelTab("profile");
      setEditDraft({
        first_name: row.first_name ?? "",
        last_name: row.last_name ?? "",
        phone_number: row.phone_number,
        email: row.email ?? "",
      });
      setCreditsDraft({ add_tokens: "", tokens_remaining: "", plan_code: "", duration_days: "" });
      setPasswordDraft({ password: "", confirm: "" });
      setSessions([]);
      setAudit([]);
      setSessionsLoading(true);
      try {
        const [sessionsPayload, auditPayload, detailPayload] = await Promise.all([
          apiRequest<{ sessions: SessionRow[] }>(`/api/v1/admin/users/${row.id}/sessions`, { headers }),
          apiRequest<{ entries: AuditRow[] }>(`/api/v1/admin/users/${row.id}/audit`, { headers }),
          apiRequest<{ academic_profile: AcademicProfileInfo }>(`/api/v1/admin/users/${row.id}`, { headers }),
        ]);
        setSessions(sessionsPayload.sessions ?? []);
        setAudit(auditPayload.entries ?? []);
        setAcademicProfile(detailPayload.academic_profile ?? null);
      } catch (cause) {
        handleError(cause, "بارگذاری اطلاعات این کاربر ناموفق بود.");
      } finally {
        setSessionsLoading(false);
      }
    },
    [handleError, headers]
  );

  const refreshSelected = useCallback(async () => {
    if (!selected) return;
    try {
      const payload = await apiRequest<{ user: AdminUserRow; academic_profile: AcademicProfileInfo }>(
        `/api/v1/admin/users/${selected.id}`,
        { headers }
      );
      setSelected(payload.user);
      setAcademicProfile(payload.academic_profile ?? null);
      setRows((prev) => prev.map((row) => (row.id === payload.user.id ? payload.user : row)));
    } catch {
      // keep the optimistic row; the next list refresh is authoritative
    }
  }, [headers, selected]);

  const askConfirm = (
    title: string,
    body: string,
    confirmLabel: string,
    onConfirm: (reauthPassword: string) => Promise<void>,
    options: { danger?: boolean; reauth?: boolean } = {}
  ) => {
    setConfirmError("");
    setReauthPassword("");
    setConfirmState({ title, body, confirmLabel, onConfirm, danger: options.danger, reauth: options.reauth ?? true });
  };

  async function runConfirm() {
    if (!confirmState) return;
    setConfirmBusy(true);
    setConfirmError("");
    try {
      await confirmState.onConfirm(reauthPassword);
      setConfirmState(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.kind === "unauthorized") {
        onUnauthorized();
        return;
      }
      setConfirmError(describeApiError(cause, "عملیات انجام نشد."));
    } finally {
      setConfirmBusy(false);
    }
  }

  const reauthHeaders = (password: string) => ({ ...headers, "X-Reauth-Password": password });

  // --- mutations ------------------------------------------------------------

  async function submitCreate(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const body: Record<string, unknown> = {
      phone_number: createDraft.phone_number.trim(),
      role: createDraft.role,
    };
    if (createDraft.password.trim()) body.password = createDraft.password;
    if (createDraft.full_name.trim()) body.full_name = createDraft.full_name.trim();

    const privileged = ["admin", "super_admin"].includes(createDraft.role);
    const action = async (reauth: string) => {
      setBusyAction("create");
      try {
        await apiRequest("/api/v1/admin/users", {
          method: "POST",
          body,
          headers: privileged ? reauthHeaders(reauth) : headers,
          fallbackMessage: "ساخت کاربر انجام نشد.",
        });
        toast.success("کاربر جدید ساخته شد.");
        setNotice("کاربر جدید با موفقیت ساخته شد.");
        setCreateOpen(false);
        setCreateDraft({ phone_number: "", full_name: "", role: "student", password: "" });
        await load({ ...filters, page: 1 });
      } finally {
        setBusyAction("");
      }
    };
    if (privileged) {
      askConfirm(
        "ساخت مدیر جدید",
        "ساخت حساب مدیر نیازمند تأیید هویت است. رمز عبور مدیرِ فعلی خود را وارد کنید.",
        "ساخت مدیر",
        action,
        { reauth: true }
      );
      return;
    }
    try {
      await action("");
    } catch (cause) {
      handleError(cause, "ساخت کاربر انجام نشد.");
    }
  }

  async function submitProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusyAction("profile");
    setError("");
    try {
      // Academic placement is student-owned: the admin PATCH no longer sends
      // grade_level/major — those fields were removed by owner decision.
      const body: Record<string, unknown> = {
        first_name: editDraft.first_name.trim(),
        last_name: editDraft.last_name.trim(),
        email: editDraft.email.trim(),
        phone_number: editDraft.phone_number.trim(),
      };
      const payload = await apiRequest<{ user: AdminUserRow; phone_changed: boolean }>(
        `/api/v1/admin/users/${selected.id}`,
        { method: "PATCH", body, headers, fallbackMessage: "ویرایش کاربر انجام نشد." }
      );
      setSelected(payload.user);
      setRows((prev) => prev.map((row) => (row.id === payload.user.id ? payload.user : row)));
      setNotice(
        payload.phone_changed
          ? "اطلاعات کاربر ذخیره شد. شمارهٔ جدید باید توسط کاربر تأیید شود."
          : "اطلاعات کاربر ذخیره شد."
      );
      toast.success("تغییرات ذخیره شد.");
    } catch (cause) {
      handleError(cause, "ویرایش کاربر انجام نشد.");
    } finally {
      setBusyAction("");
    }
  }

  function changeRole(newRole: string) {
    if (!selected) return;
    askConfirm(
      "تغییر نقش کاربر",
      `نقش کاربر از «${ROLE_LABELS[selected.role] ?? selected.role}» به «${ROLE_LABELS[newRole] ?? newRole}» تغییر می‌کند. همهٔ نشست‌های فعال کاربر باطل می‌شوند.`,
      "اعمال نقش جدید",
      async (reauth) => {
        setBusyAction("role");
        try {
          const payload = await apiRequest<{ user: AdminUserRow }>(`/api/v1/admin/users/${selected.id}/role`, {
            method: "PUT",
            body: { role: newRole },
            headers: reauthHeaders(reauth),
            fallbackMessage: "تغییر نقش انجام نشد.",
          });
          setSelected(payload.user);
          setRows((prev) => prev.map((row) => (row.id === payload.user.id ? payload.user : row)));
          setAudit((prev) => prev);
          setNotice("نقش کاربر تغییر کرد و نشست‌های او باطل شد.");
        } finally {
          setBusyAction("");
        }
      }
    );
  }

  function toggleActivation() {
    if (!selected) return;
    const nextActive = !selected.is_active;
    askConfirm(
      nextActive ? "فعال‌سازی حساب" : "غیرفعال‌سازی حساب",
      nextActive
        ? "حساب کاربر دوباره فعال می‌شود و می‌تواند وارد شود."
        : "حساب کاربر غیرفعال می‌شود و همهٔ نشست‌های فعال او باطل می‌شوند. کاربر تا فعال‌سازی مجدد نمی‌تواند وارد شود.",
      nextActive ? "فعال کن" : "غیرفعال کن",
      async () => {
        setBusyAction("activation");
        try {
          const payload = await apiRequest<{ user: AdminUserRow; sessions_revoked: number }>(
            `/api/v1/admin/users/${selected.id}/activation`,
            {
              method: "PUT",
              body: { is_active: nextActive },
              headers,
              fallbackMessage: "تغییر وضعیت انجام نشد.",
            }
          );
          setSelected(payload.user);
          setRows((prev) => prev.map((row) => (row.id === payload.user.id ? payload.user : row)));
          setNotice(
            nextActive
              ? "حساب فعال شد."
              : `حساب غیرفعال شد و ${formatFa(payload.sessions_revoked)} نشست باطل شد.`
          );
        } finally {
          setBusyAction("");
        }
      },
      { danger: !nextActive, reauth: false }
    );
  }

  function deleteAccount() {
    if (!selected) return;
    askConfirm(
      "حذف حساب کاربر",
      "حساب کاربر حذف (نرم) می‌شود: ورود او مسدود، رمز عبورش پاک و همهٔ نشست‌هایش باطل می‌شود. سابقهٔ پرداخت و مصرف برای حسابرسی حفظ می‌شود.",
      "حذف حساب",
      async (reauth) => {
        setBusyAction("delete");
        try {
          const payload = await apiRequest<{ mode: string; revoked_sessions: number }>(
            `/api/v1/admin/users/${selected.id}`,
            {
              method: "DELETE",
              headers: reauthHeaders(reauth),
              fallbackMessage: "حذف کاربر انجام نشد.",
            }
          );
          toast.success(payload.mode === "soft" ? "حساب حذف (غیرفعال) شد." : "حساب حذف شد.");
          setSelected(null);
          setAcademicProfile(null);
          await load(filters);
        } finally {
          setBusyAction("");
        }
      },
      { danger: true, reauth: true }
    );
  }

  function submitPassword(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    if (passwordDraft.password !== passwordDraft.confirm) {
      setError("رمز عبور و تکرار آن یکسان نیست.");
      return;
    }
    askConfirm(
      "تعیین رمز عبور جدید",
      "با این کار رمز قبلی کاربر بی‌اعتبار و همهٔ نشست‌های او باطل می‌شود. رمز جدید را به‌صورت امن به کاربر اطلاع دهید.",
      "ذخیرهٔ رمز",
      async (reauth) => {
        setBusyAction("password");
        try {
          const payload = await apiRequest<{ user: AdminUserRow; sessions_revoked: number }>(
            `/api/v1/admin/users/${selected.id}/password`,
            {
              method: "POST",
              body: { new_password: passwordDraft.password, require_change_on_next_login: true },
              headers: reauthHeaders(reauth),
              fallbackMessage: "تغییر رمز انجام نشد.",
            }
          );
          setSelected(payload.user);
          setPasswordDraft({ password: "", confirm: "" });
          setNotice(`رمز عبور تغییر کرد و ${formatFa(payload.sessions_revoked)} نشست باطل شد.`);
        } finally {
          setBusyAction("");
        }
      }
    );
  }

  async function submitCredits(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusyAction("credits");
    setError("");
    try {
      const body: Record<string, unknown> = {};
      if (creditsDraft.plan_code) body.plan_code = creditsDraft.plan_code;
      if (creditsDraft.add_tokens.trim()) body.add_tokens = Number(creditsDraft.add_tokens);
      if (creditsDraft.tokens_remaining.trim()) body.tokens_remaining = Number(creditsDraft.tokens_remaining);
      if (creditsDraft.duration_days.trim()) body.duration_days = Number(creditsDraft.duration_days);
      if (Object.keys(body).length === 0) {
        setError("حداقل یکی از مقادیر سهمیه یا توکن را وارد کنید.");
        return;
      }
      const payload = await apiRequest<{ user: AdminUserRow }>(`/api/v1/admin/users/${selected.id}/credits`, {
        method: "PUT",
        body,
        headers,
        fallbackMessage: "تغییر سهمیه انجام نشد.",
      });
      setSelected(payload.user);
      setRows((prev) => prev.map((row) => (row.id === payload.user.id ? payload.user : row)));
      setCreditsDraft({ add_tokens: "", tokens_remaining: "", plan_code: "", duration_days: "" });
      setNotice("سهمیه و اعتبار کاربر به‌روزرسانی شد.");
      toast.success("سهمیه ذخیره شد.");
    } catch (cause) {
      handleError(cause, "تغییر سهمیه انجام نشد.");
    } finally {
      setBusyAction("");
    }
  }

  async function revokeSession(sessionId: string) {
    if (!selected) return;
    setBusyAction(`session:${sessionId}`);
    try {
      await apiRequest(`/api/v1/admin/users/${selected.id}/sessions/${sessionId}`, {
        method: "DELETE",
        headers,
        fallbackMessage: "ابطال نشست انجام نشد.",
      });
      setSessions((prev) =>
        prev.map((row) =>
          row.id === sessionId ? { ...row, is_active: false, revoked_at: new Date().toISOString() } : row
        )
      );
      toast.success("نشست باطل شد.");
    } catch (cause) {
      handleError(cause, "ابطال نشست انجام نشد.");
    } finally {
      setBusyAction("");
    }
  }

  async function revokeAllSessions() {
    if (!selected) return;
    setBusyAction("sessions:all");
    try {
      const payload = await apiRequest<{ revoked_count: number }>(
        `/api/v1/admin/users/${selected.id}/sessions/revoke-all`,
        { method: "POST", headers, fallbackMessage: "ابطال نشست‌ها انجام نشد." }
      );
      setSessions((prev) => prev.map((row) => ({ ...row, is_active: false })));
      setNotice(`${formatFa(payload.revoked_count)} نشست باطل شد.`);
      toast.success("همهٔ نشست‌ها باطل شد.");
    } catch (cause) {
      handleError(cause, "ابطال نشست‌ها انجام نشد.");
    } finally {
      setBusyAction("");
    }
  }

  const availableRoles = roles?.roles ?? [
    { code: "student", rank: 10, assignable: true },
    { code: "teacher", rank: 30, assignable: true },
    { code: "moderator", rank: 40, assignable: true },
    { code: "admin", rank: 50, assignable: true },
    { code: "super_admin", rank: 60, assignable: true },
  ];

  return (
    <div className="admin-users-panel">
      <div className="admin-kpi-grid">
        <div className="admin-kpi-card">
          <span>کل کاربران</span>
          <b>{formatFa(summary?.total_users ?? 0)}</b>
        </div>
        <div className="admin-kpi-card">
          <span>کاربران فعال</span>
          <b>{formatFa(summary?.active_users ?? 0)}</b>
        </div>
        <div className="admin-kpi-card">
          <span>حذف‌شده‌ها</span>
          <b>{formatFa(summary?.deleted_users ?? 0)}</b>
        </div>
        <div className="admin-kpi-card">
          <span>مدیران</span>
          <b>{formatFa((summary?.roles?.admin ?? 0) + (summary?.roles?.super_admin ?? 0))}</b>
        </div>
      </div>

      <section className="admin-card">
        <div className="users-toolbar">
          <form
            className="users-search"
            onSubmit={(event) => {
              event.preventDefault();
              applyFilters({ q: searchDraft });
            }}
          >
            <Search size={15} />
            <input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="جستجو با شماره موبایل یا نام..."
              aria-label="جستجوی کاربران"
            />
          </form>
          <select
            aria-label="نقش"
            value={filters.role}
            onChange={(event) => applyFilters({ role: event.target.value })}
          >
            <option value="all">همهٔ نقش‌ها</option>
            {Object.entries(ROLE_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label="وضعیت"
            value={filters.status}
            onChange={(event) => applyFilters({ status: event.target.value })}
          >
            {Object.entries(STATUS_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label="پلن"
            value={filters.plan}
            onChange={(event) => applyFilters({ plan: event.target.value })}
          >
            <option value="all">همهٔ پلن‌ها</option>
            <option value="trial">هدیه ثبت‌نام</option>
            <option value="normal">اقتصادی</option>
            <option value="pro">حرفه‌ای</option>
            <option value="vip">هوشمندانه</option>
          </select>
          <button type="button" className="outline-button" onClick={() => void load(filters)} disabled={loading}>
            <RefreshCw size={14} className={loading ? "spin" : ""} /> بروزرسانی
          </button>
          <button type="button" className="primary-button" onClick={() => setCreateOpen((prev) => !prev)}>
            <Plus size={15} /> کاربر جدید
          </button>
        </div>

        {notice && (
          <div className="success-note admin-banner" role="status">
            <CheckCircle2 size={15} />
            {notice}
            <button type="button" className="icon-button" aria-label="بستن پیام" onClick={() => setNotice("")}>
              <X size={14} />
            </button>
          </div>
        )}
        {error && (
          <div className="inline-error admin-banner" role="alert">
            {error}
          </div>
        )}

        {createOpen && (
          <form className="admin-create-user" onSubmit={submitCreate}>
            <h3>
              <UserCog size={16} /> ساخت حساب کاربری جدید
            </h3>
            <div className="admin-create-grid">
              <label className="form-field">
                <span>شماره موبایل</span>
                <input
                  dir="ltr"
                  value={createDraft.phone_number}
                  onChange={(event) => setCreateDraft((prev) => ({ ...prev, phone_number: event.target.value }))}
                  placeholder="09123456789"
                  required
                />
              </label>
              <label className="form-field">
                <span>نام نمایشی</span>
                <input
                  value={createDraft.full_name}
                  onChange={(event) => setCreateDraft((prev) => ({ ...prev, full_name: event.target.value }))}
                  placeholder="مثلاً مریم محمدی"
                />
              </label>
              <label className="form-field">
                <span>نقش</span>
                <select
                  value={createDraft.role}
                  onChange={(event) => setCreateDraft((prev) => ({ ...prev, role: event.target.value }))}
                >
                  {availableRoles
                    .filter((role) => role.assignable)
                    .map((role) => (
                      <option key={role.code} value={role.code}>
                        {ROLE_LABELS[role.code] ?? role.code}
                      </option>
                    ))}
                </select>
              </label>
              <label className="form-field">
                <span>رمز عبور اولیه (اختیاری)</span>
                <input
                  type="password"
                  dir="ltr"
                  value={createDraft.password}
                  onChange={(event) => setCreateDraft((prev) => ({ ...prev, password: event.target.value }))}
                  placeholder="حداقل ۸ کاراکتر"
                  autoComplete="new-password"
                />
              </label>
            </div>
            <div className="admin-inline-actions">
              <button type="submit" className="primary-button" disabled={busyAction === "create"}>
                {busyAction === "create" ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                ساخت کاربر
              </button>
              <button type="button" className="outline-button" onClick={() => setCreateOpen(false)}>
                انصراف
              </button>
            </div>
          </form>
        )}

        {loading ? (
          <div className="review-loading">
            <LoaderCircle className="spin" size={18} />
            <span>در حال دریافت کاربران...</span>
          </div>
        ) : rows.length === 0 ? (
          <div className="review-empty">کاربری با این فیلترها پیدا نشد.</div>
        ) : (
          <div className="admin-users-table-wrap">
            <table className="admin-users-table">
              <thead>
                <tr>
                  <th>موبایل / نام</th>
                  <th>نقش</th>
                  <th>پلن</th>
                  <th>توکن باقی‌مانده</th>
                  <th>وضعیت</th>
                  <th>آخرین ورود</th>
                  <th>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className={selected?.id === row.id ? "selected" : ""}>
                    <td>
                      <b dir="ltr">{row.phone_number}</b>
                      <small>{row.full_name || "بدون نام"}</small>
                    </td>
                    <td>
                      <span className={`badge-pill ${row.role.includes("admin") ? "done" : ""}`}>
                        {ROLE_LABELS[row.role] ?? row.role}
                      </span>
                    </td>
                    <td>{row.plan_title}</td>
                    <td>
                      {formatFa(row.tokens_remaining)} / {formatFa(row.tokens_total)}
                    </td>
                    <td>
                      {row.is_deleted ? (
                        <span className="badge-pill failed">حذف‌شده</span>
                      ) : row.is_active ? (
                        "فعال"
                      ) : (
                        <span className="badge-pill failed">غیرفعال</span>
                      )}
                    </td>
                    <td>{formatWhen(row.last_login_at)}</td>
                    <td>
                      <div className="user-row-actions">
                        <button type="button" className="outline-button" onClick={() => void selectUser(row)}>
                          <UserCog size={14} /> مدیریت
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {pagination && pagination.total_pages > 1 && (
          <div className="admin-pagination">
            <button
              type="button"
              className="outline-button"
              disabled={!pagination.has_prev || loading}
              onClick={() => applyFilters({ page: pagination.page - 1 })}
            >
              <ChevronRight size={14} /> قبلی
            </button>
            <span>
              صفحهٔ {formatFa(pagination.page)} از {formatFa(pagination.total_pages)} — {formatFa(pagination.total)} کاربر
            </span>
            <button
              type="button"
              className="outline-button"
              disabled={!pagination.has_next || loading}
              onClick={() => applyFilters({ page: pagination.page + 1 })}
            >
              بعدی <ChevronLeft size={14} />
            </button>
          </div>
        )}
      </section>

      {selected && (
        <section className="admin-card admin-user-detail">
          <div className="card-heading">
            <div>
              <h2>
                پروندهٔ کاربر <span dir="ltr">{selected.phone_number}</span>
                {selected.full_name ? ` — ${selected.full_name}` : ""}
              </h2>
              <p>
                نقش: {ROLE_LABELS[selected.role] ?? selected.role} · وضعیت:{" "}
                {selected.is_deleted ? "حذف‌شده" : selected.is_active ? "فعال" : "غیرفعال"} · رمز عبور:{" "}
                {selected.has_password ? "تعیین‌شده" : "تعیین‌نشده"}
              </p>
            </div>
            <div className="report-head-actions">
              <button type="button" className="outline-button" onClick={() => void refreshSelected()}>
                <RefreshCw size={14} /> بروزرسانی
              </button>
              <button type="button" className="icon-button" aria-label="بستن پرونده" onClick={() => setSelected(null)}>
                <X size={18} />
              </button>
            </div>
          </div>

          <div className="admin-user-actions">
            <select
              aria-label="تغییر نقش"
              value={selected.role}
              onChange={(event) => {
                if (event.target.value !== selected.role) changeRole(event.target.value);
              }}
              disabled={busyAction === "role"}
            >
              {availableRoles.map((role) => (
                <option key={role.code} value={role.code}>
                  {ROLE_LABELS[role.code] ?? role.code}
                </option>
              ))}
            </select>
            <button type="button" className="outline-button" onClick={toggleActivation} disabled={busyAction === "activation"}>
              {selected.is_active ? <Lock size={14} /> : <Unlock size={14} />}
              {selected.is_active ? "غیرفعال‌سازی" : "فعال‌سازی"}
            </button>
            <button type="button" className="outline-button danger" onClick={deleteAccount} disabled={busyAction === "delete"}>
              <Trash2 size={14} /> حذف حساب
            </button>
          </div>

          <div className="admin-user-tabs" role="tablist">
            {(
              [
                ["profile", "اطلاعات و امنیت"],
                ["credits", "سهمیه و اعتبار"],
                ["sessions", "نشست‌ها"],
                ["audit", "تاریخچهٔ مدیریت"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={panelTab === key}
                className={`admin-user-tab ${panelTab === key ? "active" : ""}`}
                onClick={() => setPanelTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {panelTab === "profile" && (
            <div className="admin-user-pane">
                          <div className="account-card" style={{ marginTop: 12 }}>
              <h3 style={{ marginTop: 0, fontSize: 14 }}>پروفایل تحصیلی (فقط مشاهده)</h3>
              {academicProfile?.exists ? (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                    gap: 8,
                    fontSize: 12,
                  }}
                >
                  <div><b>پایه:</b> {academicProfile.grade_title ?? "—"}</div>
                  <div><b>دوره:</b> {academicProfile.cycle_title ?? "—"}</div>
                  <div><b>شاخه:</b> {academicProfile.branch_title ?? "—"}</div>
                  <div><b>زمینه:</b> {academicProfile.ground_title ?? "—"}</div>
                  <div><b>رشته:</b> {academicProfile.field_title ?? "—"}</div>
                  <div><b>سال تحصیلی:</b> {academicProfile.academic_year_code ?? "—"}</div>
                  <div>
                    <b>اعتبار رشته:</b>{" "}
                    {academicProfile.field_validity_status
                      ? VALIDITY_LABELS[academicProfile.field_validity_status] ??
                        academicProfile.field_validity_status
                      : "—"}
                  </div>
                  <div>
                    <b>آخرین تغییر:</b>{" "}
                    {academicProfile.updated_at
                      ? new Date(academicProfile.updated_at).toLocaleString("fa-IR")
                      : "—"}
                  </div>
                </div>
              ) : (
                <p className="admin-muted" style={{ fontSize: 12 }}>
                  دانش‌آموز هنوز پایه و رشتهٔ تحصیلی خود را انتخاب نکرده است. انتخاب و تغییر پایه فقط با خودِ
                  دانش‌آموز است و هیچ مرحلهٔ تأییدی در این پنل وجود ندارد.
                </p>
              )}
            </div>
            <form className="admin-user-form" onSubmit={submitProfile}>
                <div className="admin-create-grid">
                  <label className="form-field">
                    <span>نام</span>
                    <input
                      value={editDraft.first_name}
                      onChange={(event) => setEditDraft((prev) => ({ ...prev, first_name: event.target.value }))}
                    />
                  </label>
                  <label className="form-field">
                    <span>نام خانوادگی</span>
                    <input
                      value={editDraft.last_name}
                      onChange={(event) => setEditDraft((prev) => ({ ...prev, last_name: event.target.value }))}
                    />
                  </label>
                  <label className="form-field">
                    <span>شماره موبایل</span>
                    <input
                      dir="ltr"
                      value={editDraft.phone_number}
                      onChange={(event) => setEditDraft((prev) => ({ ...prev, phone_number: event.target.value }))}
                    />
                  </label>
                  <label className="form-field">
                    <span>ایمیل</span>
                    <input
                      dir="ltr"
                      type="email"
                      value={editDraft.email}
                      onChange={(event) => setEditDraft((prev) => ({ ...prev, email: event.target.value }))}
                    />
                  </label>
                  <p className="academic-picker-note" style={{ gridColumn: "1 / -1" }}>
                    پایه و رشتهٔ تحصیلی توسط خود دانش‌آموز انتخاب و تغییر می‌کند و از این فرم قابل ویرایش نیست —
                    وضعیت فعلی در بخش «پروفایل تحصیلی» همین پرونده نمایش داده می‌شود.
                  </p>
                </div>
                <div className="admin-inline-actions">
                  <button type="submit" className="primary-button" disabled={busyAction === "profile"}>
                    {busyAction === "profile" ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                    ذخیرهٔ اطلاعات
                  </button>
                </div>
              </form>

              <form className="admin-user-form admin-password-reset" onSubmit={submitPassword}>
                <h3>
                  <KeyRound size={15} /> تعیین رمز عبور جدید
                </h3>
                <p className="admin-muted">
                  اقدام حساس: نیازمند تأیید هویت مدیر است و همهٔ نشست‌های کاربر را باطل می‌کند.
                </p>
                <div className="admin-create-grid">
                  <label className="form-field">
                    <span>رمز جدید</span>
                    <input
                      type="password"
                      dir="ltr"
                      autoComplete="new-password"
                      value={passwordDraft.password}
                      onChange={(event) => setPasswordDraft((prev) => ({ ...prev, password: event.target.value }))}
                    />
                  </label>
                  <label className="form-field">
                    <span>تکرار رمز جدید</span>
                    <input
                      type="password"
                      dir="ltr"
                      autoComplete="new-password"
                      value={passwordDraft.confirm}
                      onChange={(event) => setPasswordDraft((prev) => ({ ...prev, confirm: event.target.value }))}
                    />
                  </label>
                </div>
                <div className="admin-inline-actions">
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={busyAction === "password" || !passwordDraft.password}
                  >
                    {busyAction === "password" ? <LoaderCircle className="spin" size={15} /> : <ShieldCheck size={15} />}
                    ذخیرهٔ رمز عبور
                  </button>
                </div>
              </form>
            </div>
          )}

          {panelTab === "credits" && (
            <div className="admin-user-pane">
              <div className="admin-kpi-grid">
                <div className="admin-kpi-card">
                  <span>توکن باقی‌مانده</span>
                  <b>{formatFa(selected.tokens_remaining)}</b>
                </div>
                <div className="admin-kpi-card">
                  <span>کل توکن</span>
                  <b>{formatFa(selected.tokens_total)}</b>
                </div>
                <div className="admin-kpi-card">
                  <span>مصرف امروز</span>
                  <b>{formatFa(selected.tokens_used_today)}</b>
                </div>
                <div className="admin-kpi-card">
                  <span>اعتبار پلن</span>
                  <b>{selected.is_expired ? "منقضی" : `${formatFa(selected.days_remaining)} روز`}</b>
                </div>
              </div>
              <form className="admin-user-form" onSubmit={submitCredits}>
                <div className="admin-create-grid">
                  <label className="form-field">
                    <span>تغییر پلن</span>
                    <select
                      value={creditsDraft.plan_code}
                      onChange={(event) => setCreditsDraft((prev) => ({ ...prev, plan_code: event.target.value }))}
                    >
                      <option value="">بدون تغییر</option>
                      <option value="trial">هدیه ثبت‌نام</option>
                      <option value="normal">اقتصادی</option>
                      <option value="pro">حرفه‌ای</option>
                      <option value="vip">هوشمندانه</option>
                    </select>
                  </label>
                  <label className="form-field">
                    <span>افزودن / کسر توکن</span>
                    <input
                      type="number"
                      value={creditsDraft.add_tokens}
                      onChange={(event) => setCreditsDraft((prev) => ({ ...prev, add_tokens: event.target.value }))}
                      placeholder="مثلاً 50000 یا -1000"
                    />
                  </label>
                  <label className="form-field">
                    <span>تعیین مستقیم توکن باقی‌مانده</span>
                    <input
                      type="number"
                      min={0}
                      value={creditsDraft.tokens_remaining}
                      onChange={(event) =>
                        setCreditsDraft((prev) => ({ ...prev, tokens_remaining: event.target.value }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>تمدید اعتبار (روز)</span>
                    <input
                      type="number"
                      min={1}
                      value={creditsDraft.duration_days}
                      onChange={(event) => setCreditsDraft((prev) => ({ ...prev, duration_days: event.target.value }))}
                    />
                  </label>
                </div>
                <div className="admin-inline-actions">
                  <button type="submit" className="primary-button" disabled={busyAction === "credits"}>
                    {busyAction === "credits" ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
                    ذخیرهٔ سهمیه و اعتبار
                  </button>
                </div>
              </form>
            </div>
          )}

          {panelTab === "sessions" && (
            <div className="admin-user-pane">
              <div className="admin-inline-actions">
                <button
                  type="button"
                  className="outline-button danger"
                  onClick={() => void revokeAllSessions()}
                  disabled={busyAction === "sessions:all"}
                >
                  {busyAction === "sessions:all" ? (
                    <LoaderCircle className="spin" size={14} />
                  ) : (
                    <Lock size={14} />
                  )}
                  ابطال همهٔ نشست‌ها
                </button>
              </div>
              {sessionsLoading ? (
                <div className="review-loading">
                  <LoaderCircle className="spin" size={16} />
                  <span>در حال دریافت نشست‌ها...</span>
                </div>
              ) : sessions.length === 0 ? (
                <div className="review-empty">نشست فعالی برای این کاربر ثبت نشده است.</div>
              ) : (
                <div className="admin-users-table-wrap">
                  <table className="admin-users-table compact">
                    <thead>
                      <tr>
                        <th>دستگاه</th>
                        <th>IP</th>
                        <th>آخرین فعالیت</th>
                        <th>وضعیت</th>
                        <th>عملیات</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sessions.map((row) => (
                        <tr key={row.id}>
                          <td title={row.user_agent ?? ""}>{row.user_agent ? row.user_agent.slice(0, 42) : "نامشخص"}</td>
                          <td dir="ltr">{row.ip_address ?? "—"}</td>
                          <td>{formatWhen(row.last_seen_at)}</td>
                          <td>{row.is_active ? "فعال" : "باطل"}</td>
                          <td>
                            <button
                              type="button"
                              className="outline-button"
                              disabled={!row.is_active || busyAction === `session:${row.id}`}
                              onClick={() => void revokeSession(row.id)}
                            >
                              ابطال
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {panelTab === "audit" && (
            <div className="admin-user-pane">
              {audit.length === 0 ? (
                <div className="review-empty">تا کنون اقدام مدیریتی برای این کاربر ثبت نشده است.</div>
              ) : (
                <ul className="admin-audit-list">
                  {audit.map((entry) => (
                    <li key={entry.id}>
                      <div>
                        <b>{ACTION_LABELS[entry.action] ?? entry.action}</b>
                        <span className="admin-muted"> — {entry.actor}</span>
                      </div>
                      <div className="admin-audit-meta">
                        {formatWhen(entry.created_at)}
                        {entry.payload && Object.keys(entry.payload).length > 0 && (
                          <details>
                            <summary>جزئیات</summary>
                            <pre className="admin-code">{JSON.stringify(entry.payload, null, 2)}</pre>
                          </details>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      {confirmState && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (!confirmBusy && event.target === event.currentTarget) setConfirmState(null);
          }}
        >
          <section className="exam-setup-modal confirm-modal" role="dialog" aria-modal="true" dir="rtl">
            <div className={`modal-icon ${confirmState.danger ? "danger-icon" : ""}`}>
              {confirmState.danger ? <AlertTriangle size={22} /> : <ShieldCheck size={22} />}
            </div>
            <h2>{confirmState.title}</h2>
            <p>{confirmState.body}</p>
            {confirmState.reauth && (
              <label className="form-field">
                <span>رمز عبور مدیر (تأیید هویت)</span>
                <input
                  type="password"
                  dir="ltr"
                  autoComplete="current-password"
                  value={reauthPassword}
                  onChange={(event) => setReauthPassword(event.target.value)}
                  autoFocus
                />
              </label>
            )}
            {confirmError && <div className="inline-error" role="alert">{confirmError}</div>}
            <div className="dialog-actions-row">
              <button
                type="button"
                className="outline-button"
                onClick={() => setConfirmState(null)}
                disabled={confirmBusy}
                autoFocus={!confirmState.reauth}
              >
                انصراف
              </button>
              <button
                type="button"
                className={confirmState.danger ? "danger-button" : "primary-button"}
                onClick={() => void runConfirm()}
                disabled={confirmBusy || (confirmState.reauth && !reauthPassword)}
              >
                {confirmBusy ? <LoaderCircle className="spin" size={15} /> : null}
                {confirmState.confirmLabel}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
