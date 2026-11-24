"use client";

import AdminSideNav, { parseAdminTabParam, type AdminNavKey } from "@/components/AdminSideNav";
import AdminUsersPanel from "@/components/AdminUsersPanel";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  Coins,
  Cpu,
  Crown,
  Database,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  FileUp,
  GitCompareArrows,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Monitor,
  Moon,
  Palette,
  Pencil,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  ShieldOff,
  Sparkles,
  Sun,
  Trash2,
  Users,
  XCircle,
  Zap,
  ToggleRight,
  Layers,
} from "lucide-react";
import AdminAppearancePanel, { type AdminPreferencesPatch } from "@/components/AdminAppearancePanel";
import AdminIntegrationsPanel, { type AdminSystemSettingsPayload } from "@/components/AdminIntegrationsPanel";
import AdminObservabilityPanel from "@/components/AdminObservabilityPanel";
import AdminOverviewPanel, { type AdminOverviewData } from "@/components/AdminOverviewPanel";
import AdminProvidersPanel from "@/components/AdminProvidersPanel";
import AdminRolesQuotasPanel from "@/components/AdminRolesQuotasPanel";
import AdminKbPanel from "@/components/AdminKbPanel";
import AdminFlashcardsPanel from "@/components/AdminFlashcardsPanel";
import AdminPhase5Panel from "@/components/AdminPhase5Panel";
import AdminPhase6Panel from "@/components/AdminPhase6Panel";
import AdminPodcastsPanel from "@/components/AdminPodcastsPanel";
import AdminSkillsPanel from "@/components/AdminSkillsPanel";
import AdminCapabilitiesPanel from "@/components/AdminCapabilitiesPanel";
import DiffViewer from "@/components/DiffViewer";
import GlobalSearch, { type SearchItem } from "@/components/GlobalSearch";
import { computeLineDiff } from "@/lib/diff";
import {
  applyPreferencesToDocument,
  DEFAULT_PREFERENCES,
  normalizePreferencesClient,
  readCachedAdminPreferences,
  resolveEffectiveColorMode,
  writeCachedAdminPreferences,
} from "@/lib/preferences";
import type {
  PaymentTransactionItem,
  PlanItem,
  StudentUser,
  TokenUsageLogItem,
  UserPreferences,
} from "@/lib/types";

type BookStatus = {
  id: number;
  title: string;
  grade_number?: number;
  major_code?: string | null;
  branch_code?: string | null;
  academic_year_id?: number | null;
  edition_label?: string | null;
  print_year?: number | null;
  publisher?: string | null;
  source_checksum?: string | null;
  total_pdf_pages: number;
  status: string;
  pages: Record<string, number>;
};

type CurriculumBranchOption = {
  code: string;
  title: string;
  min_grade: number;
  max_grade: number;
};
type CurriculumFieldOption = {
  code: string;
  title: string;
  branch_code: string;
  branch_title: string;
};
type CurriculumSubjectOption = { code: string; title: string; description?: string | null };

type VisualElement = {
  label?: string;
  type?: string;
  scientific_description?: string;
};

type AdminPageItem = {
  pdf_page_index: number;
  printed_page_number: number | null;
  chapter_number: number | null;
  chapter_title: string | null;
  status: string;
  warnings: string[];
  markdown_content: string;
  original_markdown_content?: string | null;
  visual_elements: VisualElement[];
  extraction_model: string | null;
  edited_by_human: boolean;
  error_message: string | null;
  image_url: string | null;
};

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const ADMIN_TOKEN_KEY = "iran_tutor_admin_token";

function detectClientFileFormat(file: File | null): "pdf" | "markdown" | "json" | "html" | "unknown" {
  if (!file) return "pdf";
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "markdown";
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".html") || name.endsWith(".htm")) return "html";
  const mime = (file.type || "").toLowerCase();
  if (mime.includes("pdf")) return "pdf";
  if (mime.includes("markdown")) return "markdown";
  if (mime.includes("json")) return "json";
  if (mime.includes("html")) return "html";
  return "unknown";
}

function readStoredAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeAdminToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    }
  } catch {
    // ignore storage restriction
  }
}

function buildAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-Admin-Token": token,
  };
}

const statusLabel: Record<string, string> = {
  done: "تأییدشده",
  needs_review: "نیازمند بازبینی",
  failed: "خطا",
  pending: "در انتظار",
};

type BillingSettingsData = {
  token_price_per_1k_toman: number;
  starter_tokens: number;
  starter_duration_days: number;
  starter_storage_bytes?: number;
};

type AdminUserSessionRow = {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  is_active: boolean;
  last_seen_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
};

type AdminUsersSummary = {
  total_users: number;
  active_users: number;
  paid_users: number;
  total_tokens_used: number;
  total_used_value_toman: number;
  total_revenue_toman: number;
};

type AdminUsageActionSummary = {
  action: string;
  count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_toman: number;
};

type AdminUsageDailyItem = {
  date: string;
  requests: number;
  total_tokens: number;
  cost_toman: number;
};

type AdminUsageLogRow = TokenUsageLogItem & {
  book_title?: string | null;
};

type AdminUserUsageReport = {
  user: StudentUser;
  token_price_per_1k_toman: number;
  by_action: AdminUsageActionSummary[];
  daily: AdminUsageDailyItem[];
  logs: AdminUsageLogRow[];
  transactions: PaymentTransactionItem[];
};

const actionLabels: Record<string, string> = {
  tutor_ask: "پرسش متنی از معلم",
  tutor_image: "آپلود و تحلیل تصویر",
  tutor_audio: "آپلود/ضبط صدا",
  exam_create: "ساخت آزمون زمان‌دار",
};

const providerLabels: Record<string, string> = {
  demo: "درگاه آزمایشی",
  zarinpal: "زرین‌پال",
  admin_grant: "تخصیص مدیر",
};

function formatFaNumber(value: number) {
  try {
    return new Intl.NumberFormat("fa-IR").format(value);
  } catch {
    return String(value);
  }
}

function formatFaDateTime(iso?: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fa-IR", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function formatFaDate(isoDate: string) {
  try {
    return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("fa-IR", {
      dateStyle: "medium",
    });
  } catch {
    return isoDate;
  }
}

// The tab lives in the `?tab=` query parameter so every admin section is a stable,
// deep-linkable URL: refresh, back/forward and new-tab all land on the same section.
// Programmatic jumps (quick actions, search, post-login defaults) go through
// `setAdminTab`, which pushes the URL instead of only flipping local state — the
// client component is not remounted by a search-param change, so auth and loaded
// data survive navigation.
function AdminPageBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const adminTab: AdminNavKey = parseAdminTabParam(searchParams.get("tab"));
  const setAdminTab = useCallback(
    (key: AdminNavKey) => {
      router.push(`/admin?tab=${key}`, { scroll: false });
    },
    [router]
  );
  const [authState, setAuthState] = useState<"checking" | "locked" | "authenticated">("checking");
  const tokenRef = useRef<string | null>(null);
  const [activeTokenState, setActiveTokenState] = useState<string | null>(null);
  const pendingJumpPageRef = useRef<{ bookId: number; pageIndex: number } | null>(null);
  const [systemMode, setSystemMode] = useState<"demo" | "production">("demo");
  const [overviewData, setOverviewData] = useState<AdminOverviewData | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState("");
  const [adminPreferences, setAdminPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [systemIsDark, setSystemIsDark] = useState(false);
  const [appearanceSaving, setAppearanceSaving] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [pageImageSrc, setPageImageSrc] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState<string>("");

  // Phase 6: Plans, token pricing & user management state
  const [billingSettings, setBillingSettings] = useState<BillingSettingsData>({
    token_price_per_1k_toman: 1000,
    starter_tokens: 15000,
    starter_duration_days: 7,
    starter_storage_bytes: 25 * 1024 * 1024,
  });
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [billingLoading, setBillingLoading] = useState(false);
  const [billingSaving, setBillingSaving] = useState(false);
  const [savingPlanCode, setSavingPlanCode] = useState<string | null>(null);
  const [billingMessage, setBillingMessage] = useState("");
  const [billingError, setBillingError] = useState("");

  const [users, setUsers] = useState<StudentUser[]>([]);
  const [usersSummary, setUsersSummary] = useState<AdminUsersSummary | null>(null);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [userPlanFilter, setUserPlanFilter] = useState("all");
  const [editingUser, setEditingUser] = useState<StudentUser | null>(null);
  const [editUserPlan, setEditUserPlan] = useState("trial");
  const [editUserApplyPlanDefaults, setEditUserApplyPlanDefaults] = useState(true);
  const [editUserAddTokens, setEditUserAddTokens] = useState("");
  const [editUserDurationDays, setEditUserDurationDays] = useState("");
  const [editUserActive, setEditUserActive] = useState(true);
  const [userSaving, setUserSaving] = useState(false);
  const [userMessage, setUserMessage] = useState("");
  const [userError, setUserError] = useState("");
  const [userSessions, setUserSessions] = useState<AdminUserSessionRow[]>([]);
  const [userSessionsLoading, setUserSessionsLoading] = useState(false);
  const [revokingSessions, setRevokingSessions] = useState(false);
  const [usageReportUserId, setUsageReportUserId] = useState<string | null>(null);
  const [usageReport, setUsageReport] = useState<AdminUserUsageReport | null>(null);
  const [usageReportLoading, setUsageReportLoading] = useState(false);
  const [usageReportError, setUsageReportError] = useState("");

  // Book lifecycle actions state (edit metadata, reindex vectors, reprocess PDF, delete)
  const [editingBookMeta, setEditingBookMeta] = useState(false);
  const [editBookTitle, setEditBookTitle] = useState("");
  const [editBookGrade, setEditBookGrade] = useState(12);
  const [editBookMajor, setEditBookMajor] = useState("math_physics");
  const [bookActionBusy, setBookActionBusy] = useState<string | null>(null);
  const [bookActionMessage, setBookActionMessage] = useState("");
  const [bookActionError, setBookActionError] = useState("");
  const [deleteBookConfirm, setDeleteBookConfirm] = useState<"none" | "confirm" | "force">("none");
  const [deleteConflictDetail, setDeleteConflictDetail] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("فیزیک ۳");
  const [grade, setGrade] = useState(12);
  const [branchCode, setBranchCode] = useState("theoretical");
  const [branchOptions, setBranchOptions] = useState<CurriculumBranchOption[]>([]);
  const [fieldOptions, setFieldOptions] = useState<CurriculumFieldOption[]>([]);
  const [subjectOptions, setSubjectOptions] = useState<CurriculumSubjectOption[]>([]);
  const [subjectCode, setSubjectCode] = useState("");
  const [selectedFieldCodes, setSelectedFieldCodes] = useState<string[]>(["math_physics"]);
  const [academicYearCode, setAcademicYearCode] = useState("");
  const [editionLabel, setEditionLabel] = useState("");
  const [printYear, setPrintYear] = useState("");
  const [publisher, setPublisher] = useState("");
  const [isGeneralBook, setIsGeneralBook] = useState(false);
  const [catalogJson, setCatalogJson] = useState('{"academic_years":[],"fields":[],"subjects":[],"units":[]}');
  const [catalogSubmitting, setCatalogSubmitting] = useState(false);
  const [startPage, setStartPage] = useState(12);
  const [endPage, setEndPage] = useState(16);
  const [books, setBooks] = useState<BookStatus[]>([]);
  const [book, setBook] = useState<BookStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewStatus, setPreviewStatus] = useState<"all" | "needs_review" | "done" | "failed">("all");
  const [previewVersion, setPreviewVersion] = useState(1);
  const [uploadMessage, setUploadMessage] = useState("");

  const [pages, setPages] = useState<AdminPageItem[]>([]);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [editPrintedPage, setEditPrintedPage] = useState("");
  const [editChapterNumber, setEditChapterNumber] = useState("");
  const [editChapterTitle, setEditChapterTitle] = useState("");
  const [editMarkdown, setEditMarkdown] = useState("");
  const [savingPage, setSavingPage] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");
  const [imageError, setImageError] = useState(false);
  const [showReviewDiff, setShowReviewDiff] = useState(true);
  const [diffBaseline, setDiffBaseline] = useState<"saved" | "original">("saved");

  const selectPageForEdit = useCallback((page: AdminPageItem | null) => {
    if (!page) {
      setSelectedIdx(null);
      setEditPrintedPage("");
      setEditChapterNumber("");
      setEditChapterTitle("");
      setEditMarkdown("");
      setSaveError("");
      setImageError(false);
      return;
    }
    setSelectedIdx(page.pdf_page_index);
    setEditPrintedPage(page.printed_page_number !== null ? String(page.printed_page_number) : "");
    setEditChapterNumber(page.chapter_number !== null ? String(page.chapter_number) : "");
    setEditChapterTitle(page.chapter_title ?? "");
    setEditMarkdown(page.markdown_content ?? "");
    setSaveError("");
    setImageError(false);
  }, []);

  const getActiveToken = useCallback((): string | null => {
    return tokenRef.current ?? readStoredAdminToken();
  }, []);

  const setActiveToken = useCallback((token: string | null) => {
    tokenRef.current = token;
    setActiveTokenState(token);
    storeAdminToken(token);
  }, []);

  const lockAdminPanel = useCallback(() => {
    setActiveToken(null);
    setAuthState("locked");
    setBooks([]);
    setBook(null);
    setPages([]);
    setPageImageSrc(null);
    setPreviewHtml("");
    setPreviewOpen(false);
    selectPageForEdit(null);
    writeCachedAdminPreferences(null);
    setAdminPreferences(DEFAULT_PREFERENCES);
  }, [selectPageForEdit, setActiveToken]);

  const fetchAdminPreferences = useCallback(
    async (tokenOverride?: string | null): Promise<UserPreferences | null> => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      try {
        const res = await fetch("/api/v1/admin/preferences", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (!res.ok) return null;
        const payload = (await res.json()) as { preferences?: UserPreferences };
        if (!payload.preferences) return null;
        const normalized = normalizePreferencesClient(payload.preferences);
        setAdminPreferences(normalized);
        writeCachedAdminPreferences(normalized);
        return normalized;
      } catch {
        return null;
      }
    },
    [getActiveToken]
  );

  const patchAdminPreferences = useCallback(
    async (patch: AdminPreferencesPatch) => {
      const optimistic = normalizePreferencesClient({
        general: { ...adminPreferences.general, ...(patch.general ?? {}) },
        appearance: {
          ...adminPreferences.appearance,
          ...(patch.appearance ?? {}),
          light: { ...adminPreferences.appearance.light, ...(patch.appearance?.light ?? {}) },
          dark: { ...adminPreferences.appearance.dark, ...(patch.appearance?.dark ?? {}) },
        },
        notifications: adminPreferences.notifications,
        privacy: adminPreferences.privacy,
      });
      setAdminPreferences(optimistic);
      writeCachedAdminPreferences(optimistic);

      const token = getActiveToken();
      if (!token && authState !== "authenticated") return;
      setAppearanceSaving(true);
      try {
        const res = await fetch("/api/v1/admin/preferences", {
          method: "PUT",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
          body: JSON.stringify(patch),
        });
        if (res.status === 401) {
          lockAdminPanel();
          throw new Error("نشست مدیریت منقضی شده است؛ لطفاً دوباره وارد شوید.");
        }
        const payload = (await res.json().catch(() => ({}))) as {
          preferences?: UserPreferences;
          detail?: string;
        };
        if (!res.ok || !payload.preferences) {
          throw new Error(payload.detail ?? "ذخیره تنظیمات ظاهری انجام نشد.");
        }
        const normalized = normalizePreferencesClient(payload.preferences);
        setAdminPreferences(normalized);
        writeCachedAdminPreferences(normalized);
      } finally {
        setAppearanceSaving(false);
      }
    },
    [adminPreferences, authState, getActiveToken, lockAdminPanel]
  );

  const resetAdminPreferences = useCallback(async () => {
    const token = getActiveToken();
    setAppearanceSaving(true);
    try {
      const res = await fetch("/api/v1/admin/preferences/reset", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify({ section: "appearance" }),
      });
      if (res.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است.");
      }
      const payload = (await res.json().catch(() => ({}))) as {
        preferences?: UserPreferences;
        detail?: string;
      };
      if (!res.ok || !payload.preferences) {
        throw new Error(payload.detail ?? "بازنشانی تنظیمات انجام نشد.");
      }
      const normalized = normalizePreferencesClient(payload.preferences);
      setAdminPreferences(normalized);
      writeCachedAdminPreferences(normalized);
    } finally {
      setAppearanceSaving(false);
    }
  }, [getActiveToken, lockAdminPanel]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event: MediaQueryListEvent) => setSystemIsDark(event.matches);
    const timer = window.setTimeout(() => {
      setSystemIsDark(mq.matches);
      const cached = readCachedAdminPreferences();
      if (cached) setAdminPreferences(cached);
    }, 0);
    mq.addEventListener?.("change", handler);
    return () => {
      window.clearTimeout(timer);
      mq.removeEventListener?.("change", handler);
    };
  }, []);

  useEffect(() => {
    applyPreferencesToDocument(adminPreferences, systemIsDark);
  }, [adminPreferences, systemIsDark]);

  const fetchBooks = useCallback(
    async (tokenOverride?: string | null): Promise<{ items: BookStatus[]; unauthorized: boolean }> => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      try {
        const response = await fetch("/api/v1/admin/books", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) return { items: [], unauthorized: true };
        if (!response.ok) return { items: [], unauthorized: false };
        return { items: (await response.json()) as BookStatus[], unauthorized: false };
      } catch {
        return { items: [], unauthorized: false };
      }
    },
    [getActiveToken]
  );

  const fetchBookPages = useCallback(
    async (bookId: number, tokenOverride?: string | null): Promise<{ items: AdminPageItem[]; unauthorized: boolean }> => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      try {
        const response = await fetch(`/api/v1/admin/books/${bookId}/pages`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) return { items: [], unauthorized: true };
        if (!response.ok) return { items: [], unauthorized: false };
        return { items: (await response.json()) as AdminPageItem[], unauthorized: false };
      } catch {
        return { items: [], unauthorized: false };
      }
    },
    [getActiveToken]
  );

  const fetchBillingData = useCallback(
    async (tokenOverride?: string | null) => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      setBillingLoading(true);
      setBillingError("");
      try {
        const response = await fetch("/api/v1/admin/billing", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await response.json()) as {
          settings?: BillingSettingsData;
          plans?: PlanItem[];
          detail?: string;
        };
        if (!response.ok) throw new Error(payload.detail ?? "خطا در دریافت تنظیمات پلن‌ها");
        if (payload.settings) setBillingSettings(payload.settings);
        if (payload.plans) setPlans(payload.plans);
      } catch (cause) {
        setBillingError(cause instanceof Error ? cause.message : "خطا در دریافت تنظیمات");
      } finally {
        setBillingLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel]
  );

  const fetchUsersData = useCallback(
    async (searchTerm?: string, planFilter?: string) => {
      const token = getActiveToken();
      setUsersLoading(true);
      setUserError("");
      try {
        const params = new URLSearchParams();
        const qVal = searchTerm !== undefined ? searchTerm : userSearch;
        const pVal = planFilter !== undefined ? planFilter : userPlanFilter;
        if (qVal.trim()) params.set("q", qVal.trim());
        if (pVal && pVal !== "all") params.set("plan", pVal);
        const response = await fetch(`/api/v1/admin/users?${params.toString()}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await response.json()) as {
          summary?: AdminUsersSummary;
          users?: StudentUser[];
          detail?: string;
        };
        if (!response.ok) throw new Error(payload.detail ?? "خطا در دریافت لیست کاربران");
        if (payload.summary) setUsersSummary(payload.summary);
        if (payload.users) setUsers(payload.users);
      } catch (cause) {
        setUserError(cause instanceof Error ? cause.message : "خطا در دریافت کاربران");
      } finally {
        setUsersLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel, userPlanFilter, userSearch]
  );

  const fetchUserUsageReport = useCallback(
    async (userId: string) => {
      const token = getActiveToken();
      setUsageReportUserId(userId);
      setUsageReportLoading(true);
      setUsageReportError("");
      try {
        const response = await fetch(`/api/v1/admin/users/${userId}/usage?limit=100`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (response.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await response.json()) as AdminUserUsageReport & { detail?: string };
        if (!response.ok) throw new Error(payload.detail ?? "خطا در دریافت گزارش مصرف کاربر");
        setUsageReport(payload);
      } catch (cause) {
        setUsageReportError(cause instanceof Error ? cause.message : "خطا در دریافت گزارش مصرف");
      } finally {
        setUsageReportLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel]
  );

  const downloadUserUsageCsv = useCallback(() => {
    if (!usageReport) return;
    const rows = [
      ["id", "created_at", "action", "book_title", "prompt_tokens", "completion_tokens", "total_tokens", "cost_toman"],
      ...usageReport.logs.map((log) => [
        String(log.id),
        log.created_at ?? "",
        actionLabels[log.action] ?? log.action,
        (log.book_title ?? "").replace(/"/g, '""'),
        String(log.prompt_tokens),
        String(log.completion_tokens),
        String(log.total_tokens),
        String(log.cost_toman),
      ]),
    ];
    const csv = "\uFEFF" + rows.map((r) => r.map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `token-usage-${usageReport.user.phone_number}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [usageReport]);

  const refreshBooksAndSelect = useCallback(
    async (preferredBookId?: number, tokenOverride?: string | null) => {
      const { items, unauthorized } = await fetchBooks(tokenOverride);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setBooks(items);
      if (preferredBookId !== undefined) {
        const match = items.find((item) => item.id === preferredBookId);
        if (match) setBook(match);
      } else if (items.length > 0) {
        setBook((current) => (current ? items.find((item) => item.id === current.id) ?? items[0] : items[0]));
      }
    },
    [fetchBooks, lockAdminPanel]
  );

  const refreshBookPages = useCallback(
    async (bookId: number, keepPageIdx?: number | null) => {
      setPagesLoading(true);
      const { items, unauthorized } = await fetchBookPages(bookId);
      setPagesLoading(false);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setPages(items);
      if (items.length === 0) {
        selectPageForEdit(null);
        return;
      }
      const kept =
        keepPageIdx !== undefined && keepPageIdx !== null
          ? items.find((item) => item.pdf_page_index === keepPageIdx)
          : undefined;
      const firstNeedsReview = items.find((item) => item.status === "needs_review" || item.status === "failed");
      selectPageForEdit(kept ?? firstNeedsReview ?? items[0]);
    },
    [fetchBookPages, lockAdminPanel, selectPageForEdit]
  );

  const fetchOverviewData = useCallback(
    async (tokenOverride?: string | null) => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      setOverviewLoading(true);
      setOverviewError("");
      try {
        const res = await fetch("/api/v1/admin/overview", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (res.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await res.json()) as AdminOverviewData & { detail?: string };
        if (!res.ok) throw new Error(payload.detail ?? "خطا در دریافت نمای کلی سیستم");
        setOverviewData(payload);
        if (payload.system?.mode) {
          setSystemMode(payload.system.mode);
        }
      } catch (cause) {
        setOverviewError(cause instanceof Error ? cause.message : "خطا در دریافت نمای کلی");
      } finally {
        setOverviewLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel]
  );

  const fetchUserSessions = useCallback(
    async (userId: string) => {
      const token = getActiveToken();
      setUserSessionsLoading(true);
      try {
        const res = await fetch(`/api/v1/admin/users/${userId}/sessions`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildAuthHeaders(token),
        });
        if (res.status === 401) {
          lockAdminPanel();
          return;
        }
        const payload = (await res.json()) as { sessions?: AdminUserSessionRow[] };
        if (res.ok && payload.sessions) setUserSessions(payload.sessions);
      } catch {
        setUserSessions([]);
      } finally {
        setUserSessionsLoading(false);
      }
    },
    [getActiveToken, lockAdminPanel]
  );

  const handleRevokeUserSessions = async (userId: string) => {
    const token = getActiveToken();
    setRevokingSessions(true);
    setUserMessage("");
    setUserError("");
    try {
      const res = await fetch(`/api/v1/admin/users/${userId}/revoke-sessions`, {
        method: "POST",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
      });
      if (res.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await res.json()) as { revoked_count?: number; detail?: string };
      if (!res.ok) throw new Error(payload.detail ?? "بستن نشست‌های کاربر انجام نشد");
      setUserMessage(`${formatFaNumber(payload.revoked_count ?? 0)} نشست فعال کاربر با موفقیت لغو شد.`);
      await fetchUserSessions(userId);
    } catch (cause) {
      setUserError(cause instanceof Error ? cause.message : "خطا در بستن نشست‌ها");
    } finally {
      setRevokingSessions(false);
    }
  };

  const openBookMetaEditor = (target: BookStatus) => {
    setEditBookTitle(target.title);
    setEditBookGrade(target.grade_number ?? 12);
    setEditBookMajor(target.major_code ?? "math_physics");
    setEditingBookMeta((prev) => !prev);
    setBookActionError("");
    setBookActionMessage("");
  };

  const handleSaveBookMeta = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!book) return;
    const token = getActiveToken();
    setBookActionBusy("meta");
    setBookActionError("");
    setBookActionMessage("");
    try {
      const res = await fetch(`/api/v1/admin/books/${book.id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify({
          title: editBookTitle.trim(),
          grade_number: editBookGrade,
          major_code: editBookGrade >= 10 ? editBookMajor : null,
        }),
      });
      if (res.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await res.json()) as { book?: BookStatus; detail?: string };
      if (!res.ok || !payload.book) throw new Error(payload.detail ?? "ویرایش اطلاعات کتاب انجام نشد");
      setBook(payload.book);
      setEditingBookMeta(false);
      setBookActionMessage("اطلاعات کتاب با موفقیت به‌روزرسانی شد.");
      await refreshBooksAndSelect(payload.book.id);
    } catch (cause) {
      setBookActionError(cause instanceof Error ? cause.message : "خطا در ویرایش کتاب");
    } finally {
      setBookActionBusy(null);
    }
  };

  const handleReindexBook = async (targetBookId: number) => {
    const token = getActiveToken();
    setBookActionBusy("reindex");
    setBookActionError("");
    setBookActionMessage("");
    try {
      const res = await fetch(`/api/v1/admin/books/${targetBookId}/reindex`, {
        method: "POST",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
      });
      if (res.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await res.json()) as {
        indexed_pages?: number;
        vector_backend?: string;
        detail?: string;
      };
      if (!res.ok) throw new Error(payload.detail ?? "ایندکس مجدد کتاب ناموفق بود");
      setBookActionMessage(
        `${formatFaNumber(payload.indexed_pages ?? 0)} صفحه در موتور برداری (${payload.vector_backend ?? "vector"}) ایندکس شد.`
      );
    } catch (cause) {
      setBookActionError(cause instanceof Error ? cause.message : "خطا در ایندکس مجدد برداری");
    } finally {
      setBookActionBusy(null);
    }
  };

  const handleReprocessBook = async (targetBookId: number) => {
    const token = getActiveToken();
    setBookActionBusy("reprocess");
    setBookActionError("");
    setBookActionMessage("");
    try {
      const res = await fetch(`/api/v1/admin/books/${targetBookId}/reprocess`, {
        method: "POST",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
      });
      if (res.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await res.json()) as { detail?: string; start_page?: number; end_page?: number };
      if (!res.ok) throw new Error(payload.detail ?? "شروع پردازش مجدد ناموفق بود");
      setBook((prev) => (prev && prev.id === targetBookId ? { ...prev, status: "ingesting" } : prev));
      setBookActionMessage(
        `پردازش مجدد صفحه‌های ${payload.start_page ?? 1} تا ${payload.end_page ?? 1} آغاز شد.`
      );
    } catch (cause) {
      setBookActionError(cause instanceof Error ? cause.message : "خطا در پردازش مجدد کتاب");
    } finally {
      setBookActionBusy(null);
    }
  };

  const handleDeleteBook = async (targetBookId: number, forceDelete: boolean) => {
    const token = getActiveToken();
    setBookActionBusy("delete");
    setBookActionError("");
    setBookActionMessage("");
    try {
      const res = await fetch(`/api/v1/admin/books/${targetBookId}?force=${forceDelete ? "true" : "false"}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
      });
      if (res.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await res.json()) as { detail?: string };
      if (res.status === 409) {
        setDeleteBookConfirm("force");
        setDeleteConflictDetail(payload.detail ?? "این کتاب دارای سوابق گفت‌وگو یا آزمون است.");
        return;
      }
      if (!res.ok) throw new Error(payload.detail ?? "حذف کتاب ناموفق بود");
      setDeleteBookConfirm("none");
      setDeleteConflictDetail("");
      setEditingBookMeta(false);
      setPreviewOpen(false);
      setPages([]);
      selectPageForEdit(null);
      setBook(null);
      setBookActionMessage("کتاب و صفحه‌های مربوطه با موفقیت حذف شدند.");
      const { items } = await fetchBooks();
      setBooks(items);
      if (items.length > 0) setBook(items[0]);
    } catch (cause) {
      setBookActionError(cause instanceof Error ? cause.message : "خطا در حذف کتاب");
    } finally {
      setBookActionBusy(null);
    }
  };

  useEffect(() => {
    let active = true;
    const storedToken = getActiveToken();
    fetch("/api/v1/admin/auth/session", {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(storedToken),
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = (await response.json()) as { authenticated?: boolean };
        return Boolean(data.authenticated);
      })
      .catch(() => false)
      .then(async (authenticated) => {
        if (!active) return;
        if (!authenticated) {
          setActiveToken(null);
          setAuthState("locked");
          return;
        }
        setActiveToken(storedToken);
        const [{ items, unauthorized }] = await Promise.all([
          fetchBooks(storedToken),
          fetchAdminPreferences(storedToken),
          fetchOverviewData(storedToken),
        ]);
        if (!active) return;
        if (unauthorized) {
          lockAdminPanel();
          return;
        }
        setAuthState("authenticated");
        if (items.length > 0) {
          setBooks(items);
          setBook((current) => current ?? items[0]);
        }
      });
    return () => {
      active = false;
    };
  }, [fetchAdminPreferences, fetchBooks, fetchOverviewData, getActiveToken, lockAdminPanel, setActiveToken]);

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setAuthError("لطفاً نام کاربری و رمز عبور مدیر را وارد کنید.");
      return;
    }
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch("/api/v1/admin/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        detail?: string;
        authenticated?: boolean;
        token?: string;
      };
      if (!response.ok || !payload.authenticated || !payload.token) {
        throw new Error(payload.detail ?? "نام کاربری یا رمز عبور مدیر نادرست است.");
      }
      setActiveToken(payload.token);
      const [{ items, unauthorized }] = await Promise.all([
        fetchBooks(payload.token),
        fetchAdminPreferences(payload.token),
        fetchOverviewData(payload.token),
      ]);
      if (unauthorized) {
        setActiveToken(null);
        throw new Error("نشست احراز هویت در مرورگر حفظ نشد؛ لطفاً صفحه را رفرش یا در تب جدید باز کنید.");
      }
      setPassword("");
      setBooks(items);
      setBook(items[0] ?? null);
      setAuthState("authenticated");
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "خطا در ورود به پنل مدیریت");
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogout = async () => {
    const token = getActiveToken();
    await fetch("/api/v1/admin/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    }).catch(() => undefined);
    lockAdminPanel();
  };

  const activeBookId = authState === "authenticated" ? book?.id ?? null : null;
  const activeBookStatus = authState === "authenticated" ? book?.status ?? null : null;

  useEffect(() => {
    if (!activeBookId || !activeBookStatus) return;
    let active = true;

    if (activeBookStatus === "ingesting") {
      const timer = window.setInterval(async () => {
        const token = getActiveToken();
        try {
          const response = await fetch(`/api/v1/admin/books/${activeBookId}/status`, {
            cache: "no-store",
            credentials: "same-origin",
            headers: buildAuthHeaders(token),
          });
          if (!active) return;
          if (response.status === 401) {
            lockAdminPanel();
            return;
          }
          const payload = (await response.json()) as BookStatus;
          if (!response.ok) return;
          setBook(payload);
          if (payload.status !== "ingesting") {
            const { items, unauthorized } = await fetchBooks();
            if (!active) return;
            if (unauthorized) {
              lockAdminPanel();
              return;
            }
            if (items.length > 0) setBooks(items);
          }
        } catch {
          if (active) setError("وضعیت پردازش دریافت نشد؛ ارتباط بک‌اند را بررسی کن.");
        }
      }, 2000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }

    fetchBookPages(activeBookId).then(({ items, unauthorized }) => {
      if (!active) return;
      setPagesLoading(false);
      if (unauthorized) {
        lockAdminPanel();
        return;
      }
      setPages(items);
      if (items.length === 0) {
        selectPageForEdit(null);
        return;
      }
      const pending = pendingJumpPageRef.current;
      const jumped =
        pending && pending.bookId === activeBookId
          ? items.find((item) => item.pdf_page_index === pending.pageIndex)
          : undefined;
      if (pending && pending.bookId === activeBookId) {
        pendingJumpPageRef.current = null;
      }
      const firstNeedsReview = items.find((item) => item.status === "needs_review" || item.status === "failed");
      selectPageForEdit(jumped ?? firstNeedsReview ?? items[0]);
    });

    return () => {
      active = false;
    };
  }, [activeBookId, activeBookStatus, fetchBookPages, fetchBooks, getActiveToken, lockAdminPanel, selectPageForEdit]);

  const selectedPage = useMemo(
    () => pages.find((item) => item.pdf_page_index === selectedIdx) ?? null,
    [pages, selectedIdx]
  );

  const effectiveAdminColorMode = resolveEffectiveColorMode(adminPreferences, systemIsDark);
  const diffMarkersEnabled = adminPreferences.appearance.diff_markers !== false;
  const hasOriginalSnapshot = Boolean(
    selectedPage &&
      selectedPage.original_markdown_content !== null &&
      selectedPage.original_markdown_content !== undefined
  );
  const effectiveDiffBaseline =
    diffBaseline === "original" && hasOriginalSnapshot ? "original" : "saved";
  const diffBeforeMarkdown = useMemo(() => {
    if (!selectedPage) return "";
    if (effectiveDiffBaseline === "original") {
      return selectedPage.original_markdown_content ?? selectedPage.markdown_content ?? "";
    }
    return selectedPage.markdown_content ?? "";
  }, [effectiveDiffBaseline, selectedPage]);
  const liveMarkdownDiff = useMemo(
    () => computeLineDiff(diffBeforeMarkdown, editMarkdown),
    [diffBeforeMarkdown, editMarkdown]
  );

  const authHeadersMemo = useMemo(() => buildAuthHeaders(activeTokenState), [activeTokenState]);

  const cycleQuickColorMode = () => {
    const current = adminPreferences.appearance.color_mode;
    const next = current === "light" ? "dark" : current === "dark" ? "system" : "light";
    void patchAdminPreferences({ appearance: { color_mode: next } }).catch(() => undefined);
  };

  const handleAdminJumpBook = useCallback(
    (targetBookId: number, pageIndex?: number) => {
      setAdminTab("books");
      const targetBook = books.find((b) => b.id === targetBookId);
      if (book?.id === targetBookId) {
        if (pageIndex !== undefined) {
          const targetPage = pages.find((p) => p.pdf_page_index === pageIndex);
          if (targetPage) selectPageForEdit(targetPage);
        }
        return;
      }
      if (pageIndex !== undefined) {
        pendingJumpPageRef.current = { bookId: targetBookId, pageIndex };
      }
      if (targetBook) {
        setBook(targetBook);
        setPages([]);
        setPagesLoading(targetBook.status !== "ingesting");
      } else {
        void fetchBooks().then(({ items }) => {
          setBooks(items);
          const match = items.find((b) => b.id === targetBookId) ?? null;
          if (match) {
            setBook(match);
            setPages([]);
            setPagesLoading(match.status !== "ingesting");
          }
        });
      }
    },
    [book?.id, books, fetchBooks, pages, selectPageForEdit, setAdminTab]
  );

  const handleAdminJumpUser = useCallback(
    (userId: string) => {
      setAdminTab("users");
      void fetchUsersData();
      void fetchBillingData();
      void fetchUserUsageReport(userId);
    },
    [fetchBillingData, fetchUserUsageReport, fetchUsersData, setAdminTab]
  );

  const adminQuickCommands = useMemo<SearchItem[]>(
    () => [
      {
        id: "cmd-overview",
        category: "commands",
        title: "نمای کلی سیستم، آمار زنده و تراکنش‌ها",
        subtitle: "وضعیت سرویس‌ها، صفحه‌های نیازمند بازبینی، تراکنش‌ها و لاگ مصرف",
        badge: "تب",
        icon: "nav",
        onSelect: () => {
          setAdminTab("overview");
          void fetchOverviewData();
        },
      },
      {
        id: "cmd-integrations",
        category: "commands",
        title: "API هوش مصنوعی، مدل‌ها، پیامک و درگاه پرداخت",
        subtitle: "تنظیم کلید API، تست مدل‌ها، pgvector/Qdrant، کاوه‌نگار و زرین‌پال",
        badge: "سیستم",
        icon: "nav",
        onSelect: () => setAdminTab("integrations"),
      },
      {
        id: "cmd-books",
        category: "commands",
        title: "کتاب‌ها و پردازش PDF / Markdown",
        subtitle: "آپلود کتاب جدید، بررسی وضعیت، ایندکس برداری و بازبینی صفحه‌ها",
        badge: "تب",
        icon: "book",
        onSelect: () => setAdminTab("books"),
      },
      {
        id: "cmd-plans",
        category: "commands",
        title: "مدیریت پلن‌ها، فضای ذخیره و قیمت توکن",
        subtitle: "ویرایش تعرفه پلن‌ها، حجم مجاز و هدیه ثبت‌نام",
        badge: "تب",
        icon: "plan",
        onSelect: () => {
          setAdminTab("plans");
          void fetchBillingData();
        },
      },
      {
        id: "cmd-users",
        category: "commands",
        title: "مدیریت کاربران، نشست‌ها و سهمیه‌ها",
        subtitle: "لیست کاربران، گزارش مصرف، شارژ دستی و لغو نشست‌ها",
        badge: "تب",
        icon: "user",
        onSelect: () => {
          setAdminTab("users");
          void fetchUsersData();
          void fetchBillingData();
        },
      },
      {
        id: "cmd-appearance",
        category: "commands",
        title: "تنظیمات ظاهر، تم، فونت و Diff Markers",
        subtitle: "حالت روشن/تاریک/سیستم، رنگ‌بندی، کنتراست و دسترس‌پذیری",
        badge: "ظاهر",
        icon: "appearance",
        onSelect: () => setAdminTab("appearance"),
      },
    ],
    [fetchBillingData, fetchOverviewData, fetchUsersData, setAdminTab]
  );

  const selectedImageUrl = selectedPage?.image_url ?? null;

  useEffect(() => {
    if (authState !== "authenticated" || !selectedImageUrl) return;
    let active = true;
    let objectUrl: string | null = null;
    const token = getActiveToken();
    fetch(`${selectedImageUrl}?v=${previewVersion}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    })
      .then(async (response) => {
        if (response.status === 401) {
          if (active) lockAdminPanel();
          return null;
        }
        if (!response.ok) return null;
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        if (!blob) {
          setImageError(true);
          setPageImageSrc(null);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setImageError(false);
        setPageImageSrc(objectUrl);
      })
      .catch(() => {
        if (active) {
          setImageError(true);
          setPageImageSrc(null);
        }
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [authState, getActiveToken, lockAdminPanel, previewVersion, selectedImageUrl]);

  useEffect(() => {
    if (authState !== "authenticated" || !previewOpen || !activeBookId) return;
    let active = true;
    const token = getActiveToken();
    fetch(`/api/v1/admin/books/${activeBookId}/preview?status=${previewStatus}&v=${previewVersion}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: buildAuthHeaders(token),
    })
      .then(async (response) => {
        if (response.status === 401) {
          if (active) lockAdminPanel();
          return "";
        }
        if (!response.ok) return "";
        return response.text();
      })
      .then((htmlText) => {
        if (active && htmlText) setPreviewHtml(htmlText);
      })
      .catch(() => undefined);

    return () => {
      active = false;
    };
  }, [activeBookId, authState, getActiveToken, lockAdminPanel, previewOpen, previewStatus, previewVersion]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    Promise.all([
      fetch(`/api/v1/curriculum/branches?grade_number=${grade}`, {
        cache: "no-store",
        signal: controller.signal,
      }),
      fetch("/api/v1/curriculum/fields", {
        cache: "no-store",
        signal: controller.signal,
      }),
    ])
      .then(async ([branchResponse, fieldResponse]) => {
        if (!branchResponse.ok || !fieldResponse.ok) throw new Error("curriculum catalogue unavailable");
        const branchData = (await branchResponse.json()) as CurriculumBranchOption[];
        const fieldData = (await fieldResponse.json()) as CurriculumFieldOption[];
        const subjectFetch = await fetch("/api/v1/curriculum/subjects", {
          cache: "no-store",
          signal: controller.signal,
        });
        const subjectData = subjectFetch.ok
          ? ((await subjectFetch.json()) as CurriculumSubjectOption[])
          : [];
        if (!active) return;
        setBranchOptions(branchData);
        setFieldOptions(fieldData);
        setSubjectOptions(subjectData);
        setBranchCode((current) =>
          branchData.some((item) => item.code === current)
            ? current
            : branchData.find((item) => item.code === "theoretical")?.code ?? branchData[0]?.code ?? ""
        );
        setSelectedFieldCodes((current) => current.filter((code) => fieldData.some((item) => item.code === code)));
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (active) {
          setBranchOptions([]);
          setFieldOptions([]);
          setSubjectOptions([]);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [grade]);

  const selectedFileFormat = useMemo(() => detectClientFileFormat(file), [file]);
  const isPdfUpload = selectedFileFormat === "pdf";

  const processedPages = useMemo(
    () => (book ? Object.values(book.pages).reduce((total, count) => total + count, 0) : 0),
    [book]
  );
  const progress = book?.total_pdf_pages ? Math.min(100, (processedPages / book.total_pdf_pages) * 100) : 0;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("ابتدا فایل کتاب را انتخاب کن.");
      return;
    }
    if (selectedFileFormat === "unknown") {
      setError("فرمت فایل پشتیبانی نمی‌شود. فقط PDF، Markdown (.md)، JSON (.json) و HTML (.html) مجاز هستند.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError("حجم فایل نباید بیشتر از ۱۰۰ مگابایت باشد.");
      return;
    }
    if (isPdfUpload && (startPage < 1 || endPage < startPage)) {
      setError("بازهٔ صفحه‌ها معتبر نیست.");
      return;
    }
    setSubmitting(true);
    setError("");
    setPreviewOpen(false);
    setPreviewStatus("all");
    setUploadMessage("");
    setSaveMessage("");
    setPages([]);
    selectPageForEdit(null);
    const form = new FormData();
    form.set("file", file);
    form.set("grade_number", String(grade));
    form.set("book_title", title);
    if (isPdfUpload) {
      form.set("start_page", String(startPage));
      form.set("end_page", String(endPage));
    }
    if (subjectCode) form.set("subject_code", subjectCode);
    if (grade >= 10) {
      if (selectedFieldCodes.length > 0) {
        for (const code of selectedFieldCodes) form.append("applicable_field_codes", code);
        if (selectedFieldCodes.length === 1) form.set("major_code", selectedFieldCodes[0]);
      } else if (branchCode && (branchCode !== "theoretical" || !isGeneralBook)) {
        form.set("branch_code", branchCode);
      }
      if (isGeneralBook) form.set("is_general_book", "true");
    }
    if (academicYearCode.trim()) form.set("academic_year_code", academicYearCode.trim());
    if (editionLabel.trim()) form.set("edition_label", editionLabel.trim());
    if (printYear.trim()) form.set("print_year", printYear.trim());
    if (publisher.trim()) form.set("publisher", publisher.trim());
    try {
      const token = getActiveToken();
      const response = await fetch("/api/v1/admin/books/upload-and-ingest", {
        method: "POST",
        credentials: "same-origin",
        headers: buildAuthHeaders(token),
        body: form,
      });
      if (response.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است؛ لطفاً دوباره وارد شوید.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "آپلود و پردازش شروع نشد.");
      const nextStatus = typeof payload.status === "string" ? payload.status : "ingesting";
      const totalPages = typeof payload.total_pages === "number" ? payload.total_pages : endPage - startPage + 1;
      setUploadMessage(
        nextStatus === "ready"
          ? `کتاب با شناسهٔ ${payload.book_id} در ${formatFaNumber(totalPages)} بخش/صفحه ثبت و برای دانش‌آموزان منتشر شد.`
          : `پردازش کتاب با شناسهٔ ${payload.book_id} شروع شد.`
      );
      if (nextStatus !== "ingesting") {
        setPagesLoading(true);
      }
      setBook({
        id: payload.book_id,
        title,
        grade_number: grade,
        major_code: grade >= 10 && selectedFieldCodes.length === 1 ? selectedFieldCodes[0] : null,
        branch_code: grade >= 10 && selectedFieldCodes.length === 0 ? branchCode : null,
        edition_label: editionLabel.trim() || null,
        print_year: printYear.trim() ? Number(printYear) : null,
        publisher: publisher.trim() || null,
        total_pdf_pages: totalPages,
        status: nextStatus,
        pages: payload.pages ?? {},
      });
      const { items } = await fetchBooks();
      if (items.length > 0) setBooks(items);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "خطا در ارتباط با سرور");
    } finally {
      setSubmitting(false);
    }
  };

  const handleImportCurriculumCatalog = async () => {
    let body: unknown;
    try {
      body = JSON.parse(catalogJson);
    } catch {
      setError("JSON کاتالوگ معتبر نیست.");
      return;
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      setError("ساختار کاتالوگ باید یک شیء JSON باشد.");
      return;
    }
    setCatalogSubmitting(true);
    setError("");
    try {
      const token = getActiveToken();
      const response = await fetch("/api/v1/admin/curriculum/catalog/import", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(token),
        },
        body: JSON.stringify(body),
      });
      if (response.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است؛ دوباره وارد شوید.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "ورود کاتالوگ برنامهٔ درسی ناموفق بود.");
      const fieldResponse = await fetch("/api/v1/curriculum/fields", { cache: "no-store" });
      if (fieldResponse.ok) setFieldOptions((await fieldResponse.json()) as CurriculumFieldOption[]);
      setUploadMessage("کاتالوگ برنامهٔ درسی با موفقیت به‌روزرسانی شد.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ورود کاتالوگ برنامهٔ درسی ناموفق بود.");
    } finally {
      setCatalogSubmitting(false);
    }
  };

  const handleSavePage = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!book || !selectedPage) return;
    setSavingPage(true);
    setSaveError("");
    setSaveMessage("");

    const parsedPrinted = editPrintedPage.trim() === "" ? null : Number(editPrintedPage);
    const parsedChapter = editChapterNumber.trim() === "" ? null : Number(editChapterNumber);
    if (parsedPrinted !== null && (!Number.isInteger(parsedPrinted) || parsedPrinted < 0)) {
      setSaveError("شمارهٔ صفحهٔ چاپی باید عدد صحیح نامنفی یا خالی باشد.");
      setSavingPage(false);
      return;
    }
    if (parsedChapter !== null && (!Number.isInteger(parsedChapter) || parsedChapter < 0)) {
      setSaveError("شمارهٔ فصل باید عدد صحیح نامنفی یا خالی باشد.");
      setSavingPage(false);
      return;
    }

    try {
      const token = getActiveToken();
      const response = await fetch(`/api/v1/admin/books/${book.id}/pages/${selectedPage.pdf_page_index}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(token),
        },
        credentials: "same-origin",
        body: JSON.stringify({
          printed_page_number: parsedPrinted,
          chapter_number: parsedChapter,
          chapter_title: editChapterTitle.trim() === "" ? null : editChapterTitle.trim(),
          markdown_content: editMarkdown,
        }),
      });
      if (response.status === 401) {
        lockAdminPanel();
        throw new Error("نشست مدیریت منقضی شده است؛ لطفاً دوباره وارد شوید.");
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "ذخیرهٔ صفحه انجام نشد.");
      setSaveMessage(`صفحهٔ PDF ${selectedPage.pdf_page_index} ذخیره و به‌عنوان «تأییدشده» ثبت شد.`);
      setPreviewVersion((current) => current + 1);
      await Promise.all([
        refreshBooksAndSelect(book.id),
        refreshBookPages(book.id, selectedPage.pdf_page_index),
      ]);
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : "خطا در ذخیرهٔ صفحه");
    } finally {
      setSavingPage(false);
    }
  };

  const handleSaveBillingSettings = async (event: React.FormEvent) => {
    event.preventDefault();
    const token = getActiveToken();
    setBillingSaving(true);
    setBillingError("");
    setBillingMessage("");
    try {
      const response = await fetch("/api/v1/admin/billing/settings", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify(billingSettings),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { settings?: BillingSettingsData; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "ذخیره تنظیمات توکن انجام نشد");
      if (payload.settings) setBillingSettings(payload.settings);
      setBillingMessage("قیمت توکن و تنظیمات هدیه ثبت‌نام با موفقیت ذخیره شد.");
    } catch (cause) {
      setBillingError(cause instanceof Error ? cause.message : "خطا در ذخیره تنظیمات");
    } finally {
      setBillingSaving(false);
    }
  };

  const handleSavePlan = async (plan: PlanItem) => {
    const token = getActiveToken();
    setSavingPlanCode(plan.code);
    setBillingError("");
    setBillingMessage("");
    try {
      const response = await fetch(`/api/v1/admin/billing/plans/${plan.code}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify({
          name: plan.name,
          description: plan.description,
          price_toman: Number(plan.price_toman),
          token_quota: Number(plan.token_quota),
          duration_days: Number(plan.duration_days),
          storage_quota_bytes: Number(plan.storage_quota_bytes || 104_857_600),
          is_active: plan.is_active,
        }),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { plan?: PlanItem; detail?: string };
      if (!response.ok) throw new Error(payload.detail ?? "ذخیره پلن انجام نشد");
      if (payload.plan) {
        setPlans((prev) => prev.map((item) => (item.code === plan.code ? payload.plan! : item)));
      }
      setBillingMessage(`تغییرات پلن «${plan.name}» با موفقیت ذخیره شد.`);
    } catch (cause) {
      setBillingError(cause instanceof Error ? cause.message : "خطا در ذخیره پلن");
    } finally {
      setSavingPlanCode(null);
    }
  };

  const selectUserForEdit = (u: StudentUser) => {
    setEditingUser(u);
    setEditUserPlan(u.plan_code);
    setEditUserApplyPlanDefaults(false);
    setEditUserAddTokens("");
    setEditUserDurationDays("");
    setEditUserActive(u.is_active);
    setUserMessage("");
    setUserError("");
    void fetchUserSessions(u.id);
  };

  const handleSaveUser = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    const token = getActiveToken();
    setUserSaving(true);
    setUserError("");
    setUserMessage("");
    try {
      const body: Record<string, unknown> = {
        plan_code: editUserPlan,
        apply_plan_defaults: editUserApplyPlanDefaults,
        is_active: editUserActive,
      };
      if (editUserAddTokens.trim() !== "") {
        body.add_tokens = Number(editUserAddTokens);
      }
      if (editUserDurationDays.trim() !== "") {
        body.duration_days = Number(editUserDurationDays);
      }
      const response = await fetch(`/api/v1/admin/users/${editingUser.id}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...buildAuthHeaders(token) },
        body: JSON.stringify(body),
      });
      if (response.status === 401) {
        lockAdminPanel();
        return;
      }
      const payload = (await response.json()) as { user?: StudentUser; detail?: string };
      if (!response.ok || !payload.user) throw new Error(payload.detail ?? "به‌روزرسانی کاربر انجام نشد");
      setUserMessage(`اطلاعات کاربر ${payload.user.phone_number} با موفقیت به‌روزرسانی شد.`);
      setEditingUser(payload.user);
      setEditUserAddTokens("");
      setEditUserDurationDays("");
      setEditUserApplyPlanDefaults(false);
      await fetchUsersData();
      if (usageReportUserId === payload.user.id) {
        await fetchUserUsageReport(payload.user.id);
      }
    } catch (cause) {
      setUserError(cause instanceof Error ? cause.message : "خطا در به‌روزرسانی کاربر");
    } finally {
      setUserSaving(false);
    }
  };

  if (authState === "checking") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <div className="admin-login-card">
          <div className="admin-login-icon">
            <LoaderCircle size={24} className="spin" />
          </div>
          <h1>بررسی دسترسی مدیریت...</h1>
        </div>
      </main>
    );
  }

  if (authState === "locked") {
    return (
      <main className="admin-login-shell" dir="rtl">
        <section className="admin-login-card" aria-labelledby="admin-login-title">
          <div className="admin-login-icon">
            <LockKeyhole size={24} />
          </div>
          <span className="eyebrow">دسترسی محدود</span>
          <h1 id="admin-login-title">ورود به پنل مدیریت درسیار</h1>
          <p>این بخش از محیط دانش‌آموز جداست. برای مدیریت کتاب‌های درسی، نام کاربری و رمز عبور مدیر را وارد کنید.</p>
          <form onSubmit={handleLogin} className="admin-form">
            <label className="form-field">
              <span>نام کاربری</span>
              <input
                type="text"
                dir="ltr"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
                autoComplete="username"
                autoFocus
              />
            </label>
            <label className="form-field">
              <span>رمز عبور</span>
              <div className="password-input-wrap">
                <input
                  type={showPassword ? "text" : "password"}
                  dir="ltr"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="رمز عبور را وارد کنید"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "مخفی کردن رمز" : "نمایش رمز"}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            {authError && <div className="inline-error">{authError}</div>}
            <button className="primary-button admin-submit" type="submit" disabled={authBusy}>
              {authBusy ? <LoaderCircle size={17} className="spin" /> : <LockKeyhole size={17} />}
              ورود به پنل مدیریت
            </button>
          </form>
          <Link className="back-link admin-login-back" href="/">
            <ArrowRight size={16} /> بازگشت به سایت
          </Link>
        </section>
      </main>
    );
  }

  // Sidebar selection: same side effects the flat tab bar used to run.
  const handleAdminNavSelect = (key: AdminNavKey) => {
    setAdminTab(key);
    if (key === "overview") void fetchOverviewData();
    if (key === "plans") void fetchBillingData();
    if (key === "users") {
      void fetchUsersData();
      void fetchBillingData();
    }
  };
  return (
    <main className="admin-shell" dir="rtl">
      <header className="admin-topbar">
        <div className="admin-brand">
          <div className="brand-mark">د</div>
          <div>
            <b>مدیریت درسیار</b>
            <span>مرکز محتوای آموزشی</span>
          </div>
        </div>
        <div className="admin-topbar-actions">
          <button
            type="button"
            className={`admin-theme-chip ${systemMode === "production" ? "live-mode" : ""}`}
            onClick={() => setAdminTab("integrations")}
            title="وضعیت اجرای هوش مصنوعی و تنظیمات API"
          >
            <Zap size={14} />
            <span>{systemMode === "production" ? "تولید AI" : "حالت دمو"}</span>
          </button>
          <button
            type="button"
            className="admin-theme-chip"
            onClick={cycleQuickColorMode}
            title="تغییر سریع حالت رنگ (روشن / تاریک / سیستم)"
            aria-label="تغییر سریع حالت رنگ"
          >
            {adminPreferences.appearance.color_mode === "system" ? (
              <Monitor size={15} />
            ) : effectiveAdminColorMode === "dark" ? (
              <Moon size={15} />
            ) : (
              <Sun size={15} />
            )}
            <span>
              {adminPreferences.appearance.color_mode === "system"
                ? "سیستم"
                : effectiveAdminColorMode === "dark"
                ? "تاریک"
                : "روشن"}
            </span>
          </button>
          <button
            type="button"
            className={`admin-theme-chip ${adminTab === "appearance" ? "active" : ""}`}
            onClick={() => setAdminTab("appearance")}
            title="تنظیمات ظاهر و دسترس‌پذیری"
          >
            <Palette size={15} />
            <span>ظاهر</span>
          </button>
          <Link className="back-link" href="/">
            <ArrowRight size={17} /> مشاهدهٔ سایت
          </Link>
          <button type="button" className="admin-logout-btn" onClick={() => void handleLogout()}>
            <LogOut size={15} /> خروج
          </button>
          <GlobalSearch
            mode="admin"
            authToken={activeTokenState}
            isAuthenticated
            quickCommands={adminQuickCommands}
            onAdminSelectBook={handleAdminJumpBook}
            onAdminSelectUser={handleAdminJumpUser}
            onAdminSelectPlan={() => {
              setAdminTab("plans");
              void fetchBillingData();
            }}
          />
        </div>
      </header>
      <div className="admin-body">
        <AdminSideNav active={adminTab} onSelect={handleAdminNavSelect} />
      <div className="admin-content">
        <div className="admin-heading">
          <div>
            <span className="eyebrow">مرکز کنترل جامع مدیریت درسیار</span>
            <h1>
              {adminTab === "overview"
                ? "نمای کلی، سلامت سرویس‌ها و تراکنش‌ها"
                : adminTab === "books"
                ? "افزودن و بازبینی کتاب درسی"
                : adminTab === "plans"
                ? "مدیریت قیمت توکن، فضا و پلن‌ها"
                : adminTab === "users"
                ? "مدیریت کاربران، نشست‌ها و سهمیه‌ها"
                : adminTab === "integrations"
                ? "مرکز کنترل API هوش مصنوعی، مدل‌ها و درگاه‌ها"
                : "ظاهر، تم و دسترس‌پذیری پنل مدیریت"}
            </h1>
            <p>
              {adminTab === "overview"
                ? "گزارش زنده وضعیت سرور، آمار کل کتاب‌ها و کاربران، صفحه‌های نیازمند بازبینی و آخرین تراکنش‌های مالی و مصرف توکن."
                : adminTab === "books"
                ? "کتاب را وارد کن، چند صفحه را آزمایشی پردازش کن، خروجی را با PDF بسنج و صفحه‌ها یا بردارهای RAG را مدیریت کن."
                : adminTab === "plans"
                ? "قیمت پایهٔ توکن، سهمیهٔ هر پلن، فضای ذخیره‌سازی، مدت اعتبار و مبلغ پلن‌ها را تنظیم کنید."
                : adminTab === "users"
                ? "وضعیت کاربران ثبت‌نامی، میزان مصرف توکن، پلن فعال، نشست‌های باز و شارژ حساب‌ها را مدیریت کنید."
                : adminTab === "integrations"
                ? "کلید API و آدرس سرویس هوش مصنوعی، مدل‌های معلم/بینایی/صدا/امبدینگ، جستجوی برداری، پیامک OTP و زرین‌پال را بدون نیاز به ری‌استارت تنظیم کنید."
                : "حالت روشن/تاریک/سیستم، رنگ‌های مستقل، فونت UI و کد، کنتراست و نشانگرهای Diff را تنظیم کنید."}
            </p>
          </div>
          <div className="admin-heading-mark">
            {adminTab === "overview" ? (
              <Activity size={25} />
            ) : adminTab === "books" ? (
              <BookOpen size={25} />
            ) : adminTab === "plans" ? (
              <Crown size={25} />
            ) : adminTab === "users" ? (
              <Users size={25} />
            ) : adminTab === "integrations" ? (
              <Cpu size={25} />
            ) : (
              <Palette size={25} />
            )}
          </div>
        </div>


        <div className="admin-warning admin-protected-note">
          <ShieldCheck size={18} />
          <span>
            <b>دسترسی محافظت‌شده با رمز عبور</b> · مسیر /admin از محیط دانش‌آموز جدا شده است. پیش از انتشار نهایی، مقدار ADMIN_PASSWORD را به رمز قوی تغییر دهید.
          </span>
        </div>

        {adminTab === "overview" && (
          <AdminOverviewPanel
            overview={overviewData}
            loading={overviewLoading}
            error={overviewError}
            onRefresh={() => void fetchOverviewData()}
            onJumpToTab={(tab) => {
              setAdminTab(tab);
              if (tab === "plans") void fetchBillingData();
              if (tab === "users") {
                void fetchUsersData();
                void fetchBillingData();
              }
            }}
            onJumpToBookPage={handleAdminJumpBook}
            onJumpToUser={handleAdminJumpUser}
          />
        )}

        {adminTab === "integrations" && (
          <AdminIntegrationsPanel
            authHeaders={authHeadersMemo}
            onUnauthorized={lockAdminPanel}
            onSettingsApplied={(payload: AdminSystemSettingsPayload) => {
              setSystemMode(payload.config.demo_mode ? "demo" : "production");
            }}
          />
        )}

        {adminTab === "providers" && (
          <AdminProvidersPanel
            authHeaders={authHeadersMemo}
            onUnauthorized={lockAdminPanel}
          />
        )}

        {adminTab === "observability" && (
          <AdminObservabilityPanel
            authHeaders={authHeadersMemo}
            onUnauthorized={lockAdminPanel}
          />
        )}

        {adminTab === "roles" && (
          <AdminRolesQuotasPanel
            authHeaders={authHeadersMemo}
            onUnauthorized={lockAdminPanel}
          />
        )}

        {adminTab === "kb" && (
          <AdminKbPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "skills" && (
          <AdminSkillsPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "capabilities" && (
          <AdminCapabilitiesPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "flashcards" && (
          <AdminFlashcardsPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "deep_learning" && (
          <AdminPhase5Panel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "rich_study" && (
          <AdminPhase6Panel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "podcasts" && (
          <AdminPodcastsPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
        )}

        {adminTab === "appearance" && (
          <AdminAppearancePanel
            preferences={adminPreferences}
            systemIsDark={systemIsDark}
            saving={appearanceSaving}
            onPatchPreferences={patchAdminPreferences}
            onResetPreferences={resetAdminPreferences}
          />
        )}

        {adminTab === "plans" && (
          <div className="admin-billing-stack">
            {billingMessage && <div className="success-note admin-banner"><CheckCircle2 size={15} />{billingMessage}</div>}
            {billingError && <div className="inline-error admin-banner">{billingError}</div>}

            <section className="admin-card">
              <div className="card-heading">
                <div>
                  <h2>قیمت پایهٔ توکن و اعتبار هدیهٔ ثبت‌نام</h2>
                  <p>ارزش معادل هر ۱٬۰۰۰ توکن مصرفی به تومان و سهمیهٔ اولیه کاربران تازه‌وارد.</p>
                </div>
                <span className="step-badge"><Coins size={14} /></span>
              </div>
              <form className="admin-form" onSubmit={handleSaveBillingSettings}>
                <div className="form-row">
                  <label className="form-field">
                    <span>قیمت هر ۱٬۰۰۰ توکن (تومان)</span>
                    <input
                      type="number"
                      min={1}
                      value={billingSettings.token_price_per_1k_toman}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          token_price_per_1k_toman: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>توکن هدیه ثبت‌نام جدید</span>
                    <input
                      type="number"
                      min={0}
                      value={billingSettings.starter_tokens}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          starter_tokens: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>مدت اعتبار هدیه (روز)</span>
                    <input
                      type="number"
                      min={1}
                      value={billingSettings.starter_duration_days}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          starter_duration_days: Number(e.target.value),
                        }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>فضای ذخیره هدیه (مگابایت)</span>
                    <input
                      type="number"
                      min={1}
                      max={10240}
                      value={Math.max(
                        1,
                        Math.round((billingSettings.starter_storage_bytes ?? 25 * 1024 * 1024) / (1024 * 1024))
                      )}
                      onChange={(e) =>
                        setBillingSettings((prev) => ({
                          ...prev,
                          starter_storage_bytes: Math.max(1, Number(e.target.value)) * 1024 * 1024,
                        }))
                      }
                    />
                  </label>
                </div>
                <div className="admin-inline-actions">
                  <button className="primary-button" type="submit" disabled={billingSaving || billingLoading}>
                    {billingSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                    ذخیره تنظیمات توکن
                  </button>
                </div>
              </form>
            </section>

            <section className="admin-plans-grid">
              {plans.map((plan) => (
                <article key={plan.code} className="admin-card">
                  <div className="card-heading">
                    <div>
                      <h2>پلن {plan.name} ({plan.code})</h2>
                      <p>تعرفه مؤثر: {formatFaNumber(plan.token_quota > 0 ? Math.round((plan.price_toman * 1000) / plan.token_quota) : 0)} تومان / ۱٬۰۰۰ توکن</p>
                    </div>
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={plan.is_active}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, is_active: e.target.checked } : item
                            )
                          )
                        }
                      />
                      <span>فعال</span>
                    </label>
                  </div>
                  <div className="admin-form">
                    <label className="form-field">
                      <span>عنوان پلن</span>
                      <input
                        value={plan.name}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) => (item.code === plan.code ? { ...item, name: e.target.value } : item))
                          )
                        }
                      />
                    </label>
                    <label className="form-field">
                      <span>قیمت پلن (تومان)</span>
                      <input
                        type="number"
                        min={0}
                        value={plan.price_toman}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, price_toman: Number(e.target.value) } : item
                            )
                          )
                        }
                      />
                    </label>
                    <div className="form-row">
                      <label className="form-field">
                        <span>میزان توکن (سهمیه)</span>
                        <input
                          type="number"
                          min={1}
                          value={plan.token_quota}
                          onChange={(e) =>
                            setPlans((prev) =>
                              prev.map((item) =>
                                item.code === plan.code ? { ...item, token_quota: Number(e.target.value) } : item
                              )
                            )
                          }
                        />
                      </label>
                      <label className="form-field">
                        <span>زمان استفاده (روز)</span>
                        <input
                          type="number"
                          min={1}
                          value={plan.duration_days}
                          onChange={(e) =>
                            setPlans((prev) =>
                              prev.map((item) =>
                                item.code === plan.code ? { ...item, duration_days: Number(e.target.value) } : item
                              )
                            )
                          }
                        />
                      </label>
                      <label className="form-field">
                        <span>حجم فایل (مگابایت)</span>
                        <input
                          type="number"
                          min={1}
                          max={102400}
                          value={Math.max(1, Math.round((plan.storage_quota_bytes || 104_857_600) / (1024 * 1024)))}
                          onChange={(e) =>
                            setPlans((prev) =>
                              prev.map((item) =>
                                item.code === plan.code
                                  ? {
                                      ...item,
                                      storage_quota_bytes: Math.max(1, Number(e.target.value)) * 1024 * 1024,
                                    }
                                  : item
                              )
                            )
                          }
                        />
                      </label>
                    </div>
                    <label className="form-field">
                      <span>توضیحات نمایشی</span>
                      <input
                        value={plan.description}
                        onChange={(e) =>
                          setPlans((prev) =>
                            prev.map((item) =>
                              item.code === plan.code ? { ...item, description: e.target.value } : item
                            )
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="primary-button admin-submit"
                      disabled={savingPlanCode === plan.code}
                      onClick={() => void handleSavePlan(plan)}
                    >
                      {savingPlanCode === plan.code ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                      ذخیره تغییرات پلن {plan.name}
                    </button>
                  </div>
                </article>
              ))}
            </section>
          </div>
        )}

        {adminTab === "users" && (
          <div className="admin-users-shell">
            <AdminUsersPanel authHeaders={authHeadersMemo} onUnauthorized={lockAdminPanel} />
          </div>
        )}

        {adminTab === "users" && (
          <div className="admin-billing-stack">
            {usersSummary && (
              <div className="admin-kpi-grid">
                <div className="admin-kpi-card"><span>کل کاربران</span><b>{formatFaNumber(usersSummary.total_users)}</b></div>
                <div className="admin-kpi-card"><span>کاربران با پلن خریداری‌شده</span><b>{formatFaNumber(usersSummary.paid_users)}</b></div>
                <div className="admin-kpi-card"><span>مجموع توکن مصرفی</span><b>{formatFaNumber(usersSummary.total_tokens_used)}</b></div>
                <div className="admin-kpi-card"><span>درآمد پرداخت‌ها (تومان)</span><b>{formatFaNumber(usersSummary.total_revenue_toman)}</b></div>
              </div>
            )}

            <section className="admin-card">
              <div className="users-toolbar">
                <div className="users-search">
                  <Search size={15} />
                  <input
                    placeholder="جستجو با شماره موبایل یا نام..."
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void fetchUsersData(userSearch, userPlanFilter);
                    }}
                  />
                </div>
                <select
                  value={userPlanFilter}
                  onChange={(e) => {
                    setUserPlanFilter(e.target.value);
                    void fetchUsersData(userSearch, e.target.value);
                  }}
                >
                  <option value="all">همه پلن‌ها</option>
                  <option value="trial">هدیه ثبت‌نام</option>
                  <option value="normal">اقتصادی</option>
                  <option value="pro">حرفه‌ای</option>
                  <option value="vip">هوشمندانه</option>
                </select>
                <button
                  type="button"
                  className="outline-button"
                  onClick={() => void fetchUsersData(userSearch, userPlanFilter)}
                >
                  بروزرسانی لیست
                </button>
              </div>

              {userMessage && <div className="success-note admin-banner"><CheckCircle2 size={15} />{userMessage}</div>}
              {userError && <div className="inline-error admin-banner">{userError}</div>}

              {usersLoading ? (
                <div className="review-loading surface-loading"><LoaderCircle className="spin" size={18} /><span>در حال دریافت کاربران...</span></div>
              ) : users.length === 0 ? (
                <div className="review-empty surface-empty">هنوز کاربری ثبت‌نام نکرده است.</div>
              ) : (
                <div className="admin-users-table-wrap">
                  <table className="admin-users-table">
                    <thead>
                      <tr>
                        <th>موبایل / نام</th>
                        <th>پلن فعلی</th>
                        <th>توکن باقی‌مانده</th>
                        <th>مصرف امروز / کل</th>
                        <th>ارزش مصرف (تومان)</th>
                        <th>اعتبار باقی‌مانده</th>
                        <th>وضعیت</th>
                        <th>عملیات</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr
                          key={u.id}
                          className={editingUser?.id === u.id || usageReportUserId === u.id ? "selected" : ""}
                        >
                          <td>
                            <b dir="ltr">{u.phone_number}</b>
                            <small>{u.full_name || "بدون نام"}</small>
                          </td>
                          <td><span className={`badge-pill ${u.is_expired ? "failed" : "done"}`}>{u.plan_title}</span></td>
                          <td>{formatFaNumber(u.tokens_remaining)} / {formatFaNumber(u.tokens_total)}</td>
                          <td>{formatFaNumber(u.tokens_used_today)} / {formatFaNumber(u.tokens_used_total)}</td>
                          <td>{formatFaNumber(u.used_value_toman)}</td>
                          <td>{u.is_expired ? "منقضی" : `${formatFaNumber(u.days_remaining)} روز`}</td>
                          <td>{u.is_active ? "فعال" : "مسدود"}</td>
                          <td>
                            <div className="user-row-actions">
                              <button
                                type="button"
                                className="outline-button"
                                onClick={() => void fetchUserUsageReport(u.id)}
                              >
                                <BarChart3 size={14} />
                                گزارش مصرف
                              </button>
                              <button
                                type="button"
                                className="outline-button"
                                onClick={() => selectUserForEdit(u)}
                              >
                                ویرایش / شارژ
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

            {usageReportUserId && (
              <section className="admin-card">
                <div className="card-heading">
                  <div>
                    <h2>
                      گزارش مصرف توکن کاربر{" "}
                      <span dir="ltr">{usageReport?.user.phone_number ?? ""}</span>
                      {usageReport?.user.full_name ? ` (${usageReport.user.full_name})` : ""}
                    </h2>
                    <p>ریز مصرف به تفکیک نوع فعالیت، تاریخچه روزانه، درخواست‌ها و تراکنش‌های پرداختی.</p>
                  </div>
                  <div className="report-head-actions">
                    <button
                      type="button"
                      className="outline-button"
                      disabled={usageReportLoading}
                      onClick={() => void fetchUserUsageReport(usageReportUserId)}
                    >
                      <RefreshCw size={14} className={usageReportLoading ? "spin" : ""} />
                      بروزرسانی
                    </button>
                    {usageReport && usageReport.logs.length > 0 && (
                      <button
                        type="button"
                        className="outline-button"
                        onClick={downloadUserUsageCsv}
                      >
                        <Download size={14} />
                        خروجی CSV
                      </button>
                    )}
                    <button
                      type="button"
                      className="icon-button"
                      onClick={() => {
                        setUsageReportUserId(null);
                        setUsageReport(null);
                        setUsageReportError("");
                      }}
                      aria-label="بستن گزارش"
                    >
                      <XCircle size={18} />
                    </button>
                  </div>
                </div>

                {usageReportError && <div className="inline-error admin-banner">{usageReportError}</div>}

                {usageReportLoading && !usageReport ? (
                  <div className="review-loading surface-loading">
                    <LoaderCircle className="spin" size={18} />
                    <span>در حال دریافت گزارش مصرف توکن کاربر...</span>
                  </div>
                ) : usageReport ? (
                  <div className="user-report-stack">
                    <div className="admin-kpi-grid">
                      <div className="admin-kpi-card">
                        <span>مصرف امروز</span>
                        <b>{formatFaNumber(usageReport.user.tokens_used_today)} توکن</b>
                      </div>
                      <div className="admin-kpi-card">
                        <span>مجموع مصرف کل</span>
                        <b>{formatFaNumber(usageReport.user.tokens_used_total)} توکن</b>
                      </div>
                      <div className="admin-kpi-card">
                        <span>ارزش کل مصرف (تومان)</span>
                        <b>{formatFaNumber(usageReport.user.used_value_toman)} تومان</b>
                      </div>
                      <div className="admin-kpi-card">
                        <span>توکن باقی‌مانده</span>
                        <b>{formatFaNumber(usageReport.user.tokens_remaining)} توکن</b>
                      </div>
                    </div>

                    <div className="user-report-split">
                      <div className="user-report-panel">
                        <h3>تفکیک بر اساس نوع فعالیت</h3>
                        {usageReport.by_action.length === 0 ? (
                          <div className="usage-empty">هنوز هیچ مصرفی ثبت نشده است.</div>
                        ) : (
                          <div className="admin-users-table-wrap">
                            <table className="admin-users-table compact">
                              <thead>
                                <tr>
                                  <th>فعالیت</th>
                                  <th>تعداد</th>
                                  <th>ورودی / خروجی</th>
                                  <th>کل توکن</th>
                                  <th>هزینه (تومان)</th>
                                </tr>
                              </thead>
                              <tbody>
                                {usageReport.by_action.map((item) => (
                                  <tr key={item.action}>
                                    <td><b>{actionLabels[item.action] ?? item.action}</b></td>
                                    <td>{formatFaNumber(item.count)}</td>
                                    <td>{formatFaNumber(item.prompt_tokens)} / {formatFaNumber(item.completion_tokens)}</td>
                                    <td><b>{formatFaNumber(item.total_tokens)}</b></td>
                                    <td>{formatFaNumber(item.cost_toman)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>

                      <div className="user-report-panel">
                        <h3>گزارش روزانه (۳۰ روز اخیر)</h3>
                        {usageReport.daily.length === 0 ? (
                          <div className="usage-empty">در ۳۰ روز گذشته مصرفی ثبت نشده است.</div>
                        ) : (
                          <div className="admin-users-table-wrap user-report-scroll">
                            <table className="admin-users-table compact">
                              <thead>
                                <tr>
                                  <th>تاریخ</th>
                                  <th>درخواست</th>
                                  <th>توکن مصرفی</th>
                                  <th>هزینه (تومان)</th>
                                </tr>
                              </thead>
                              <tbody>
                                {usageReport.daily.map((day) => (
                                  <tr key={day.date}>
                                    <td><b>{formatFaDate(day.date)}</b></td>
                                    <td>{formatFaNumber(day.requests)}</td>
                                    <td><b>{formatFaNumber(day.total_tokens)}</b></td>
                                    <td>{formatFaNumber(day.cost_toman)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="user-report-panel">
                      <h3>ریز درخواست‌های مصرف توکن ({formatFaNumber(usageReport.logs.length)} مورد اخیر)</h3>
                      {usageReport.logs.length === 0 ? (
                        <div className="usage-empty">هیچ درخواستی ثبت نشده است.</div>
                      ) : (
                        <div className="admin-users-table-wrap user-report-scroll">
                          <table className="admin-users-table compact">
                            <thead>
                              <tr>
                                <th>تاریخ و ساعت</th>
                                <th>نوع فعالیت</th>
                                <th>کتاب درسی</th>
                                <th>ورودی / خروجی</th>
                                <th>مجموع توکن</th>
                                <th>هزینه (تومان)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {usageReport.logs.map((log) => (
                                <tr key={log.id}>
                                  <td><small>{formatFaDateTime(log.created_at)}</small></td>
                                  <td><b>{actionLabels[log.action] ?? log.action}</b></td>
                                  <td>{log.book_title || (log.book_id ? `کتاب #${log.book_id}` : "—")}</td>
                                  <td>{formatFaNumber(log.prompt_tokens)} / {formatFaNumber(log.completion_tokens)}</td>
                                  <td><b>{formatFaNumber(log.total_tokens)}</b></td>
                                  <td>{formatFaNumber(log.cost_toman)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>

                    <div className="user-report-panel">
                      <h3>تاریخچهٔ پرداخت‌ها و تخصیص پلن‌ها</h3>
                      {usageReport.transactions.length === 0 ? (
                        <div className="usage-empty">تراکنش یا تخصیص پلنی برای این کاربر ثبت نشده است.</div>
                      ) : (
                        <div className="admin-users-table-wrap user-report-scroll">
                          <table className="admin-users-table compact">
                            <thead>
                              <tr>
                                <th>تاریخ</th>
                                <th>پلن</th>
                                <th>روش / درگاه</th>
                                <th>مبلغ (تومان)</th>
                                <th>توکن و مدت</th>
                                <th>وضعیت / پیگیری</th>
                              </tr>
                            </thead>
                            <tbody>
                              {usageReport.transactions.map((tx) => (
                                <tr key={tx.id}>
                                  <td><small>{formatFaDateTime(tx.paid_at ?? tx.created_at)}</small></td>
                                  <td><b>{tx.plan_name}</b></td>
                                  <td>{providerLabels[tx.provider] ?? tx.provider}</td>
                                  <td>{formatFaNumber(tx.amount_toman)}</td>
                                  <td>{formatFaNumber(tx.tokens_granted)} توکن · {formatFaNumber(tx.duration_days)} روز</td>
                                  <td>
                                    <span className={`badge-pill ${tx.status === "paid" ? "done" : "failed"}`}>
                                      {tx.status === "paid" ? "تأییدشده" : tx.status}
                                    </span>
                                    {tx.ref_id && <small dir="ltr">Ref: {tx.ref_id}</small>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </section>
            )}

            {editingUser && (
              <section className="admin-card">
                <div className="card-heading">
                  <div>
                    <h2>مدیریت حساب کاربر <span dir="ltr">{editingUser.phone_number}</span></h2>
                    <p>تخصیص پلن، افزایش توکن، تغییر مدت اعتبار یا فعال/غیرفعال‌سازی دسترسی.</p>
                  </div>
                  <button type="button" className="icon-button" onClick={() => setEditingUser(null)} aria-label="بستن">
                    <XCircle size={18} />
                  </button>
                </div>
                <form className="admin-form" onSubmit={handleSaveUser}>
                  <div className="form-row">
                    <label className="form-field">
                      <span>تغییر پلن</span>
                      <select value={editUserPlan} onChange={(e) => setEditUserPlan(e.target.value)}>
                        <option value="trial">هدیه ثبت‌نام (trial)</option>
                        {plans.map((p) => (
                          <option key={p.code} value={p.code}>
                            {p.name} ({formatFaNumber(p.token_quota)} توکن / {p.duration_days} روز)
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="form-field">
                      <span>افزایش / کاهش توکن (اختیاری)</span>
                      <input
                        type="number"
                        placeholder="مثلاً 100000"
                        value={editUserAddTokens}
                        onChange={(e) => setEditUserAddTokens(e.target.value)}
                      />
                    </label>
                    <label className="form-field">
                      <span>تمدید اعتبار از امروز (روز، اختیاری)</span>
                      <input
                        type="number"
                        min={1}
                        placeholder="مثلاً 30"
                        value={editUserDurationDays}
                        onChange={(e) => setEditUserDurationDays(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="admin-inline-checks">
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={editUserApplyPlanDefaults}
                        onChange={(e) => setEditUserApplyPlanDefaults(e.target.checked)}
                      />
                      <span>سهمیه توکن و مدت روز پلن انتخابی را روی حساب اعمال کن</span>
                    </label>
                    <label className="plan-active-toggle">
                      <input
                        type="checkbox"
                        checked={editUserActive}
                        onChange={(e) => setEditUserActive(e.target.checked)}
                      />
                      <span>حساب کاربری فعال باشد</span>
                    </label>
                  </div>
                  <div className="admin-inline-actions" style={{ gap: 10, flexWrap: "wrap" }}>
                    <button type="submit" className="primary-button" disabled={userSaving}>
                      {userSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                      اعمال تغییرات کاربر
                    </button>
                    <button
                      type="button"
                      className="outline-button"
                      disabled={revokingSessions}
                      onClick={() => void handleRevokeUserSessions(editingUser.id)}
                    >
                      {revokingSessions ? <LoaderCircle className="spin" size={15} /> : <ShieldOff size={15} />}
                      بستن تمام نشست‌های فعال کاربر
                    </button>
                  </div>
                </form>

                <div className="admin-sub-divider" style={{ margin: "18px 0 12px" }} />
                <div className="card-heading" style={{ marginBottom: 10 }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: 13 }}>نشست‌های ورود اخیر کاربر</h3>
                    <p style={{ margin: "4px 0 0", fontSize: 11 }}>دستگاه‌ها و آی‌پی‌های ورود این دانش‌آموز</p>
                  </div>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={userSessionsLoading}
                    onClick={() => void fetchUserSessions(editingUser.id)}
                  >
                    <RefreshCw size={13} className={userSessionsLoading ? "spin" : ""} /> بروزرسانی نشست‌ها
                  </button>
                </div>
                {userSessionsLoading ? (
                  <div className="review-loading surface-loading">
                    <LoaderCircle className="spin" size={16} />
                    <span>در حال دریافت نشست‌ها...</span>
                  </div>
                ) : userSessions.length === 0 ? (
                  <div className="usage-empty">هیچ نشستی برای این کاربر ثبت نشده است.</div>
                ) : (
                  <div className="admin-users-table-wrap user-report-scroll">
                    <table className="admin-users-table compact">
                      <thead>
                        <tr>
                          <th>دستگاه / مرورگر</th>
                          <th>IP</th>
                          <th>وضعیت</th>
                          <th>آخرین فعالیت</th>
                        </tr>
                      </thead>
                      <tbody>
                        {userSessions.map((sess) => (
                          <tr key={sess.id}>
                            <td><small dir="ltr">{sess.user_agent || "نامشخص"}</small></td>
                            <td><small dir="ltr">{sess.ip_address || "—"}</small></td>
                            <td>
                              <span className={`badge-pill ${sess.is_active ? "done" : "failed"}`}>
                                {sess.is_active ? "فعال" : sess.revoked_at ? "لغوشده" : "منقضی"}
                              </span>
                            </td>
                            <td><small>{formatFaDateTime(sess.last_seen_at)}</small></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}
          </div>
        )}

        {adminTab === "books" && (
        <>
        <div className="admin-grid">
          <section className="admin-card">
              <div className="card-heading">
              <div>
                <h2>اطلاعات کتاب</h2>
                <p>فایل PDF، Markdown (.md)، JSON یا HTML کتاب درسی را بارگذاری کن.</p>
              </div>
              <span className="step-badge">۱</span>
            </div>
            <form onSubmit={submit} className="admin-form">
              <label className="form-field">
                <span>عنوان کتاب</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} required />
              </label>
              <div className="form-row">
                <label className="form-field">
                  <span>پایه</span>
                  <select
                    value={grade}
                    onChange={(event) => {
                      setGrade(Number(event.target.value));
                      setSelectedFieldCodes([]);
                      setBranchCode("theoretical");
                    }}
                  >
                    {Array.from({ length: 12 }, (_, index) => index + 1).map((number) => (
                      <option key={number} value={number}>
                        {number === 12 ? "دوازدهم" : `پایهٔ ${number}`}
                      </option>
                    ))}
                  </select>
                </label>
                {grade >= 10 && selectedFieldCodes.length === 0 && (
                  <label className="form-field">
                    <span>شاخهٔ تحصیلی</span>
                    <select value={branchCode} onChange={(event) => setBranchCode(event.target.value)}>
                      <option value="">انتخاب شاخه</option>
                      {branchOptions.map((item) => (
                        <option key={item.code} value={item.code}>{item.title}</option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              {grade >= 10 && (
                <div className="form-row">
                  <label className="form-field" style={{ flex: 1 }}>
                    <span>رشته‌ها / حوزه‌های کاربرد کتاب (برای کتاب مشترک چند مورد انتخاب کن)</span>
                    <select
                      multiple
                      value={selectedFieldCodes}
                      onChange={(event) =>
                        setSelectedFieldCodes(Array.from(event.target.selectedOptions, (option) => option.value))
                      }
                      style={{ minHeight: 104 }}
                    >
                      {fieldOptions.map((item) => (
                        <option key={item.code} value={item.code}>
                          {item.branch_title} — {item.title}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              )}
              <div className="form-row">
                <label className="form-field">
                  <span>درس (برای اتصال به هدف‌های یادگیری)</span>
                  <select value={subjectCode} onChange={(event) => setSubjectCode(event.target.value)}>
                    <option value="">بدون تعیین درس</option>
                    {subjectOptions.map((item) => (
                      <option key={item.code} value={item.code}>{item.title}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="form-row">
                <label className="form-field">
                  <span>کد سال تحصیلی (مثلاً 1405-1406)</span>
                  <input value={academicYearCode} onChange={(event) => setAcademicYearCode(event.target.value)} placeholder="1405-1406" />
                </label>
                <label className="form-field">
                  <span>ویرایش / نوبت چاپ</span>
                  <input value={editionLabel} onChange={(event) => setEditionLabel(event.target.value)} placeholder="چاپ اول" />
                </label>
                <label className="form-field">
                  <span>سال چاپ</span>
                  <input type="number" value={printYear} onChange={(event) => setPrintYear(event.target.value)} placeholder="1405" />
                </label>
              </div>
              <div className="form-row">
                <label className="form-field">
                  <span>ناشر</span>
                  <input value={publisher} onChange={(event) => setPublisher(event.target.value)} />
                </label>
              </div>
              {grade >= 10 && (
                <label className="plan-active-toggle">
                  <input type="checkbox" checked={isGeneralBook} onChange={(event) => setIsGeneralBook(event.target.checked)} />
                  <span>این کتاب علاوه بر رشته‌های انتخاب‌شده، منبع مشترک عمومی هم هست</span>
                </label>
              )}
              {isPdfUpload ? (
                <div className="form-row">
                  <label className="form-field">
                    <span>از صفحهٔ PDF</span>
                    <input
                      type="number"
                      min={1}
                      value={startPage}
                      onChange={(event) => setStartPage(Number(event.target.value))}
                    />
                  </label>
                  <label className="form-field">
                    <span>تا صفحهٔ PDF</span>
                    <input
                      type="number"
                      min={1}
                      value={endPage}
                      onChange={(event) => setEndPage(Number(event.target.value))}
                    />
                  </label>
                </div>
              ) : (
                <div className="review-tip" style={{ marginTop: 0 }}>
                  <Sparkles size={15} />
                  <span>
                    فایل{" "}
                    <b>
                      {selectedFileFormat === "markdown"
                        ? "Markdown"
                        : selectedFileFormat === "json"
                        ? "JSON"
                        : "HTML"}
                    </b>{" "}
                    به‌صورت خودکار به صفحه‌ها/بخش‌های ساخت‌یافته تبدیل و بلافاصله برای بازبینی آماده می‌شود.
                  </span>
                </div>
              )}
              <label className={`pdf-dropzone ${file ? "has-file" : ""}`}>
                <input
                  type="file"
                  accept=".pdf,.md,.markdown,.json,.html,.htm,application/pdf,text/markdown,application/json,text/html"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                <span className="drop-icon">{file ? <CheckCircle2 size={21} /> : <FileUp size={21} />}</span>
                <b>{file ? file.name : "فایل کتاب (PDF، MD، JSON یا HTML) را انتخاب کن"}</b>
                <small>
                  {file
                    ? `${selectedFileFormat.toUpperCase()} · ${
                        file.size >= 1024 * 1024
                          ? `${(file.size / (1024 * 1024)).toFixed(1)} مگابایت`
                          : `${Math.max(1, Math.round(file.size / 1024))} کیلوبایت`
                      }`
                    : "حداکثر ۱۰۰ مگابایت · PDF، Markdown (.md)، JSON (.json) یا HTML (.html)"}
                </small>
              </label>
              {error && (
                <div className="inline-error">
                  {error}
                  <button type="button" onClick={() => setError("")}>
                    <XCircle size={15} />
                  </button>
                </div>
              )}
              <button className="primary-button admin-submit" type="submit" disabled={submitting}>
                {submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
                آپلود و شروع پردازش
              </button>
            </form>
            <details className="admin-card" style={{ marginTop: 16 }}>
              <summary style={{ cursor: "pointer", fontWeight: 700, padding: 8 }}>
                ورود / به‌روزرسانی کاتالوگ رسمی برنامهٔ درسی
              </summary>
              <p className="muted-text">
                داده‌های سال تحصیلی، رشته‌ها، درس‌ها، فصل‌ها و هدف‌های یادگیری را به‌صورت JSON وارد کن.
                کد هر شاخه باید یکی از مقادیر نظری، فنی‌وحرفه‌ای یا کاردانشِ ثبت‌شده در سامانه باشد.
              </p>
              <textarea
                className="admin-textarea"
                rows={10}
                value={catalogJson}
                onChange={(event) => setCatalogJson(event.target.value)}
                spellCheck={false}
                aria-label="کاتالوگ برنامه درسی به فرمت JSON"
              />
              <button
                type="button"
                className="outline-button"
                disabled={catalogSubmitting}
                onClick={() => void handleImportCurriculumCatalog()}
                style={{ marginTop: 10 }}
              >
                {catalogSubmitting ? <LoaderCircle className="spin" size={15} /> : <Database size={15} />}
                واردکردن کاتالوگ
              </button>
            </details>
          </section>

          <section className="admin-card progress-card">
            <div className="card-heading">
              <div>
                <h2>وضعیت پردازش</h2>
                <p>استخراج صفحه‌به‌صفحه همراه با بازبینی‌پذیری.</p>
              </div>
              <span className="step-badge">۲</span>
            </div>

            {books.length > 0 && (
              <label className="form-field book-switcher">
                <span>انتخاب کتاب برای بررسی و بازبینی</span>
                <select
                  value={book?.id ?? ""}
                  onChange={(event) => {
                    const nextId = Number(event.target.value);
                    const found = books.find((item) => item.id === nextId) ?? null;
                    setBook(found);
                    setPages([]);
                    setPagesLoading(found !== null && found.status !== "ingesting");
                    selectPageForEdit(null);
                    setPreviewOpen(false);
                    setPreviewStatus("all");
                    setUploadMessage("");
                    setSaveMessage("");
                    setEditingBookMeta(false);
                    setDeleteBookConfirm("none");
                    setDeleteConflictDetail("");
                    setBookActionMessage("");
                    setBookActionError("");
                  }}
                >
                  {books.map((item) => (
                    <option key={item.id} value={item.id}>
                      #{item.id} · {item.title} ({item.total_pdf_pages} صفحه)
                    </option>
                  ))}
                </select>
              </label>
            )}

            {!book ? (
              <div className="admin-empty">
                <div>
                  <BookOpen size={22} />
                </div>
                <b>هنوز کتابی برای پردازش نیست</b>
                <span>بعد از آپلود، وضعیت هر صفحه اینجا نمایش داده می‌شود.</span>
              </div>
            ) : (
              <div className="progress-content">
                <div className="processing-book">
                  <div className="mini-book-icon">
                    <BookOpen size={20} />
                  </div>
                  <div>
                    <b>{book.title}</b>
                    <span>شناسهٔ کتاب: {book.id}</span>
                  </div>
                  <span className={`status-chip ${book.status}`}>
                    {book.status === "ingesting" ? (
                      <>
                        <LoaderCircle className="spin" size={13} />
                        در حال پردازش
                      </>
                    ) : book.status === "ready" ? (
                      <>
                        <CheckCircle2 size={13} />
                        منتشرشده
                      </>
                    ) : (
                      <>
                        <XCircle size={13} />
                        ناموفق
                      </>
                    )}
                  </span>
                </div>
                <div className="progress-label">
                  <span>صفحه‌های پردازش‌شده</span>
                  <b>
                    {processedPages} / {book.total_pdf_pages}
                  </b>
                </div>
                <div className="progress-track">
                  <span style={{ width: `${progress}%` }} />
                </div>
                <div className="status-counts">
                  <div>
                    <i className="done-dot" />
                    موفق <b>{book.pages.done ?? 0}</b>
                  </div>
                  <div>
                    <i className="review-dot" />
                    بازبینی <b>{book.pages.needs_review ?? 0}</b>
                  </div>
                  <div>
                    <i className="failed-dot" />
                    خطا <b>{book.pages.failed ?? 0}</b>
                  </div>
                </div>
                {uploadMessage && (
                  <div className="success-note">
                    <CheckCircle2 size={15} />
                    {uploadMessage}
                  </div>
                )}
                {book.status === "failed" && processedPages === 0 && (
                  <div className="inline-error" style={{ marginTop: 12 }}>
                    پردازش کتاب ناموفق بود و صفحه‌ای ثبت نشد.
                  </div>
                )}
                {book.status !== "ingesting" && processedPages > 0 && (
                  <button
                    className="outline-button preview-button"
                    type="button"
                    onClick={() => {
                      setPreviewStatus("all");
                      setPreviewVersion((current) => current + 1);
                      setPreviewOpen(true);
                    }}
                  >
                    <ExternalLink size={16} />
                    بازکردن پیش‌نمایش مقایسه‌ای
                  </button>
                )}
                <div className="admin-book-actions-bar">
                  <button
                    type="button"
                    className="outline-button"
                    onClick={() => openBookMetaEditor(book)}
                  >
                    <Pencil size={14} /> ویرایش مشخصات
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={bookActionBusy !== null || book.status === "ingesting"}
                    onClick={() => void handleReindexBook(book.id)}
                  >
                    {bookActionBusy === "reindex" ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <Database size={14} />
                    )}
                    ایندکس مجدد RAG
                  </button>
                  <button
                    type="button"
                    className="outline-button"
                    disabled={bookActionBusy !== null || book.status === "ingesting"}
                    onClick={() => void handleReprocessBook(book.id)}
                  >
                    {bookActionBusy === "reprocess" ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                    پردازش مجدد PDF
                  </button>
                  <button
                    type="button"
                    className="outline-button danger"
                    disabled={bookActionBusy !== null}
                    onClick={() => {
                      setDeleteBookConfirm((prev) => (prev === "none" ? "confirm" : "none"));
                      setDeleteConflictDetail("");
                    }}
                  >
                    <Trash2 size={14} /> حذف کتاب
                  </button>
                </div>

                {editingBookMeta && (
                  <form className="admin-book-meta-editor" onSubmit={handleSaveBookMeta}>
                    <label className="form-field">
                      <span>عنوان جدید کتاب</span>
                      <input
                        value={editBookTitle}
                        onChange={(e) => setEditBookTitle(e.target.value)}
                        required
                      />
                    </label>
                    <div className="form-row">
                      <label className="form-field">
                        <span>پایه</span>
                        <select
                          value={editBookGrade}
                          onChange={(e) => setEditBookGrade(Number(e.target.value))}
                        >
                          {Array.from({ length: 12 }, (_, idx) => idx + 1).map((n) => (
                            <option key={n} value={n}>
                              {n === 12 ? "دوازدهم" : `پایهٔ ${n}`}
                            </option>
                          ))}
                        </select>
                      </label>
                      {editBookGrade >= 10 && (
                        <label className="form-field">
                          <span>رشته</span>
                          <select
                            value={editBookMajor}
                            onChange={(e) => setEditBookMajor(e.target.value)}
                          >
                            {fieldOptions.map((field) => (
                              <option key={field.code} value={field.code}>
                                {field.branch_title} — {field.title}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    </div>
                    <div className="report-head-actions">
                      <button
                        type="button"
                        className="outline-button"
                        onClick={() => setEditingBookMeta(false)}
                      >
                        انصراف
                      </button>
                      <button
                        type="submit"
                        className="primary-button"
                        disabled={bookActionBusy === "meta"}
                      >
                        {bookActionBusy === "meta" ? (
                          <LoaderCircle className="spin" size={14} />
                        ) : (
                          <Save size={14} />
                        )}
                        ذخیره مشخصات
                      </button>
                    </div>
                  </form>
                )}

                {deleteBookConfirm !== "none" && (
                  <div className="admin-delete-confirm-box">
                    <p>
                      {deleteBookConfirm === "force"
                        ? deleteConflictDetail
                        : `آیا از حذف کامل کتاب «${book.title}» و تمام صفحه‌های آن مطمئن هستید؟ این عمل غیرقابل بازگشت است.`}
                    </p>
                    <div className="report-head-actions">
                      <button
                        type="button"
                        className="outline-button"
                        onClick={() => {
                          setDeleteBookConfirm("none");
                          setDeleteConflictDetail("");
                        }}
                      >
                        لغو
                      </button>
                      <button
                        type="button"
                        className="admin-logout-btn"
                        disabled={bookActionBusy === "delete"}
                        onClick={() => void handleDeleteBook(book.id, deleteBookConfirm === "force")}
                      >
                        {bookActionBusy === "delete" ? (
                          <LoaderCircle className="spin" size={14} />
                        ) : (
                          <Trash2 size={14} />
                        )}
                        {deleteBookConfirm === "force" ? "تأیید حذف کامل همراه با سوابق" : "تأیید حذف کتاب"}
                      </button>
                    </div>
                  </div>
                )}

                {bookActionMessage && (
                  <div className="success-note" style={{ marginTop: 10 }}>
                    <CheckCircle2 size={15} />
                    {bookActionMessage}
                  </div>
                )}
                {bookActionError && (
                  <div className="inline-error" style={{ marginTop: 10 }}>
                    {bookActionError}
                  </div>
                )}
              </div>
            )}
            <div className="review-tip">
              <Sparkles size={15} />
              <span>صفحه‌های نیازمند بازبینی را پیش از ایندکس و استفادهٔ آموزشی اصلاح و تأیید کن.</span>
            </div>
          </section>
        </div>

        {book && book.status !== "ingesting" && (
          <section className="admin-card review-panel">
            <div className="card-heading">
              <div>
                <h2>بازبینی و ویرایش دستی صفحه‌ها</h2>
                <p>تصویر صفحهٔ واقعی PDF یا محتوای منبع ساختاریافته را با متن و مشخصات فصل مقایسه کن و پس از اصلاح، صفحه را تأیید کن.</p>
              </div>
              <span className="step-badge">۳</span>
            </div>

            {pagesLoading ? (
              <div className="review-loading surface-loading">
                <LoaderCircle className="spin" size={18} />
                <span>در حال دریافت صفحه‌های کتاب...</span>
              </div>
            ) : pages.length === 0 ? (
              <div className="review-empty surface-empty">صفحه‌ای برای این کتاب ثبت نشده است.</div>
            ) : (
              <>
                <div className="page-tabs" role="tablist" aria-label="صفحه‌های کتاب">
                  {pages.map((item) => (
                    <button
                      key={item.pdf_page_index}
                      type="button"
                      className={`page-tab ${item.status} ${selectedIdx === item.pdf_page_index ? "active" : ""}`}
                      onClick={() => {
                        selectPageForEdit(item);
                        setSaveMessage("");
                      }}
                    >
                      <i />
                      <span>{item.image_url ? "PDF" : "صفحه"} {item.pdf_page_index}</span>
                      {item.printed_page_number !== null && <small>(چاپی {item.printed_page_number})</small>}
                    </button>
                  ))}
                </div>

                {selectedPage && (
                  <div className="review-grid">
                    <div className="review-image-box">
                      <div className="review-image-head">
                        <span>
                          {selectedPage.image_url
                            ? `تصویر رندرشده (صفحهٔ PDF ${selectedPage.pdf_page_index})`
                            : `منبع متنی/ساختاریافته (بخش ${selectedPage.pdf_page_index})`}
                        </span>
                        <span className={`badge-pill ${selectedPage.status}`}>
                          {statusLabel[selectedPage.status] ?? selectedPage.status}
                          {selectedPage.edited_by_human ? " · ویرایش انسانی" : ""}
                        </span>
                      </div>
                      <div className="review-image-frame">
                        {!selectedPage.image_url ? (
                          <div className="review-image-missing">
                            <FileText size={20} />
                            <span>منبع بدون تصویر PDF ({selectedPage.extraction_model ?? "structured"})</span>
                          </div>
                        ) : imageError ? (
                          <div className="review-image-missing">
                            <FileText size={20} />
                            <span>تصویر صفحه در دسترس نیست</span>
                          </div>
                        ) : pageImageSrc ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={pageImageSrc}
                            alt={`صفحه PDF ${selectedPage.pdf_page_index}`}
                            onError={() => setImageError(true)}
                          />
                        ) : (
                          <div className="review-image-missing">
                            <LoaderCircle className="spin" size={18} />
                            <span>در حال بارگذاری تصویر...</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <form className="review-form" onSubmit={handleSavePage}>
                      {selectedPage.warnings.length > 0 && (
                        <div className="review-alerts">
                          <b>هشدارهای پردازش خودکار:</b>
                          <ul>
                            {selectedPage.warnings.map((warning, idx) => (
                              <li key={idx}>{warning}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {selectedPage.error_message && (
                        <div className="inline-error">{selectedPage.error_message}</div>
                      )}

                      <div className="form-row">
                        <label className="form-field">
                          <span className="field-label-with-diff">
                            شمارهٔ صفحهٔ چاپی
                            {diffMarkersEnabled &&
                              editPrintedPage !==
                                (selectedPage.printed_page_number !== null
                                  ? String(selectedPage.printed_page_number)
                                  : "") && <span className="diff-field-badge">~ تغییریافته</span>}
                          </span>
                          <input
                            type="number"
                            min={0}
                            placeholder="خالی = بدون شماره"
                            value={editPrintedPage}
                            onChange={(event) => setEditPrintedPage(event.target.value)}
                          />
                        </label>
                        <label className="form-field">
                          <span className="field-label-with-diff">
                            شمارهٔ فصل
                            {diffMarkersEnabled &&
                              editChapterNumber !==
                                (selectedPage.chapter_number !== null
                                  ? String(selectedPage.chapter_number)
                                  : "") && <span className="diff-field-badge">~ تغییریافته</span>}
                          </span>
                          <input
                            type="number"
                            min={0}
                            placeholder="مثلاً 1"
                            value={editChapterNumber}
                            onChange={(event) => setEditChapterNumber(event.target.value)}
                          />
                        </label>
                      </div>

                      <label className="form-field">
                        <span className="field-label-with-diff">
                          عنوان فصل
                          {diffMarkersEnabled &&
                            editChapterTitle !== (selectedPage.chapter_title ?? "") && (
                              <span className="diff-field-badge">~ تغییریافته</span>
                            )}
                        </span>
                        <input
                          placeholder="مثلاً حرکت بر خط راست"
                          value={editChapterTitle}
                          onChange={(event) => setEditChapterTitle(event.target.value)}
                        />
                      </label>

                      <div className="review-diff-toolbar">
                        <div className="review-diff-status">
                          <GitCompareArrows size={15} />
                          <span>نمای تغییرات متن (Diff Markers)</span>
                          {liveMarkdownDiff.hasChanges ? (
                            <span className="diff-pill-group">
                              <span className="diff-pill added">+{liveMarkdownDiff.addedCount}</span>
                              <span className="diff-pill removed">-{liveMarkdownDiff.removedCount}</span>
                            </span>
                          ) : (
                            <span className="diff-pill neutral">بدون تغییر</span>
                          )}
                        </div>
                        <div className="review-diff-actions">
                          {hasOriginalSnapshot && (
                            <div className="segmented-control" role="group" aria-label="مبنای مقایسه Diff">
                              <button
                                type="button"
                                className={effectiveDiffBaseline === "saved" ? "active" : ""}
                                onClick={() => setDiffBaseline("saved")}
                              >
                                نسخه فعلی
                              </button>
                              <button
                                type="button"
                                className={effectiveDiffBaseline === "original" ? "active" : ""}
                                onClick={() => setDiffBaseline("original")}
                              >
                                استخراج اولیه
                              </button>
                            </div>
                          )}
                          <button
                            type="button"
                            className="outline-button"
                            onClick={() => setShowReviewDiff((prev) => !prev)}
                          >
                            {showReviewDiff ? "بستن Diff" : "نمایش Diff"}
                          </button>
                        </div>
                      </div>

                      <label className="form-field">
                        <span>متن مارک‌داون و LaTeX صفحه</span>
                        <textarea
                          className="review-markdown"
                          rows={12}
                          value={editMarkdown}
                          onChange={(event) => setEditMarkdown(event.target.value)}
                        />
                      </label>

                      {showReviewDiff && (
                        <DiffViewer
                          beforeText={diffBeforeMarkdown}
                          afterText={editMarkdown}
                          diffMarkersEnabled={diffMarkersEnabled}
                          codeFontSize={adminPreferences.appearance.code_font_size}
                          title={
                            effectiveDiffBaseline === "original"
                              ? "مقایسه با نسخه استخراج اولیه"
                              : "تغییرات پیش‌نویس نسبت به نسخه ذخیره‌شده"
                          }
                        />
                      )}

                      {selectedPage.visual_elements.length > 0 && (
                        <div className="review-visuals">
                          <span>اجزای تصویری استخراج‌شده:</span>
                          {selectedPage.visual_elements.map((el, idx) => (
                            <div key={idx} className="review-visual-item">
                              <b>{el.label ?? "شکل"}</b> ({el.type ?? "تصویر"}) — {el.scientific_description}
                            </div>
                          ))}
                        </div>
                      )}

                      {saveError && (
                        <div className="inline-error">
                          {saveError}
                          <button type="button" onClick={() => setSaveError("")}>
                            <XCircle size={15} />
                          </button>
                        </div>
                      )}
                      {saveMessage && (
                        <div className="success-note">
                          <CheckCircle2 size={15} />
                          {saveMessage}
                        </div>
                      )}

                      <button className="primary-button admin-submit" type="submit" disabled={savingPage}>
                        {savingPage ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}
                        ذخیره و تأیید نهایی صفحه
                      </button>
                    </form>
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {previewOpen && book && (
          <section className="preview-panel">
            <div className="preview-head">
              <div>
                <b>پیش‌نمایش کتاب</b>
                <span>تصویر اصلی در کنار متن استخراج‌شده و خروجی KaTeX</span>
              </div>
              <div className="preview-controls">
                {(["all", "needs_review", "done", "failed"] as const).map((statusKey) => {
                  const count =
                    statusKey === "all" ? processedPages : (book.pages[statusKey] ?? 0);
                  if (statusKey !== "all" && count === 0) return null;
                  return (
                    <button
                      key={statusKey}
                      type="button"
                      className={`preview-filter ${previewStatus === statusKey ? "active" : ""}`}
                      onClick={() => setPreviewStatus(statusKey)}
                    >
                      {statusKey === "all" ? "همه" : statusLabel[statusKey]} ({count})
                    </button>
                  );
                })}
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setPreviewOpen(false)}
                  aria-label="بستن پیش‌نمایش"
                >
                  <XCircle size={18} />
                </button>
              </div>
            </div>
            <iframe
              key={`${book.id}-${previewStatus}-${previewVersion}`}
              title="پیش‌نمایش صفحات کتاب"
              srcDoc={previewHtml || "<html><body dir='rtl' style='font-family:sans-serif;padding:24px;color:#667'>در حال بارگذاری پیش‌نمایش...</body></html>"}
            />
          </section>
        )}
        </>
        )}
      </div>
      </div>
    </main>
  );
}

// `useSearchParams` needs a Suspense boundary during static prerendering; the admin
// shell itself is client-only, so a minimal placeholder is enough.
export default function AdminPage() {
  return (
    <Suspense
      fallback={
        <main className="admin-shell" dir="rtl">
          <div className="admin-loading-state surface-loading">در حال بارگذاری پنل مدیریت…</div>
        </main>
      }
    >
      <AdminPageBody />
    </Suspense>
  );
}
