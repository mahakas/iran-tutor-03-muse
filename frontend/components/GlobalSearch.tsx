"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  Clock,
  Crown,
  FileText,
  FolderOpen,
  GraduationCap,
  HelpCircle,
  LoaderCircle,
  MessageSquare,
  Palette,
  Search,
  Sparkles,
  Users,
  X,
} from "lucide-react";

export type SearchItem = {
  id: string;
  category: string;
  title: string;
  subtitle?: string;
  badge?: string;
  icon: "book" | "page" | "user" | "plan" | "chat" | "exam" | "file" | "appearance" | "help" | "nav";
  onSelect: () => void;
};

type GlobalSearchProps = {
  mode: "admin" | "student";
  lang?: "fa" | "en";
  authToken?: string | null;
  authHeaders?: Record<string, string>;
  isAuthenticated?: boolean;
  quickCommands?: SearchItem[];
  // Admin navigation callbacks
  onAdminSelectBook?: (bookId: number, pageIndex?: number) => void;
  onAdminSelectUser?: (userId: string) => void;
  onAdminSelectPlan?: () => void;
  // Student navigation callbacks
  onStudentSelectBook?: (payload: {
    bookId: number;
    gradeNumber: number;
    majorCode: string;
    topicTitle?: string | null;
  }) => void;
  onStudentSelectChat?: (chatId: string) => void;
  onStudentSelectExam?: (examId: string) => void;
  onNavigateRoute?: (href: string) => void;
  onRequestLogin?: () => void;
};

type AdminSearchResponse = {
  books?: Array<{
    id: number;
    title: string;
    grade_number: number;
    grade_title: string;
    major_title?: string | null;
    total_pdf_pages: number;
    status: string;
  }>;
  pages?: Array<{
    book_id: number;
    book_title: string;
    pdf_page_index: number;
    printed_page_number: number | null;
    chapter_number: number | null;
    chapter_title: string | null;
    status: string;
    snippet: string;
  }>;
  users?: Array<{
    id: string;
    phone_number: string;
    full_name: string | null;
    plan_title: string;
    tokens_remaining: number;
    is_active: boolean;
  }>;
  plans?: Array<{
    code: string;
    name: string;
    price_toman: number;
    token_quota: number;
    duration_days: number;
  }>;
};

type StudentSearchResponse = {
  books?: Array<{
    id: number;
    title: string;
    grade_number: number;
    grade_title: string;
    major_code: string;
    major_title?: string | null;
  }>;
  topics?: Array<{
    book_id: number;
    book_title: string;
    grade_number: number;
    major_code: string;
    chapter_number: number | null;
    chapter_title: string | null;
    printed_page_number: number | null;
    pdf_page_index: number;
  }>;
  chats?: Array<{
    id: string;
    title: string;
    mode: string;
    book_id: number;
    book_title: string;
    grade_number: number;
    major_code: string;
  }>;
  exams?: Array<{
    id: string;
    title: string;
    exam_type: string;
    status: string;
    book_id: number;
    book_title: string;
  }>;
  files?: Array<{
    id: string;
    filename: string;
    category: string;
    size_bytes: number;
  }>;
};

const RECENT_STORAGE_PREFIX = "darsyar_recent_search_v1_";

function isTypingElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function renderItemIcon(icon: SearchItem["icon"]) {
  switch (icon) {
    case "book":
      return <BookOpen size={15} />;
    case "page":
      return <FileText size={15} />;
    case "user":
      return <Users size={15} />;
    case "plan":
      return <Crown size={15} />;
    case "chat":
      return <MessageSquare size={15} />;
    case "exam":
      return <GraduationCap size={15} />;
    case "file":
      return <FolderOpen size={15} />;
    case "appearance":
      return <Palette size={15} />;
    case "help":
      return <HelpCircle size={15} />;
    default:
      return <Sparkles size={15} />;
  }
}

export default function GlobalSearch({
  mode,
  lang = "fa",
  authToken,
  authHeaders,
  isAuthenticated = false,
  quickCommands = [],
  onAdminSelectBook,
  onAdminSelectUser,
  onAdminSelectPlan,
  onStudentSelectBook,
  onStudentSelectChat,
  onStudentSelectExam,
  onNavigateRoute,
  onRequestLogin,
}: GlobalSearchProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeCat, setActiveCat] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [remoteItems, setRemoteItems] = useState<SearchItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [recentQueries, setRecentQueries] = useState<string[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const dialogId = useId();
  const listboxId = useId();
  const recentKey = `${RECENT_STORAGE_PREFIX}${mode}`;

  const categories = useMemo(() => {
    if (mode === "admin") {
      return [
        { id: "all", label: "همه" },
        { id: "books", label: "کتاب‌ها" },
        { id: "pages", label: "صفحه‌ها و متن" },
        { id: "users", label: "کاربران" },
        { id: "plans", label: "پلن‌ها" },
        { id: "commands", label: "تنظیمات و ظاهر" },
      ];
    }
    return [
      { id: "all", label: lang === "en" ? "All" : "همه" },
      { id: "books", label: lang === "en" ? "Textbooks" : "کتاب‌ها و درس‌ها" },
      { id: "chats", label: lang === "en" ? "Chats" : "گفت‌وگوها" },
      { id: "exams", label: lang === "en" ? "Exams" : "آزمون‌ها" },
      { id: "files", label: lang === "en" ? "Files" : "فایل‌ها" },
      { id: "commands", label: lang === "en" ? "Navigation" : "تنظیمات و ناوبری" },
    ];
  }, [lang, mode]);

  const loadRecent = useCallback(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.sessionStorage.getItem(recentKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setRecentQueries(parsed.filter((item): item is string => typeof item === "string").slice(0, 5));
        }
      }
    } catch {
      // ignore storage errors
    }
  }, [recentKey]);

  const rememberQuery = useCallback(
    (term: string) => {
      const clean = term.trim();
      if (!clean || typeof window === "undefined") return;
      setRecentQueries((prev) => {
        const next = [clean, ...prev.filter((q) => q !== clean)].slice(0, 5);
        try {
          window.sessionStorage.setItem(recentKey, JSON.stringify(next));
        } catch {
          // ignore storage errors
        }
        return next;
      });
    },
    [recentKey]
  );

  const openModal = useCallback(() => {
    loadRecent();
    setOpen(true);
    setSelectedIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 10);
  }, [loadRecent]);

  const closeModal = useCallback(() => {
    setOpen(false);
    setQuery("");
    setRemoteItems([]);
    setActiveCat("all");
    setSelectedIndex(0);
  }, []);

  // Global keyboard shortcuts: `/` outside inputs OR `Ctrl+/` / `Cmd+/` anywhere
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "/") {
        event.preventDefault();
        if (open) closeModal();
        else openModal();
        return;
      }
      if (!open && event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !isTypingElement(event.target)) {
        event.preventDefault();
        openModal();
        return;
      }
      if (open && event.key === "Escape") {
        event.preventDefault();
        closeModal();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeModal, open, openModal]);

  // Debounced hybrid API search (runs both on open with empty query to populate tabs, and on typing)
  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();

    const controller = new AbortController();
    const delayMs = trimmed ? 170 : 0;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        if (mode === "admin") {
          const headers: Record<string, string> = { ...(authHeaders ?? {}) };
          if (authToken) {
            headers.Authorization = `Bearer ${authToken}`;
            headers["X-Admin-Token"] = authToken;
          }
          const res = await fetch(
            `/api/v1/admin/search?q=${encodeURIComponent(trimmed)}&limit=12`,
            { cache: "no-store", credentials: "same-origin", headers, signal: controller.signal }
          );
          if (!res.ok) {
            setRemoteItems([]);
            return;
          }
          const data = (await res.json()) as AdminSearchResponse;
          const items: SearchItem[] = [];
          for (const b of data.books ?? []) {
            items.push({
              id: `admin-book-${b.id}`,
              category: "books",
              title: b.title,
              subtitle: `${b.grade_title}${b.major_title ? ` · ${b.major_title}` : ""} · ${b.total_pdf_pages} صفحه`,
              badge: b.status === "ready" ? "آماده" : b.status,
              icon: "book",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onAdminSelectBook?.(b.id);
                closeModal();
              },
            });
          }
          for (const p of data.pages ?? []) {
            items.push({
              id: `admin-page-${p.book_id}-${p.pdf_page_index}`,
              category: "pages",
              title: `${p.book_title} · صفحه ${p.pdf_page_index}${p.chapter_title ? ` (${p.chapter_title})` : ""}`,
              subtitle: p.snippet || (p.printed_page_number ? `صفحه چاپی ${p.printed_page_number}` : ""),
              badge: p.status === "done" ? "تأییدشده" : p.status === "needs_review" ? "بازبینی" : p.status,
              icon: "page",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onAdminSelectBook?.(p.book_id, p.pdf_page_index);
                closeModal();
              },
            });
          }
          for (const u of data.users ?? []) {
            items.push({
              id: `admin-user-${u.id}`,
              category: "users",
              title: `${u.full_name || "کاربر بدون نام"} (${u.phone_number})`,
              subtitle: `پلن: ${u.plan_title} · باقی‌مانده: ${u.tokens_remaining.toLocaleString("fa-IR")} توکن`,
              badge: u.is_active ? "فعال" : "مسدود",
              icon: "user",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onAdminSelectUser?.(u.id);
                closeModal();
              },
            });
          }
          for (const pl of data.plans ?? []) {
            items.push({
              id: `admin-plan-${pl.code}`,
              category: "plans",
              title: `پلن ${pl.name} (${pl.code})`,
              subtitle: `${pl.price_toman.toLocaleString("fa-IR")} تومان · ${pl.token_quota.toLocaleString("fa-IR")} توکن`,
              badge: `${pl.duration_days} روز`,
              icon: "plan",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onAdminSelectPlan?.();
                closeModal();
              },
            });
          }
          setRemoteItems(items);
        } else {
          const endpoint = isAuthenticated
            ? `/api/v1/account/search?q=${encodeURIComponent(trimmed)}&limit=12`
            : `/api/v1/curriculum/search?q=${encodeURIComponent(trimmed)}&limit=12`;
          const headers: Record<string, string> = { ...(authHeaders ?? {}) };
          if (isAuthenticated && authToken) {
            headers.Authorization = `Bearer ${authToken}`;
            headers["X-User-Token"] = authToken;
          }
          const res = await fetch(endpoint, {
            cache: "no-store",
            credentials: "same-origin",
            headers,
            signal: controller.signal,
          });
          if (!res.ok) {
            setRemoteItems([]);
            return;
          }
          const data = (await res.json()) as StudentSearchResponse;
          const items: SearchItem[] = [];
          for (const b of data.books ?? []) {
            items.push({
              id: `st-book-${b.id}`,
              category: "books",
              title: b.title,
              subtitle: `${b.grade_title}${b.major_title ? ` · ${b.major_title}` : ""}`,
              badge: lang === "en" ? "Book" : "کتاب درسی",
              icon: "book",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onStudentSelectBook?.({
                  bookId: b.id,
                  gradeNumber: b.grade_number,
                  majorCode: b.major_code === "general" ? "" : b.major_code,
                });
                closeModal();
              },
            });
          }
          for (const t of data.topics ?? []) {
            const topicLabel = t.chapter_title
              ? `${t.chapter_title} — ${t.book_title}`
              : `${t.book_title} · صفحه ${t.printed_page_number ?? t.pdf_page_index}`;
            items.push({
              id: `st-topic-${t.book_id}-${t.pdf_page_index}`,
              category: "books",
              title: topicLabel,
              subtitle: t.printed_page_number
                ? `${lang === "en" ? "Printed page" : "صفحه چاپی"} ${t.printed_page_number}`
                : t.book_title,
              badge: lang === "en" ? "Topic" : "درس / مبحث",
              icon: "page",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onStudentSelectBook?.({
                  bookId: t.book_id,
                  gradeNumber: t.grade_number,
                  majorCode: t.major_code === "general" ? "" : t.major_code,
                  topicTitle: t.chapter_title || topicLabel,
                });
                closeModal();
              },
            });
          }
          for (const c of data.chats ?? []) {
            items.push({
              id: `st-chat-${c.id}`,
              category: "chats",
              title: c.title,
              subtitle: c.book_title,
              badge: lang === "en" ? "Chat" : "گفت‌وگو",
              icon: "chat",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onStudentSelectChat?.(c.id);
                closeModal();
              },
            });
          }
          for (const ex of data.exams ?? []) {
            items.push({
              id: `st-exam-${ex.id}`,
              category: "exams",
              title: ex.title,
              subtitle: ex.book_title,
              badge:
                ex.status === "submitted"
                  ? lang === "en"
                    ? "Submitted"
                    : "تکمیل‌شده"
                  : lang === "en"
                  ? "Exam"
                  : "آزمون",
              icon: "exam",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onStudentSelectExam?.(ex.id);
                closeModal();
              },
            });
          }
          for (const f of data.files ?? []) {
            items.push({
              id: `st-file-${f.id}`,
              category: "files",
              title: f.filename,
              subtitle: `${Math.max(1, Math.round(f.size_bytes / 1024))} KB`,
              badge: f.category,
              icon: "file",
              onSelect: () => {
                if (trimmed) rememberQuery(trimmed);
                onNavigateRoute?.(`/account/settings/storage?q=${encodeURIComponent(f.filename)}`);
                closeModal();
              },
            });
          }
          setRemoteItems(items);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setRemoteItems([]);
      } finally {
        setLoading(false);
      }
    }, delayMs);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    authHeaders,
    authToken,
    closeModal,
    isAuthenticated,
    lang,
    mode,
    onAdminSelectBook,
    onAdminSelectPlan,
    onAdminSelectUser,
    onNavigateRoute,
    onStudentSelectBook,
    onStudentSelectChat,
    onStudentSelectExam,
    open,
    query,
    rememberQuery,
  ]);

  const localFiltered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return quickCommands.filter((item) => {
      if (!q) return true;
      return `${item.title} ${item.subtitle ?? ""} ${item.badge ?? ""}`.toLowerCase().includes(q);
    });
  }, [query, quickCommands]);

  const guestAuthCommands = useMemo<SearchItem[]>(() => {
    if (mode !== "student" || isAuthenticated || !onRequestLogin) return [];
    return [
      {
        id: "guest-login-chats",
        category: "chats",
        title: lang === "en" ? "Sign in to view saved chats" : "ورود پیامکی برای مشاهدهٔ گفت‌وگوهای ذخیره‌شده",
        subtitle: lang === "en" ? "Access all past tutor conversations" : "دسترسی به آرشیو گفت‌وگوها با شماره موبایل",
        badge: lang === "en" ? "Sign in" : "ورود",
        icon: "chat",
        onSelect: () => {
          closeModal();
          onRequestLogin();
        },
      },
      {
        id: "guest-login-exams",
        category: "exams",
        title: lang === "en" ? "Sign in to view or create exams" : "ورود پیامکی برای مشاهده و ساخت آزمون‌ها",
        subtitle: lang === "en" ? "Create timed exams & view reports" : "ساخت آزمون زمان‌دار و مشاهدهٔ کارنامه",
        badge: lang === "en" ? "Sign in" : "ورود",
        icon: "exam",
        onSelect: () => {
          closeModal();
          onRequestLogin();
        },
      },
      {
        id: "guest-login-files",
        category: "files",
        title: lang === "en" ? "Sign in to access uploaded files" : "ورود پیامکی برای دسترسی به فایل‌ها و پیوست‌ها",
        subtitle: lang === "en" ? "Manage images, audio, and personal files" : "مشاهدهٔ تصاویر، صداها و فایل‌های ذخیره‌شده",
        badge: lang === "en" ? "Sign in" : "ورود",
        icon: "file",
        onSelect: () => {
          closeModal();
          onRequestLogin();
        },
      },
    ];
  }, [closeModal, isAuthenticated, lang, mode, onRequestLogin]);

  const allAvailableItems = useMemo(
    () => [...remoteItems, ...localFiltered, ...guestAuthCommands],
    [guestAuthCommands, localFiltered, remoteItems]
  );

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: allAvailableItems.length };
    for (const item of allAvailableItems) {
      counts[item.category] = (counts[item.category] ?? 0) + 1;
    }
    return counts;
  }, [allAvailableItems]);

  const combinedItems = useMemo(() => {
    if (activeCat === "all") return allAvailableItems;
    return allAvailableItems.filter((item) => item.category === activeCat);
  }, [activeCat, allAvailableItems]);

  const isSearching = loading;

  const clampedIdx = combinedItems.length === 0 ? -1 : Math.min(selectedIndex, combinedItems.length - 1);

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (combinedItems.length > 0) {
        setSelectedIndex((prev) => (prev + 1) % combinedItems.length);
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (combinedItems.length > 0) {
        setSelectedIndex((prev) => (prev - 1 + combinedItems.length) % combinedItems.length);
      }
    } else if (event.key === "Enter" && clampedIdx >= 0 && combinedItems[clampedIdx]) {
      event.preventDefault();
      combinedItems[clampedIdx].onSelect();
    }
  };

  return (
    <>
      <button
        type="button"
        className="global-search-trigger"
        onClick={openModal}
        aria-label={lang === "en" ? "Open global search" : "باز کردن جستجوی سریع"}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={lang === "en" ? "Search (Ctrl + /)" : "جستجوی سریع (Ctrl + /)"}
      >
        <Search size={15} />
        <span className="global-search-placeholder">
          {lang === "en" ? "Quick search..." : "جستجوی سریع..."}
        </span>
        <kbd className="global-search-kbd" dir="ltr">
          /
        </kbd>
      </button>

      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="command-palette-backdrop"
            role="presentation"
            onClick={(event) => {
              if (event.target === event.currentTarget) closeModal();
            }}
          >
            <div
              id={dialogId}
              className="command-palette-dialog"
              role="dialog"
              aria-modal="true"
              aria-label={lang === "en" ? "Quick search and commands" : "جستجو و دسترسی سریع"}
            >
            <div className="command-palette-input-row">
              <Search size={17} className="command-search-icon" />
              <input
                ref={inputRef}
                type="search"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSelectedIndex(0);
                }}
                onKeyDown={handleInputKeyDown}
                placeholder={
                  mode === "admin"
                    ? "جستجو در کتاب‌ها، صفحه‌ها، کاربران، پلن‌ها یا تنظیمات ظاهر..."
                    : lang === "en"
                    ? "Search textbooks, chats, exams, files, or settings..."
                    : "جستجو در کتاب‌ها، مباحث درسی، گفت‌وگوها، آزمون‌ها، فایل‌ها و تنظیمات..."
                }
                aria-controls={listboxId}
                aria-activedescendant={
                  clampedIdx >= 0 && combinedItems[clampedIdx]
                    ? `${listboxId}-opt-${clampedIdx}`
                    : undefined
                }
              />
              {isSearching && <LoaderCircle size={16} className="spin" />}
              <button
                type="button"
                className="icon-button"
                onClick={closeModal}
                aria-label={lang === "en" ? "Close search" : "بستن جستجو"}
              >
                <X size={16} />
              </button>
            </div>

            <div className="command-palette-filters" role="tablist" aria-label="فیلترهای جستجو">
              {categories.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  role="tab"
                  aria-selected={activeCat === cat.id}
                  className={`command-filter-chip ${activeCat === cat.id ? "active" : ""}`}
                  onClick={() => {
                    setActiveCat(cat.id);
                    setSelectedIndex(0);
                  }}
                >
                  <span>{cat.label}</span>
                  {typeof categoryCounts[cat.id] === "number" && (
                    <span className="command-filter-count">{categoryCounts[cat.id]}</span>
                  )}
                </button>
              ))}
            </div>

            {!query.trim() && recentQueries.length > 0 && (
              <div className="command-recent-row">
                <span>
                  <Clock size={12} /> {lang === "en" ? "Recent:" : "جستجوهای اخیر:"}
                </span>
                {recentQueries.map((term) => (
                  <button
                    key={term}
                    type="button"
                    className="command-recent-chip"
                    onClick={() => {
                      setQuery(term);
                      setSelectedIndex(0);
                    }}
                  >
                    {term}
                  </button>
                ))}
              </div>
            )}

            <div id={listboxId} className="command-palette-results" role="listbox">
              {combinedItems.length === 0 ? (
                <div className="command-palette-empty">
                  <Search size={20} />
                  <span>
                    {isSearching
                      ? lang === "en"
                        ? "Searching..."
                        : "در حال جستجو..."
                      : query.trim()
                      ? lang === "en"
                        ? "No matching items found."
                        : "نتیجه‌ای مطابق جستجوی شما یافت نشد."
                      : lang === "en"
                      ? "Type to search..."
                      : "عبارتی را برای جستجو وارد کنید."}
                  </span>
                </div>
              ) : (
                combinedItems.map((item, idx) => (
                  <button
                    key={item.id}
                    id={`${listboxId}-opt-${idx}`}
                    type="button"
                    role="option"
                    aria-selected={clampedIdx === idx}
                    className={`command-result-item ${clampedIdx === idx ? "active" : ""}`}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    onClick={() => item.onSelect()}
                  >
                    <span className="command-result-icon">{renderItemIcon(item.icon)}</span>
                    <span className="command-result-body">
                      <b>{item.title}</b>
                      {item.subtitle && <small>{item.subtitle}</small>}
                    </span>
                    {item.badge && <span className="command-result-badge">{item.badge}</span>}
                  </button>
                ))
              )}
            </div>

            <div className="command-palette-footer">
              <span>
                <kbd dir="ltr">↑ ↓</kbd> {lang === "en" ? "Navigate" : "جابه‌جایی"}
              </span>
              <span>
                <kbd dir="ltr">Enter</kbd> {lang === "en" ? "Open" : "باز کردن"}
              </span>
              <span>
                <kbd dir="ltr">Esc</kbd> {lang === "en" ? "Close" : "بستن"}
              </span>
              <span>
                <kbd dir="ltr">Ctrl + /</kbd> {lang === "en" ? "Shortcut" : "میانبر"}
              </span>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
