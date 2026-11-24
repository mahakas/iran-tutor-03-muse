"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import StudentSideNav from "@/components/StudentSideNav";
import StudentHomeDashboard from "@/components/StudentHomeDashboard";
import AcademicProfileGate from "@/components/AcademicProfileGate";
import { buildNotebookBlockFromMessage } from "@/lib/handoffs";
import { useNavDrawer } from "@/lib/useNavDrawer";
import {
  ArrowUp,
  AudioLines,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Coins,
  Crown,
  FileImage,
  GraduationCap,
  LoaderCircle,
  LogIn,
  Menu,
  Moon,
  Sun,
  MessageSquare,
  Mic,
  NotebookPen,
  Paperclip,
  Phone,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Wand2,
  X,
  Layers,
} from "lucide-react";
import AccountAvatar from "@/components/AccountAvatar";
import AccountMenu from "@/components/AccountMenu";
import { buildUserAuthHeaders, useAppContext } from "@/components/AppProvider";
import ExamRunner from "@/components/ExamRunner";
import GlobalSearch, { type SearchItem } from "@/components/GlobalSearch";
import MathContent from "@/components/MathContent";
import LearningBlockRenderer from "@/components/LearningBlockRenderer";
import { fetchMyCapabilities } from "@/lib/capabilities";
import ThemedSelect from "@/components/ThemedSelect";
import ChatRecycleBin from "@/components/ChatRecycleBin";
import {
  consumeTutorStream,
  startTutorStream,
  stopTutorStream,
  type TutorStreamOutcome,
} from "@/lib/tutorStream";
import { formatDateTime, formatNumber } from "@/lib/i18n";
import type {
  BookOption,
  ChatMessage,
  ChatSessionDetail,
  ChatSessionSummary,
  Exam,
  ExamSummary,
  GradeOption,
  BranchOption,
  FieldOption,
  PublicPlansPayload,
  Source,
  TutorMode,
  TutorResponse,
} from "@/lib/types";

function errorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function sourceText(source: Source, lang: "fa" | "en") {
  const title = source.book_title ?? (lang === "en" ? "Textbook" : "کتاب درسی");
  const bookLabel = source.grade_number
    ? `${title} (${lang === "en" ? "Grade" : "پایه"} ${source.grade_number})`
    : title;
  const scopeLabels = [
    ...(source.branch_titles ?? []),
    ...(source.field_titles ?? []),
  ];
  const scopeLabel = scopeLabels.length
    ? `${lang === "en" ? "Scope" : "شاخه/رشته"}: ${scopeLabels.join(lang === "en" ? ", " : "، ")}`
    : null;
  const editionLabels = [
    source.academic_year_code
      ? `${lang === "en" ? "Academic year" : "سال تحصیلی"} ${source.academic_year_code}`
      : null,
    source.edition_label,
    source.print_year
      ? `${lang === "en" ? "Print" : "چاپ"} ${source.print_year}`
      : null,
    source.publisher
      ? `${lang === "en" ? "Publisher" : "ناشر"}: ${source.publisher}`
      : null,
  ].filter(Boolean);
  const editionLabel = editionLabels.length ? editionLabels.join(" · ") : null;
  const chapterLabel =
    source.chapter_number != null && source.chapter_title
      ? `${lang === "en" ? "Ch." : "فصل"} ${source.chapter_number}: ${source.chapter_title}`
      : source.chapter_number != null
        ? `${lang === "en" ? "Ch." : "فصل"} ${source.chapter_number}`
        : source.chapter_title ?? null;
  const pageLabel =
    source.printed_page_number != null
      ? `${lang === "en" ? "Page" : "صفحه"} ${source.printed_page_number}`
      : source.pdf_page_index != null
        ? `${lang === "en" ? "PDF page" : "صفحه PDF"} ${source.pdf_page_index}`
        : null;
  return [bookLabel, scopeLabel, editionLabel, chapterLabel, pageLabel]
    .filter(Boolean)
    .join(lang === "en" ? " · " : "، ");
}

function uniqueSourceTexts(sources: Source[], lang: "fa" | "en") {
  return Array.from(new Set(sources.map((source) => sourceText(source, lang))));
}

function makeChatTitle(text: string, lang: "fa" | "en") {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return lang === "en" ? "Tutor Conversation" : "گفت‌وگو با معلم";
  return clean.length > 44 ? `${clean.slice(0, 44)}…` : clean;
}

export default function StudentApp() {
  const router = useRouter();
  const {
    user: currentUser,
    token: userTokenState,
    authReady,
    preferences,
    getActiveToken,
    setUser: setCurrentUser,
    refreshAccount,
    authFetch,
    openLoginModal,
    updatePreferences,
  } = useAppContext();

  const lang = preferences.general.language === "en" ? "en" : "fa";
  const [isThemeDark, setIsThemeDark] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsThemeDark(root.getAttribute("data-theme") === "dark");
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  const tz = preferences.general.timezone || "Asia/Tehran";

  const [grades, setGrades] = useState<GradeOption[]>([]);
  const [branches, setBranches] = useState<BranchOption[]>([]);
  const [fields, setFields] = useState<FieldOption[]>([]);
  const [books, setBooks] = useState<BookOption[]>([]);
  const [gradeNumber, setGradeNumber] = useState<number | null>(null);
  const [branchCode, setBranchCode] = useState("");
  // Legacy request field retained; the API now interprets it as field_of_study.code.
  const [majorCode, setMajorCode] = useState("");
  const [bookId, setBookId] = useState("");
  const [curriculumError, setCurriculumError] = useState("");
  const [demoMode, setDemoMode] = useState(false);
  const [plansPayload, setPlansPayload] = useState<PublicPlansPayload | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatSessionSummary[]>([]);
  const [examHistory, setExamHistory] = useState<ExamSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [messageError, setMessageError] = useState("");
  const [tutoringMode, setTutoringMode] = useState<TutorMode>(
    preferences.general.default_tutor_mode || "tutor"
  );
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const sidebarCloseRef = useRef<HTMLButtonElement | null>(null);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);
  // Mobile drawer behaviour: Escape closes, focus moves in/out, body scroll locks
  // only while the drawer actually overlays the page (below 768px).
  useNavDrawer({ open: sidebarOpen, onClose: closeSidebar, focusRef: sidebarCloseRef });
  // Phase 4: Auto-Mode router, multi-grade filter, streaming, chat search / bin.
  const [autoMode, setAutoMode] = useState(false);
  const [multiGrades, setMultiGrades] = useState<number[]>([]);
  const selectGradeNumber = useCallback((nextGrade: number | null) => {
    setGradeNumber(nextGrade);
    setMultiGrades((previous) =>
      nextGrade === null ? [] : previous.filter((grade) => grade <= nextGrade)
    );
  }, []);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [chatBinTab, setChatBinTab] = useState<"search" | "bin" | null>(null);
  // Capability Registry (Phase 2): null = registry unreachable -> keep the legacy menu.
  const [enabledCapabilities, setEnabledCapabilities] = useState<Set<string> | null>(null);
  const [examSetupOpen, setExamSetupOpen] = useState(false);
  const [examHistoryOpen, setExamHistoryOpen] = useState(false);
  const [examType, setExamType] = useState<"konkoor" | "final">("konkoor");
  const [questionCount, setQuestionCount] = useState(5);
  const [timeLimit, setTimeLimit] = useState(15);
  const [activeExam, setActiveExam] = useState<Exam | null>(null);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunks = useRef<BlobPart[]>([]);
  const appliedDefaultModeRef = useRef(false);

  const selectedBook = books.find((book) => String(book.id) === bookId);
  const currentGrade = grades.find((grade) => grade.number === gradeNumber);
  const isUpperSecondary = gradeNumber !== null && gradeNumber >= 10;
  const hasMajor = Boolean(majorCode);
  const branchRequiresField = isUpperSecondary && (branchCode === "theoretical" || fields.length > 0);
  const canAsk = Boolean(bookId && !busy);

  useEffect(() => {
    if (!appliedDefaultModeRef.current && preferences.general.default_tutor_mode && messages.length === 0) {
      setTutoringMode(preferences.general.default_tutor_mode);
      appliedDefaultModeRef.current = true;
    }
  }, [messages.length, preferences.general.default_tutor_mode]);

  const loadChatHistory = useCallback(
    async (tokenOverride?: string | null) => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      if (!token && !currentUser) return;
      try {
        const response = await fetch("/api/v1/tutor/sessions", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildUserAuthHeaders(token),
        });
        if (!response.ok) return;
        const items = (await response.json()) as ChatSessionSummary[];
        setChatHistory(items);
      } catch {
        // Ignore silent history fetch failure
      }
    },
    [currentUser, getActiveToken]
  );

  const loadExamHistory = useCallback(
    async (tokenOverride?: string | null) => {
      const token = tokenOverride !== undefined ? tokenOverride : getActiveToken();
      if (!token && !currentUser) return;
      try {
        const response = await fetch("/api/v1/exams", {
          cache: "no-store",
          credentials: "same-origin",
          headers: buildUserAuthHeaders(token),
        });
        if (!response.ok) return;
        const items = (await response.json()) as ExamSummary[];
        setExamHistory(items);
      } catch {
        // Ignore silent history fetch failure
      }
    },
    [currentUser, getActiveToken]
  );

  // Load curriculum, status, and public plans once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [gradeResponse, branchResponse] = await Promise.all([
          fetch("/api/v1/curriculum/grades"),
          fetch("/api/v1/curriculum/branches?grade_number=12"),
        ]);
        if (!gradeResponse.ok || !branchResponse.ok) {
          throw new Error(
            lang === "en"
              ? "Curriculum catalog is unavailable"
              : "کتابخانهٔ آموزشی در دسترس نیست"
          );
        }
        const gradeData = (await gradeResponse.json()) as GradeOption[];
        const branchData = (await branchResponse.json()) as BranchOption[];
        if (cancelled) return;
        setGrades(gradeData);
        setBranches(branchData);
        selectGradeNumber(
          gradeData.find((item) => item.number === 12)?.number ?? gradeData[0]?.number ?? null
        );
        setBranchCode(branchData.find((item) => item.code === "theoretical")?.code ?? branchData[0]?.code ?? "");
      } catch (error) {
        if (!cancelled) {
          setCurriculumError(
            error instanceof Error
              ? error.message
              : lang === "en"
              ? "Failed to load curriculum"
              : "خطا در دریافت فهرست کتاب‌ها"
          );
        }
      }
    })();

    fetch("/api/v1/system/status")
      .then((response) => (response.ok ? response.json() : null))
      .then((status: { mode?: string } | null) => {
        if (!cancelled) setDemoMode(status?.mode === "demo");
      })
      .catch(() => {
        if (!cancelled) setDemoMode(false);
      });

    fetch("/api/v1/plans", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((plansData: PublicPlansPayload | null) => {
        if (!cancelled && plansData) setPlansPayload(plansData);
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [lang, selectGradeNumber]);

  const currentUserId = currentUser?.id ?? null;

  // Sync chat & exam history when authenticated user changes
  useEffect(() => {
    if (!currentUserId) return;
    let active = true;
    const token = getActiveToken();
    void (async () => {
      if (!active) return;
      await Promise.all([loadChatHistory(token), loadExamHistory(token)]);
    })();
    return () => {
      active = false;
    };
  }, [currentUserId, getActiveToken, loadChatHistory, loadExamHistory]);

  // Redirect payment callback query params to /account/upgrade if user lands on / with Authority
  useEffect(() => {
    if (!currentUser || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("Authority")) {
      router.replace(`/account/upgrade${window.location.search}`);
    }
  }, [currentUser, router]);

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | null = null;
    void (async () => {
      // Defer one microtask: effects run after paint and microtasks run before the next
      // paint, so the reset+fetch sequence is unchanged — it is just not synchronous
      // inside the effect (React 19 cascading-render rule).
      await Promise.resolve();
      if (cancelled || !gradeNumber) return;
      if (isUpperSecondary && (!branchCode || (branchRequiresField && !majorCode))) {
        setBooks([]);
        setBookId("");
        return;
      }
      controller = new AbortController();
      const query = new URLSearchParams({ grade_number: String(gradeNumber) });
      if (isUpperSecondary) {
        query.set("branch_code", branchCode);
        if (majorCode) query.set("field_code", majorCode);
      }
      try {
        const response = await fetch(`/api/v1/curriculum/books?${query.toString()}`, {
          signal: controller.signal,
        });
        const payload = await response.json();
        if (cancelled) return;
        if (!response.ok) {
          throw new Error(
            errorMessage(
              payload,
              lang === "en" ? "No books found for this selection" : "کتابی برای این انتخاب پیدا نشد"
            )
          );
        }
        setBooks(payload as BookOption[]);
        setCurriculumError("");
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setCurriculumError(
          error instanceof Error
            ? error.message
            : lang === "en"
            ? "Failed to load books"
            : "خطا در دریافت کتاب‌ها"
        );
      }
    })();
    return () => {
      cancelled = true;
      controller?.abort();
    };
  }, [gradeNumber, branchCode, majorCode, isUpperSecondary, branchRequiresField, lang]);

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | null = null;
    void (async () => {
      await Promise.resolve();
      if (cancelled || !isUpperSecondary || !branchCode) {
        if (!cancelled) setFields([]);
        return;
      }
      controller = new AbortController();
      try {
        const response = await fetch(
          `/api/v1/curriculum/fields?branch_code=${encodeURIComponent(branchCode)}`,
          {
            signal: controller.signal,
            cache: "no-store",
          }
        );
        if (!response.ok) throw new Error("field catalogue unavailable");
        if (cancelled) return;
        setFields((await response.json()) as FieldOption[]);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFields([]);
      }
    })();
    return () => {
      cancelled = true;
      controller?.abort();
    };
  }, [branchCode, isUpperSecondary]);

  const clearAttachments = useCallback(() => {
    setImageFile(null);
    setAudioFile(null);
    if (imageInputRef.current) imageInputRef.current.value = "";
  }, []);

  const resetChat = useCallback(() => {
    setMessages([]);
    setActiveChatId(null);
    setDraft("");
    setMessageError("");
    clearAttachments();
    setSidebarOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [clearAttachments]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        resetChat();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [resetChat]);

  useEffect(() => {
    if (!messages.length && !busy) return;
    document.getElementById("message-end")?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  const [flashcardBusyId, setFlashcardBusyId] = useState<string | null>(null);
  const [flashcardNotice, setFlashcardNotice] = useState<{ text: string; deckId: number | null } | null>(null);

  // Server resolves the message text and citations from the saved chat session; the client sends only ids.
  const convertMessageToFlashcards = useCallback(
    async (message: ChatMessage) => {
      if (!activeChatId) return;
      setFlashcardBusyId(message.id);
      setFlashcardNotice(null);
      try {
        const response = await authFetch("/api/v1/flashcards/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source: "chat",
            chat_session_id: activeChatId,
            message_ids: [message.id],
            count: 5,
          }),
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          setFlashcardNotice({
            text: errorMessage(
              payload,
              lang === "en" ? "Could not create flashcards" : "ساخت فلش‌کارت ناموفق بود"
            ),
            deckId: null,
          });
          return;
        }
        const created = payload as { deck_id: number; created_count: number };
        setFlashcardNotice({
          text:
            lang === "en"
              ? `${created.created_count} flashcards created from this answer.`
              : `${formatNumber(created.created_count, lang)} فلش‌کارت از این پاسخ ساخته شد.`,
          deckId: created.deck_id,
        });
      } catch {
        setFlashcardNotice({
          text: lang === "en" ? "Could not reach the server" : "ارتباط با سرور برقرار نشد",
          deckId: null,
        });
      } finally {
        setFlashcardBusyId(null);
      }
    },
    [activeChatId, authFetch, lang]
  );

  // Phase 02 handoff: save a tutor answer into the learning notebook of the same
  // book. Provenance (book / chapter / printed page) travels in the block metadata
  // so the source is never lost between tools. Uses only existing APIs:
  // GET/POST /notebooks and POST /notebooks/{id}/blocks.
  const [notebookBusyId, setNotebookBusyId] = useState<string | null>(null);
  const [notebookNotice, setNotebookNotice] = useState<{ text: string; notebookId: number | null } | null>(
    null
  );

  const convertMessageToNotebook = useCallback(
    async (message: ChatMessage) => {
      const book = selectedBook;
      if (!book || notebookBusyId !== null) return; // busy-guard: ignore re-clicks while a save is in flight
      setNotebookBusyId(message.id);
      setNotebookNotice(null);
      try {
        const listResponse = await authFetch("/api/v1/notebooks");
        const listPayload = listResponse.ok ? await listResponse.json().catch(() => null) : null;
        // The endpoint returns {"items": [...]} (same envelope NotebookWorkspace
        // reads); tolerate a bare array defensively so an existing per-book
        // notebook is found instead of duplicated on every handoff.
        const listItems: Array<{ id: number; book_id: number | null }> = Array.isArray(listPayload)
          ? listPayload
          : Array.isArray((listPayload as { items?: unknown } | null)?.items)
            ? ((listPayload as { items: Array<{ id: number; book_id: number | null }> }).items)
            : [];
        let notebook: { id: number } | null =
          listResponse.ok
            ? (listItems.find((nb: { book_id: number | null }) => nb.book_id === book.id) ?? null)
            : null;
        if (!notebook) {
          // dedupe_book=1: the server reuses an existing per-book notebook under
          // a row lock, so parallel handoffs cannot spawn duplicates.
          const createResponse = await authFetch("/api/v1/notebooks?dedupe_book=1", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: lang === "en" ? `Notebook — ${book.title}` : `دفترچهٔ ${book.title}`,
              book_id: book.id,
            }),
          });
          const created = createResponse.ok ? await createResponse.json().catch(() => null) : null;
          if (!createResponse.ok || !created?.id) {
            setNotebookNotice({
              text:
                lang === "en"
                  ? "Could not open a notebook for this book"
                  : "ساخت دفترچه برای این کتاب ناموفق بود",
              notebookId: null,
            });
            return;
          }
          notebook = { id: Number(created.id) };
        }
        // Stable handoff identity: the backend replays the existing block when
        // the same conversation/message is saved again (retry, parallel POST).
        const block = buildNotebookBlockFromMessage(message, book.title ?? "", {
          conversationId: activeChatId,
          messageId: message.id,
        });
        const blockResponse = await authFetch(`/api/v1/notebooks/${notebook.id}/blocks`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(block),
        });
        if (!blockResponse.ok) {
          const errorPayload = await blockResponse.json().catch(() => null);
          setNotebookNotice({
            text: errorMessage(
              errorPayload,
              lang === "en" ? "Could not add to notebook" : "افزودن به دفترچه ناموفق بود"
            ),
            notebookId: null,
          });
          return;
        }
        const savedBlock = (await blockResponse.json().catch(() => null)) as
          | { idempotent_replay?: boolean }
          | null;
        setNotebookNotice({
          text:
            lang === "en"
              ? savedBlock?.idempotent_replay
                ? "Already in this book's notebook."
                : "Saved to this book's notebook."
              : savedBlock?.idempotent_replay
                ? "این پاسخ از قبل در دفترچهٔ این کتاب بود."
                : "به دفترچهٔ این کتاب اضافه شد.",
          notebookId: notebook.id,
        });
      } catch {
        setNotebookNotice({
          text: lang === "en" ? "Could not reach the server" : "ارتباط با سرور برقرار نشد",
          notebookId: null,
        });
      } finally {
        setNotebookBusyId(null);
      }
    },
    [activeChatId, authFetch, lang, notebookBusyId, selectedBook]
  );

  const persistConversation = useCallback(
    async (
      existingSessionId: string | null,
      nextMessages: ChatMessage[],
      firstPrompt: string,
      selectedGrade: number,
      selectedMajor: string | null,
      selectedBookId: number,
      mode: TutorMode
    ) => {
      if (!preferences.privacy.save_chat_history) return existingSessionId;
      const token = getActiveToken();
      if (!token) return existingSessionId;
      try {
        if (existingSessionId) {
          const response = await authFetch(`/api/v1/tutor/sessions/${existingSessionId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode, messages: nextMessages }),
          });
          if (response.ok) {
            await loadChatHistory(token);
            return existingSessionId;
          }
        }
        const response = await authFetch("/api/v1/tutor/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            book_id: selectedBookId,
            grade_number: selectedGrade,
            major_code: selectedMajor,
            mode,
            title: makeChatTitle(firstPrompt, lang),
            messages: nextMessages,
          }),
        });
        if (!response.ok) return existingSessionId;
        const created = (await response.json()) as ChatSessionDetail;
        setActiveChatId(created.id);
        await loadChatHistory(token);
        return created.id;
      } catch {
        return existingSessionId;
      }
    },
    [authFetch, getActiveToken, lang, loadChatHistory, preferences.privacy.save_chat_history]
  );

  /**
   * Phase 4 text turn: streamed answer with Stop and Regenerate.
   * Stop/failure restores `snapshot` exactly, so nothing from the turn is persisted.
   */
  const runTextTurn = useCallback(
    async (args: {
      query: string;
      snapshot: ChatMessage[];
      threadBase: ChatMessage[];
      regenerateOf: string | null;
      restoreDraft: boolean;
    }) => {
      const { query, snapshot, threadBase, regenerateOf, restoreDraft } = args;
      const placeholderId = crypto.randomUUID();
      const en = lang === "en";
      setMessages([...threadBase, { id: placeholderId, role: "assistant", content: "", pending: true }]);
      setMessageError("");
      setBusy(true);
      const useMulti = multiGrades.length > 0;
      const started = await startTutorStream(authFetch, {
        query,
        grade_number: useMulti ? null : gradeNumber,
        major_code: hasMajor ? majorCode : null,
        branch_code: isUpperSecondary ? branchCode : null,
        book_id: Number(bookId),
        grade_numbers: useMulti ? multiGrades : null,
        book_ids: null,
        mode: tutoringMode,
        auto_mode: autoMode,
        chat_session_id: activeChatId,
        regenerate_of: regenerateOf,
      });
      if (!started.ok) {
        setMessages(snapshot);
        if (restoreDraft) setDraft(query);
        if (started.status === 401) {
          openLoginModal(
            en ? "Please sign in again." : "لطفاً دوباره وارد حساب خود شوید."
          );
        } else if (started.status === 402) {
          setMessageError(
            started.detail ||
              (en
                ? "Your token quota is depleted. Visit Upgrade Plan to renew."
                : "اعتبار توکن شما به پایان رسیده است. از بخش ارتقای پلن اعتبار خود را تمدید کنید.")
          );
          void refreshAccount();
        } else {
          setMessageError(
            started.detail || (en ? "No response received. Please try again." : "پاسخی دریافت نشد. دوباره تلاش کن.")
          );
        }
        setBusy(false);
        return;
      }

      setStreamingId(started.streamId);
      let outcome: TutorStreamOutcome;
      try {
        outcome = await consumeTutorStream(authFetch, started.streamId, (chunk) => {
          setMessages((prev) =>
            prev.map((item) => (item.id === placeholderId ? { ...item, content: item.content + chunk } : item))
          );
        });
      } catch {
        outcome = { status: "error", text: "", final: null };
      }
      setStreamingId(null);

      if (outcome.status !== "done" || !outcome.final) {
        setMessages(snapshot);
        if (restoreDraft) setDraft(query);
        if (outcome.status === "error") {
          setMessageError(en ? "The answer was interrupted. Please try again." : "پاسخ قطع شد. دوباره تلاش کن.");
        }
        setBusy(false);
        window.setTimeout(() => inputRef.current?.focus(), 0);
        return;
      }

      const final = outcome.final;
      const turnMode = (final.mode ?? tutoringMode) as TutorMode;
      const assistantMessage: ChatMessage = {
        id: placeholderId,
        role: "assistant",
        content: outcome.text,
        sources: final.sources,
        blocks: final.blocks,
        streamId: started.streamId,
        routedMode: final.router ? turnMode : undefined,
        routerSource: final.router?.source,
      };
      const fullThread = [...threadBase, assistantMessage];
      setMessages(fullThread);
      if (final.usage) {
        const usage = final.usage;
        setCurrentUser((prev) =>
          prev
            ? {
                ...prev,
                tokens_remaining: usage.tokens_remaining,
                tokens_used_total: prev.tokens_used_total + usage.total_tokens,
                tokens_used_today: prev.tokens_used_today + usage.total_tokens,
              }
            : prev
        );
      }
      await persistConversation(
        activeChatId,
        fullThread,
        query,
        gradeNumber as number,
        hasMajor ? majorCode : null,
        Number(bookId),
        turnMode
      );
      setBusy(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    },
    [
      activeChatId,
      authFetch,
      autoMode,
      bookId,
      gradeNumber,
      hasMajor,
      isUpperSecondary,
      branchCode,
      lang,
      majorCode,
      multiGrades,
      openLoginModal,
      persistConversation,
      refreshAccount,
      setCurrentUser,
      tutoringMode,
    ]
  );

  const stopCurrentTurn = useCallback(async () => {
    if (!streamingId) return;
    await stopTutorStream(authFetch, streamingId);
  }, [authFetch, streamingId]);

  const regenerateLastAnswer = useCallback(async () => {
    if (busy) return;
    let index = -1;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "assistant") {
        index = i;
        break;
      }
    }
    if (index < 1 || messages[index - 1].role !== "user") return;
    const question = messages[index - 1];
    if (question.attachment) return; // image/audio turns are not re-sent as text
    await runTextTurn({
      query: question.content,
      snapshot: messages,
      threadBase: messages.slice(0, index),
      regenerateOf: messages[index].streamId ?? null,
      restoreDraft: false,
    });
  }, [busy, messages, runTextTurn]);

  const sendMessage = useCallback(async () => {
    const query = draft.trim();
    if ((!query && !imageFile && !audioFile) || !bookId || gradeNumber === null || busy) return;

    const token = getActiveToken();
    if (!currentUser || !token) {
      openLoginModal(
        lang === "en"
          ? "Sign in with your mobile number to ask the tutor."
          : "برای پرسش از معلم، ابتدا با شماره موبایل خود وارد شوید."
      );
      return;
    }

    if (!imageFile && !audioFile) {
      const questionMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: query };
      setDraft("");
      await runTextTurn({
        query,
        snapshot: messages,
        threadBase: [...messages, questionMessage],
        regenerateOf: null,
        restoreDraft: true,
      });
      return;
    }

    const attachment = imageFile?.name ?? audioFile?.name;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content:
        query ||
        (imageFile
          ? lang === "en"
            ? "Solve this exercise from the attached image."
            : "این سؤال را از روی تصویر حل کن."
          : lang === "en"
          ? "Answer this recorded voice question."
          : "این سؤال را از روی صدا پاسخ بده."),
      attachment,
    };
    const priorMessages = messages;
    const withUser = [...priorMessages, userMessage];
    setMessages(withUser);
    setDraft("");
    setMessageError("");
    setBusy(true);
    try {
      const response = await (imageFile || audioFile
        ? (async () => {
            const form = new FormData();
            form.set(imageFile ? "image" : "audio", imageFile ?? (audioFile as File));
            form.set("grade_number", String(gradeNumber));
            form.set("book_id", bookId);
            form.set("mode", tutoringMode);
            if (hasMajor && majorCode) form.set("major_code", majorCode);
            if (isUpperSecondary && branchCode) form.set("branch_code", branchCode);
            if (activeChatId) form.set("chat_session_id", activeChatId);
            const endpoint = imageFile ? "/api/v1/tutor/ask-image" : "/api/v1/tutor/ask-audio";
            return authFetch(endpoint, { method: "POST", body: form });
          })()
        : authFetch("/api/v1/tutor/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query,
              grade_number: gradeNumber,
              major_code: hasMajor ? majorCode : null,
              branch_code: isUpperSecondary ? branchCode : null,
              book_id: Number(bookId),
              mode: tutoringMode,
            }),
          }));
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401) {
        setMessages(priorMessages);
        openLoginModal(
          errorMessage(
            payload,
            lang === "en" ? "Please sign in again." : "لطفاً دوباره وارد حساب خود شوید."
          )
        );
        return;
      }
      if (response.status === 402) {
        setMessages(priorMessages);
        setMessageError(
          errorMessage(
            payload,
            lang === "en"
              ? "Your token quota is depleted. Visit Upgrade Plan to renew."
              : "اعتبار توکن شما به پایان رسیده است. از بخش ارتقای پلن اعتبار خود را تمدید کنید."
          )
        );
        void refreshAccount();
        return;
      }
      if (!response.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en"
              ? "No response received. Please try again."
              : "پاسخی دریافت نشد. دوباره تلاش کن."
          )
        );
      }

      const result = payload as TutorResponse;
      const detail = result.recognized_question
        ? `${lang === "en" ? "Recognized question:" : "صورت سؤال خوانده‌شده:"} ${result.recognized_question}\n\n${result.answer}`
        : result.transcript
        ? `${lang === "en" ? "Transcript:" : "متن تشخیص‌داده‌شده:"} ${result.transcript}\n\n${result.answer}`
        : result.answer;
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: detail,
        sources: result.sources,
        // Typed blocks describe the plain answer only; prefixed transcripts stay markdown.
        blocks: detail === result.answer ? result.blocks : undefined,
      };
      const fullThread = [...withUser, assistantMessage];
      setMessages(fullThread);
      if (result.usage) {
        setCurrentUser((prev) =>
          prev
            ? {
                ...prev,
                tokens_remaining: result.usage!.tokens_remaining,
                tokens_used_total: prev.tokens_used_total + result.usage!.total_tokens,
                tokens_used_today: prev.tokens_used_today + result.usage!.total_tokens,
              }
            : prev
        );
      }
      if (result.uncertain_parts?.length) {
        setMessageError(
          `${lang === "en" ? "Uncertain parts:" : "بخش‌های نامطمئن تصویر:"} ${result.uncertain_parts.join("، ")}`
        );
      }
      clearAttachments();
      await persistConversation(
        activeChatId,
        fullThread,
        userMessage.content,
        gradeNumber,
        hasMajor ? majorCode : null,
        Number(bookId),
        tutoringMode
      );
    } catch (error) {
      setMessageError(
        error instanceof Error
          ? error.message
          : lang === "en"
          ? "Could not reach tutor service"
          : "ارتباط با معلم برقرار نشد"
      );
    } finally {
      setBusy(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [
    activeChatId,
    audioFile,
    authFetch,
    bookId,
    busy,
    clearAttachments,
    currentUser,
    draft,
    getActiveToken,
    gradeNumber,
    branchCode,
    isUpperSecondary,
    hasMajor,
    imageFile,
    lang,
    majorCode,
    messages,
    openLoginModal,
    persistConversation,
    refreshAccount,
    runTextTurn,
    setCurrentUser,
    tutoringMode,
  ]);

  const openChatSession = useCallback(
    async (sessionId: string) => {
      const token = getActiveToken();
      if (!token) {
        openLoginModal();
        return;
      }
      setMessageError("");
      try {
        const response = await authFetch(`/api/v1/tutor/sessions/${sessionId}`);
        if (!response.ok) {
          throw new Error(lang === "en" ? "Conversation not found" : "گفت‌وگو پیدا نشد");
        }
        const detail = (await response.json()) as ChatSessionDetail;
        selectGradeNumber(detail.grade_number);
        setMajorCode(detail.major_code === "general" ? "" : detail.major_code);
        setBranchCode(detail.branch_code ?? (detail.major_code !== "general" ? "theoretical" : ""));
        setBookId(String(detail.book_id));
        setTutoringMode(detail.mode);
        setMessages(detail.messages ?? []);
        setActiveChatId(detail.id);
        clearAttachments();
        setSidebarOpen(false);
      } catch (error) {
        setMessageError(
          error instanceof Error
            ? error.message
            : lang === "en"
            ? "Could not open chat"
            : "بازکردن گفت‌وگو انجام نشد"
        );
      }
    },
    [authFetch, clearAttachments, getActiveToken, lang, openLoginModal, selectGradeNumber]
  );

  const deleteChatSession = async (sessionId: string) => {
    const token = getActiveToken();
    if (!token) return;
    try {
      const response = await authFetch(`/api/v1/tutor/sessions/${sessionId}`, {
        method: "DELETE",
      });
      if (!response.ok) return;
      setChatHistory((prev) => prev.filter((item) => item.id !== sessionId));
      if (activeChatId === sessionId) {
        resetChat();
      }
    } catch {
      // Ignore silent delete error
    }
  };

  const openExamHistory = useCallback(async () => {
    const token = getActiveToken();
    if (!currentUser || !token) {
      setSidebarOpen(false);
      openLoginModal(
        lang === "en"
          ? "Sign in to view or take timed exams."
          : "برای مشاهده و شرکت در آزمون‌ها، ابتدا وارد شوید."
      );
      return;
    }
    setSidebarOpen(false);
    setExamHistoryOpen(true);
    setHistoryLoading(true);
    await loadExamHistory(token);
    setHistoryLoading(false);
  }, [currentUser, getActiveToken, lang, loadExamHistory, openLoginModal]);

  const openSavedExam = useCallback(
    async (examId: string) => {
      const token = getActiveToken();
      if (!token) {
        openLoginModal();
        return;
      }
      setBusy(true);
      setMessageError("");
      try {
        const response = await authFetch(`/api/v1/exams/${examId}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(
            errorMessage(
              payload,
              lang === "en" ? "Failed to open exam" : "دریافت آزمون انجام نشد"
            )
          );
        }
        setActiveExam(payload as Exam);
        setExamHistoryOpen(false);
      } catch (error) {
        setMessageError(
          error instanceof Error
            ? error.message
            : lang === "en"
            ? "Failed to load exam"
            : "دریافت آزمون انجام نشد"
        );
      } finally {
        setBusy(false);
      }
    },
    [authFetch, getActiveToken, lang, openLoginModal]
  );

  const startRecording = async () => {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    if (!currentUser || !getActiveToken()) {
      openLoginModal(
        lang === "en"
          ? "Sign in to record voice questions."
          : "برای پرسش صوتی، ابتدا با شماره موبایل وارد شوید."
      );
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      audioChunks.current = [];
      const recorder = new MediaRecorder(
        stream,
        MediaRecorder.isTypeSupported("audio/webm") ? { mimeType: "audio/webm" } : undefined
      );
      recorder.ondataavailable = (event) => {
        if (event.data.size) audioChunks.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(audioChunks.current, { type: recorder.mimeType || "audio/webm" });
        setAudioFile(new File([blob], "question.webm", { type: blob.type }));
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      };
      recorderRef.current = recorder;
      recorder.start();
      setImageFile(null);
      setRecording(true);
      setMessageError("");
    } catch {
      setMessageError(
        lang === "en"
          ? "Enable microphone permissions in your browser to record voice."
          : "برای ضبط صدا، دسترسی میکروفون را در مرورگر فعال کن."
      );
    }
  };

  const createExam = async () => {
    if (!bookId || gradeNumber === null) return;
    const token = getActiveToken();
    if (!currentUser || !token) {
      setExamSetupOpen(false);
      openLoginModal(
        lang === "en"
          ? "Sign in to generate a timed exam."
          : "برای ساخت آزمون زمان‌دار، ابتدا وارد حساب خود شوید."
      );
      return;
    }
    setBusy(true);
    setMessageError("");
    try {
      const response = await authFetch("/api/v1/exams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grade_number: gradeNumber,
          major_code: hasMajor ? majorCode : null,
          branch_code: isUpperSecondary ? branchCode : null,
          book_id: Number(bookId),
          question_count: questionCount,
          time_limit_minutes: timeLimit,
          exam_type: examType,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401) {
        setExamSetupOpen(false);
        openLoginModal(
          lang === "en"
            ? "Session expired. Please sign in again."
            : "نشست شما منقضی شده است؛ لطفاً دوباره وارد شوید."
        );
        return;
      }
      if (response.status === 402) {
        setExamSetupOpen(false);
        setMessageError(
          errorMessage(
            payload,
            lang === "en" ? "Insufficient token quota." : "سهمیهٔ توکن شما کافی نیست."
          )
        );
        void refreshAccount();
        return;
      }
      if (!response.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Exam generation failed" : "ساخت آزمون انجام نشد"
          )
        );
      }
      const exam = payload as Exam;
      if (exam.usage) {
        setCurrentUser((prev) =>
          prev
            ? {
                ...prev,
                tokens_remaining: exam.usage!.tokens_remaining,
                tokens_used_total: prev.tokens_used_total + exam.usage!.total_tokens,
              }
            : prev
        );
      }
      setActiveExam(exam);
      setExamSetupOpen(false);
      void loadExamHistory(token);
    } catch (error) {
      setMessageError(
        error instanceof Error
          ? error.message
          : lang === "en"
          ? "Exam generation failed"
          : "ساخت آزمون انجام نشد"
      );
      setExamSetupOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const suggestions = useMemo(
    () =>
      lang === "en"
        ? [
            "Explain linear motion simply based on the textbook",
            "Solve a step-by-step example from this chapter",
            "What does the slope of the position-time graph mean?",
          ]
        : [
            "فصل حرکت بر خط راست را ساده توضیح بده",
            "از این مبحث یک مثال مرحله‌به‌مرحله حل کن",
            "شیب نمودار مکان-زمان چه چیزی را نشان می‌دهد؟",
          ],
    [lang]
  );

  const visibleMessages = useMemo(() => (currentUser ? messages : []), [currentUser, messages]);
  const lastAssistantId = useMemo(() => {
    for (let i = visibleMessages.length - 1; i >= 0; i -= 1) {
      if (visibleMessages[i].role === "assistant") return visibleMessages[i].id;
    }
    return null;
  }, [visibleMessages]);
  const visibleChatHistory = currentUser ? chatHistory : [];
  const visibleExamHistory = currentUser ? examHistory : [];
  const visibleActiveExam = currentUser ? activeExam : null;

  const handledDeepLinkRef = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined" || handledDeepLinkRef.current) return;
    const params = new URLSearchParams(window.location.search);
    const jumpBookId = params.get("bookId");
    const jumpGrade = params.get("grade");
    const jumpMajor = params.get("major");
    const jumpTopic = params.get("topic");
    const jumpChatId = params.get("chatId");
    const jumpExamId = params.get("examId");
    const jumpAction = params.get("action");

    if (jumpBookId && jumpGrade) {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        setActiveExam(null);
        selectGradeNumber(Number(jumpGrade));
        setMajorCode(jumpMajor ?? "");
        setBookId(jumpBookId);
        if (jumpTopic) {
          setDraft(
            lang === "en"
              ? `Explain "${jumpTopic}" from this textbook clearly.`
              : `لطفاً مبحث «${jumpTopic}» از این کتاب را توضیح بده.`
          );
        }
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (jumpChatId && currentUser) {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        setActiveExam(null);
        void openChatSession(jumpChatId);
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (jumpExamId && currentUser) {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        void openSavedExam(jumpExamId);
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (jumpAction === "new-exam") {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        setActiveExam(null);
        setExamSetupOpen(true);
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (jumpAction === "exams" && currentUser) {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        setActiveExam(null);
        void openExamHistory();
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (jumpAction === "new-chat") {
      handledDeepLinkRef.current = true;
      const timer = window.setTimeout(() => {
        setActiveExam(null);
        resetChat();
        router.replace("/");
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [currentUser, lang, openChatSession, openExamHistory, openSavedExam, resetChat, router, selectGradeNumber]);

  useEffect(() => {
    let cancelled = false;
    const token = getActiveToken();
    if (!token && !currentUser) return;
    void fetchMyCapabilities(buildUserAuthHeaders(token)).then((keys) => {
      if (!cancelled) setEnabledCapabilities(keys);
    });
    return () => {
      cancelled = true;
    };
  }, [currentUser, getActiveToken]);

  // Unknown (null) registry state keeps the legacy menu; otherwise honour the flags.
  const capabilityMenuEnabled = useCallback(
    (key: string) => enabledCapabilities === null || enabledCapabilities.has(key),
    [enabledCapabilities]
  );

  const studentQuickCommands = useMemo<SearchItem[]>(
    () => [
      {
        id: "st-cmd-new-chat",
        category: "chats",
        title: lang === "en" ? "Start New Tutor Chat" : "شروع گفت‌وگوی تازه با معلم",
        subtitle: "Ctrl + K",
        badge: lang === "en" ? "New chat" : "گفت‌وگوی تازه",
        icon: "chat",
        onSelect: () => {
          setActiveExam(null);
          resetChat();
        },
      },
      {
        id: "st-cmd-new-exam",
        category: "exams",
        title: lang === "en" ? "Create New Timed Exam" : "ساخت آزمون زمان‌دار جدید",
        subtitle: lang === "en" ? "Generate questions from textbook" : "طراحی آزمون از صفحه‌های تأییدشده کتاب",
        badge: lang === "en" ? "New exam" : "آزمون جدید",
        icon: "exam",
        onSelect: () => {
          setActiveExam(null);
          setExamHistoryOpen(false);
          setExamSetupOpen(true);
        },
      },
      {
        id: "st-cmd-exam-history",
        category: "exams",
        title: lang === "en" ? "My Exam History & Reports" : "آزمون‌های من و کارنامه‌ها",
        subtitle: lang === "en" ? "Open past exams and scorecards" : "مشاهده آزمون‌های قبلی و کارنامه",
        badge: lang === "en" ? "Archive" : "آرشیو",
        icon: "exam",
        onSelect: () => {
          setActiveExam(null);
          void openExamHistory();
        },
      },
      {
        id: "st-cmd-storage",
        category: "files",
        title: lang === "en" ? "Storage & Uploaded Files" : "مدیریت حافظه و فایل‌های شخصی",
        subtitle: lang === "en" ? "Inspect quota and attachments" : "مشاهده فایل‌ها، تصاویر و صوت‌های آپلودشده",
        badge: lang === "en" ? "Storage" : "حافظه",
        icon: "file",
        onSelect: () => router.push("/account/settings/storage"),
      },
      {
        id: "st-cmd-appearance",
        category: "commands",
        title: lang === "en" ? "Appearance & Theme Settings" : "تنظیمات ظاهر، تم و فونت",
        subtitle: lang === "en" ? "Light/Dark mode, colors, contrast" : "حالت روشن/تاریک، رنگ‌ها و کنتراست",
        badge: lang === "en" ? "Settings" : "تنظیمات",
        icon: "appearance",
        onSelect: () => router.push("/account/settings/appearance"),
      },
      {
        id: "st-cmd-upgrade",
        category: "commands",
        title: lang === "en" ? "Plans & Token Balance" : "ارتقای پلن و موجودی توکن",
        subtitle: lang === "en" ? "Compare plans & usage history" : "مقایسه پلن‌ها و گزارش مصرف",
        badge: lang === "en" ? "Billing" : "اشتراک",
        icon: "plan",
        onSelect: () => router.push("/account/upgrade"),
      },
      {
        id: "st-cmd-profile",
        category: "commands",
        title: lang === "en" ? "User Profile & Phone" : "پروفایل کاربری و تغییر شماره",
        subtitle: lang === "en" ? "Name, email, avatar & phone OTP" : "نام، ایمیل، تصویر پروفایل",
        badge: lang === "en" ? "Account" : "حساب",
        icon: "nav",
        onSelect: () => router.push("/account/profile"),
      },
      {
        id: "st-cmd-help",
        category: "commands",
        title: lang === "en" ? "Help & Keyboard Shortcuts" : "راهنما و کلیدهای میانبر",
        subtitle: lang === "en" ? "Documentation and FAQ" : "پرسش‌های متداول و مستندات",
        badge: lang === "en" ? "Help" : "راهنما",
        icon: "help",
        onSelect: () => router.push("/account/help"),
      },
    ],
    [lang, openExamHistory, resetChat, router]
  );

  const examAuthHeaders = useMemo(() => buildUserAuthHeaders(userTokenState), [userTokenState]);

  if (visibleActiveExam) {
    return (
      <ExamRunner
        exam={visibleActiveExam}
        authHeaders={examAuthHeaders}
        onExit={() => {
          setActiveExam(null);
          void loadExamHistory();
          void refreshAccount();
        }}
        onStartNewExam={() => {
          setActiveExam(null);
          void loadExamHistory();
          void refreshAccount();
          setExamSetupOpen(true);
        }}
      />
    );
  }

  return (
    <div className="app-shell" dir={lang === "en" ? "ltr" : "rtl"}>
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">{lang === "en" ? "D" : "د"}</div>
          <div>
            <strong>{lang === "en" ? "Darsyar" : "درسیار"}</strong>
            <span>{lang === "en" ? "AI Textbook Tutor" : "معلم خصوصی هوشمند"}</span>
          </div>
          <button
            className="icon-button mobile-close"
            ref={sidebarCloseRef}
            aria-label={lang === "en" ? "Close menu" : "بستن منو"}
            onClick={closeSidebar}
          >
            <X size={18} />
          </button>
        </div>

        <button className="new-chat-button" onClick={resetChat}>
          <Plus size={18} /> {lang === "en" ? "New Chat" : "گفت‌وگوی تازه"}{" "}
          <span dir="ltr">⌘ K</span>
        </button>

        <StudentSideNav
          lang={lang}
          enabled={{
            chat: capabilityMenuEnabled("chat"),
            quiz: capabilityMenuEnabled("quiz"),
            flashcards: capabilityMenuEnabled("flashcards"),
            mistake_bank: capabilityMenuEnabled("mistake_bank"),
            mastery_path: capabilityMenuEnabled("mastery_path"),
            deep_solve: capabilityMenuEnabled("deep_solve"),
            learning_notebook: capabilityMenuEnabled("learning_notebook"),
            living_book: capabilityMenuEnabled("living_book"),
            audio_podcast: capabilityMenuEnabled("audio_podcast"),
          }}
          isAuthenticated={Boolean(currentUser)}
          examHistoryCount={visibleExamHistory.length}
          onAfterNavigate={closeSidebar}
          onOpenTutor={closeSidebar}
          onOpenExams={() => {
            closeSidebar();
            void openExamHistory();
          }}
          onOpenChatSearch={() => {
            closeSidebar();
            setChatBinTab("search");
          }}
          onOpenChatBin={() => {
            closeSidebar();
            setChatBinTab("bin");
          }}
        />
        <Link
          href="/account/upgrade"
          className="sidebar-item"
          onClick={closeSidebar}
        >
          <Crown size={17} />
          <span>{lang === "en" ? "Plans & Token Balance" : "پلن‌ها و اعتبار توکن"}</span>
        </Link>

        <div className="sidebar-section-label recent-label">
          {lang === "en" ? "Recent Chats" : "گفت‌وگوهای اخیر"}
        </div>
        {!currentUser ? (
          <div className="sidebar-empty">
            {lang === "en" ? (
              <>
                Sign in via SMS to save your
                <br />
                personal study chats here.
              </>
            ) : (
              <>
                پس از ورود پیامکی، گفت‌وگوهای
                <br />
                شخصی‌ات اینجا ذخیره می‌شوند.
              </>
            )}
          </div>
        ) : visibleChatHistory.length > 0 ? (
          <div className="recent-list">
            {visibleChatHistory.map((item) => (
              <div
                key={item.id}
                className={`recent-row ${activeChatId === item.id ? "active" : ""}`}
              >
                <button
                  type="button"
                  className="recent-chat"
                  onClick={() => void openChatSession(item.id)}
                  title={`${item.title}${item.book_title ? ` · ${item.book_title}` : ""}`}
                >
                  <span className="recent-indicator" />
                  <span className="recent-title">{item.title}</span>
                </button>
                <button
                  type="button"
                  className="recent-delete"
                  aria-label={lang === "en" ? "Move chat to Recycle Bin" : "انتقال گفت‌وگو به سطل بازیافت"}
                  onClick={() => void deleteChatSession(item.id)}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="sidebar-empty">
            {lang === "en" ? (
              <>
                Your recent chats will
                <br />
                appear here.
              </>
            ) : (
              <>
                گفت‌وگوهای تازه‌ات اینجا
                <br />
                ذخیره می‌شوند.
              </>
            )}
          </div>
        )}

        <div className="sidebar-spacer" />

        <AccountMenu onNavigate={() => setSidebarOpen(false)} />
      </aside>
      {chatBinTab && currentUser && (
        <ChatRecycleBin
          authFetch={authFetch}
          lang={lang}
          initialTab={chatBinTab}
          onOpenChat={(chatId) => {
            setChatBinTab(null);
            void openChatSession(chatId);
          }}
          onChanged={() => {
            const token = getActiveToken();
            if (token) void loadChatHistory(token);
          }}
          onClose={() => setChatBinTab(null)}
        />
      )}
      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          aria-label={lang === "en" ? "Close menu" : "بستن منو"}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <main className="main-panel">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label={lang === "en" ? "Open menu" : "بازکردن منو"}
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="context-title">
            <span className="online-indicator" />
            <div>
              <b>{selectedBook?.title ?? (lang === "en" ? "Classroom" : "کلاس درس")}</b>
              <span>
                {currentGrade?.title ?? (lang === "en" ? "Select Grade" : "انتخاب پایه")}
                {hasMajor && majorCode
                  ? ` · ${fields.find((field) => field.code === majorCode)?.title ?? ""}`
                  : ""}
              </span>
            </div>
            <ChevronDown size={15} />
          </div>
          <div className="topbar-actions">
            <button
              type="button"
              className="icon-button theme-toggle"
              aria-label={
                lang === "en"
                  ? "Toggle dark mode"
                  : "تغییر حالت نمایش تیره و روشن"
              }
              title={lang === "en" ? "Toggle dark mode" : "حالت تیره / روشن"}
              onClick={() => {
                void updatePreferences({
                  appearance: { color_mode: isThemeDark ? "light" : "dark" },
                });
              }}
            >
              {isThemeDark ? (
                <Sun size={18} />
              ) : (
                <Moon size={18} />
              )}
            </button>
            {demoMode && (
              <span className="private-badge demo-badge">
                <Sparkles size={14} /> {lang === "en" ? "Demo Mode" : "حالت آزمایشی"}
              </span>
            )}
            {currentUser ? (
              <Link
                href="/account/upgrade"
                className={`token-status-pill ${
                  currentUser.is_expired || currentUser.tokens_remaining <= 0 ? "depleted" : ""
                }`}
                title={
                  lang === "en" ? "Manage plans & tokens" : "مشاهده پلن‌ها و مصرف توکن"
                }
              >
                <Coins size={14} />
                <span>
                  {formatNumber(currentUser.tokens_remaining, lang)}{" "}
                  {lang === "en" ? "tokens" : "توکن"}
                </span>
                <small>{currentUser.plan_title}</small>
              </Link>
            ) : authReady ? (
              <button
                type="button"
                className="topbar-login-btn"
                onClick={() => openLoginModal()}
              >
                <LogIn size={14} /> {lang === "en" ? "SMS Login" : "ورود پیامکی"}
              </button>
            ) : null}
            <span className="private-badge">
              <ShieldCheck size={14} /> {lang === "en" ? "Private Space" : "فضای خصوصی"}
            </span>
            <Link
              href="/account/help"
              className="icon-button help-button"
              aria-label={lang === "en" ? "Help" : "راهنما"}
              title={lang === "en" ? "Help & Documentation" : "راهنما و مستندات"}
            >
              <CircleHelp size={18} />
            </Link>
            <GlobalSearch
              mode="student"
              lang={lang}
              authToken={userTokenState}
              isAuthenticated={Boolean(currentUser)}
              quickCommands={studentQuickCommands}
              onStudentSelectBook={({ bookId: nextBookId, gradeNumber: nextGrade, majorCode: nextMajor, topicTitle }) => {
                setActiveExam(null);
                setExamHistoryOpen(false);
                setExamSetupOpen(false);
                selectGradeNumber(nextGrade);
                setBranchCode(nextMajor ? "theoretical" : nextGrade >= 10 ? "theoretical" : "");
                setMajorCode(nextMajor);
                setBookId(String(nextBookId));
                setMessages([]);
                setActiveChatId(null);
                setMessageError("");
                if (topicTitle) {
                  setDraft(
                    lang === "en"
                      ? `Explain "${topicTitle}" from this textbook clearly.`
                      : `لطفاً مبحث «${topicTitle}» از این کتاب را توضیح بده.`
                  );
                }
                window.setTimeout(() => inputRef.current?.focus(), 20);
              }}
              onStudentSelectChat={(chatId) => {
                setActiveExam(null);
                void openChatSession(chatId);
              }}
              onStudentSelectExam={(examId) => void openSavedExam(examId)}
              onNavigateRoute={(href) => router.push(href)}
              onRequestLogin={() => openLoginModal()}
            />
          </div>
        </header>

        {currentUser && (
          <AcademicProfileGate
            onSaved={({ gradeNumber: profileGrade, branchCode: profileBranch, fieldCode: profileField }) => {
              setGradeNumber(profileGrade);
              setBranchCode(profileBranch ?? "");
              setMajorCode(profileField ?? "");
            }}
          />
        )}

        <StudentHomeDashboard
          lang={lang}
          isAuthenticated={Boolean(currentUser)}
          context={{
            gradeTitle: currentGrade?.title,
            majorTitle: majorCode ? fields.find((field) => field.code === majorCode)?.title : undefined,
            bookTitle: selectedBook?.title ?? null,
            bookId: selectedBook?.id ?? null,
          }}
          capabilities={{
            quiz: capabilityMenuEnabled("quiz"),
            flashcards: capabilityMenuEnabled("flashcards"),
            mistake_bank: capabilityMenuEnabled("mistake_bank"),
            learning_notebook: capabilityMenuEnabled("learning_notebook"),
            immersive_reader: capabilityMenuEnabled("immersive_reader"),
          }}
          chatSessions={visibleChatHistory}
          exams={visibleExamHistory}
          onContinueChat={(chatId) => void openChatSession(chatId)}
          onContinueExam={(examId) => void openSavedExam(examId)}
          onStart={() =>
            document.getElementById("today-class")?.scrollIntoView({ behavior: "smooth", block: "start" })
          }
          onRequireLogin={() => openLoginModal()}
        />

        <section className="curriculum-strip" id="today-class">
          <div className="strip-heading">
            <span className="strip-icon">
              <BookOpen size={17} />
            </span>
            <div>
              <b>{lang === "en" ? "Today's Class" : "کلاس امروزت"}</b>
              <span>
                {lang === "en"
                  ? "Pick your textbook so the tutor answers strictly from it."
                  : "کتابت را انتخاب کن تا معلم دقیقاً با همان منبع کمکت کند."}
              </span>
            </div>
          </div>
          <div className="selector-row">
            <ThemedSelect
              label={lang === "en" ? "Grade" : "پایه"}
              value={gradeNumber !== null ? String(gradeNumber) : ""}
              placeholder={lang === "en" ? "Select Grade" : "انتخاب پایه"}
              options={grades.map((grade) => ({
                value: String(grade.number),
                label: grade.title,
              }))}
              onChange={(nextVal) => {
                if (!nextVal) return;
                const nextGrade = Number(nextVal);
                selectGradeNumber(nextGrade);
                setBranchCode(nextGrade >= 10 ? "theoretical" : "");
                setMajorCode("");
                setBooks([]);
                setBookId("");
                setMessages([]);
                setActiveChatId(null);
                setMessageError("");
              }}
            />
            {isUpperSecondary && (
              <ThemedSelect
                label={lang === "en" ? "Branch" : "شاخه"}
                value={branchCode}
                placeholder={lang === "en" ? "Select Branch" : "انتخاب شاخه"}
                emptyOptionLabel={lang === "en" ? "Select Branch" : "انتخاب شاخه"}
                options={branches.map((branch) => ({
                  value: branch.code,
                  label: branch.title,
                }))}
                onChange={(nextVal) => {
                  setBranchCode(nextVal);
                  setMajorCode("");
                  setFields([]);
                  setBooks([]);
                  setBookId("");
                  setMessages([]);
                  setActiveChatId(null);
                  setMessageError("");
                }}
              />
            )}
            {isUpperSecondary && (branchCode === "theoretical" || fields.length > 0) && (
              <ThemedSelect
                label={lang === "en" ? "Field" : "رشته"}
                value={majorCode}
                placeholder={lang === "en" ? "Select Field" : "انتخاب رشته"}
                emptyOptionLabel={lang === "en" ? "Select Field" : "انتخاب رشته"}
                options={fields.map((field) => ({
                  value: field.code,
                  label: field.title,
                }))}
                disabled={!fields.length}
                onChange={(nextVal) => {
                  setMajorCode(nextVal);
                  setBooks([]);
                  setBookId("");
                  setMessages([]);
                  setActiveChatId(null);
                  setMessageError("");
                }}
              />
            )}
            <ThemedSelect
              label={lang === "en" ? "Book" : "کتاب"}
              value={bookId}
              className="book-select"
              placeholder={
                books.length
                  ? lang === "en"
                    ? "Select Textbook"
                    : "انتخاب کتاب"
                  : lang === "en"
                  ? "No textbooks available"
                  : "کتابی در دسترس نیست"
              }
              emptyOptionLabel={
                books.length
                  ? lang === "en"
                    ? "Select Textbook"
                    : "انتخاب کتاب"
                  : undefined
              }
              options={books.map((book) => ({
                value: String(book.id),
                label: [
                  book.title,
                  book.academic_year_code,
                  book.edition_label,
                  book.print_year ? String(book.print_year) : null,
                ].filter(Boolean).join(" — "),
              }))}
              disabled={!books.length}
              onChange={(nextVal) => {
                setBookId(nextVal);
                setMessages([]);
                setActiveChatId(null);
                setMessageError("");
              }}
            />
          </div>
          {selectedBook && capabilityMenuEnabled("immersive_reader") && (
            <Link href={`/study/${selectedBook.id}`} className="home-cta">
              <BookOpen size={16} /> {lang === "en" ? "Study book" : "مطالعهٔ کتاب"}
            </Link>
          )}
          {curriculumError && (
            <div className="notice-error">
              {curriculumError} ·{" "}
              {lang === "en"
                ? "Verify backend & database are running."
                : "مطمئن شو بک‌اند و دیتابیس اجرا هستند."}
            </div>
          )}
        </section>

        <div className="grade-filter" role="group" aria-label={lang === "en" ? "Grades to search" : "پایه‌های جستجو"}>
          <span className="grade-filter-label">
            {lang === "en" ? "Search grades:" : "جستجو در پایه‌ها:"}
          </span>
          {[
            { value: 10, label: "دهم" },
            { value: 11, label: "یازدهم" },
            { value: 12, label: "دوازدهم" },
          ].map((grade) => {
            const active = multiGrades.includes(grade.value);
            return (
              <button
                key={grade.value}
                type="button"
                className={`grade-chip ${active ? "selected" : ""}`}
                aria-pressed={active}
                disabled={gradeNumber === null || grade.value > gradeNumber}
                onClick={() =>
                  setMultiGrades((prev) =>
                    prev.includes(grade.value)
                      ? prev.filter((item) => item !== grade.value)
                      : gradeNumber !== null && grade.value <= gradeNumber
                        ? [...prev, grade.value].sort((a, b) => a - b)
                        : prev
                  )
                }
              >
                {lang === "en" ? `Grade ${grade.value}` : `پایه ${grade.label}`}
              </button>
            );
          })}
          {multiGrades.length > 0 && (
            <button type="button" className="grade-chip clear" onClick={() => setMultiGrades([])}>
              {lang === "en" ? "Selected grade only" : "فقط پایهٔ انتخابی"}
            </button>
          )}
          <span className="grade-filter-hint">
            {multiGrades.length > 0
              ? lang === "en"
                ? "Citations may come from every selected grade."
                : "منبع‌ها می‌توانند از همهٔ پایه‌های انتخابی باشند."
              : ""}
          </span>
        </div>
        <div className="mode-toolbar">
          <div className="mode-tabs">
            <button
              type="button"
              className={`mode-tab auto-mode-tab ${autoMode ? "selected" : ""}`}
              aria-pressed={autoMode}
              onClick={() => setAutoMode((value) => !value)}
              title={
                lang === "en"
                  ? "Auto: the router picks tutor, solver, or designer for each question"
                  : "خودکار: مسیریاب برای هر پرسش، حالت مناسب را انتخاب می‌کند"
              }
            >
              <Wand2 size={15} />
              {lang === "en" ? "Auto" : "خودکار"}
            </button>
            <button
              className={`mode-tab ${tutoringMode === "tutor" ? "selected" : ""}`}
              onClick={() => setTutoringMode("tutor")}
            >
              <Sparkles size={15} />
              {lang === "en" ? "Personal Tutor" : "معلم خصوصی"}
            </button>
            <button
              className={`mode-tab ${tutoringMode === "problem_solver" ? "selected" : ""}`}
              onClick={() => setTutoringMode("problem_solver")}
            >
              <Check size={15} />
              {lang === "en" ? "Problem Solver" : "حل تمرین"}
            </button>
            <button
              className={`mode-tab ${tutoringMode === "question_designer" ? "selected" : ""}`}
              onClick={() => setTutoringMode("question_designer")}
            >
              <BookOpen size={15} />
              {lang === "en" ? "Question Designer" : "طراحی سؤال"}
            </button>
            <button
              className="mode-tab"
              onClick={() => {
                if (!currentUser || !getActiveToken()) {
                  openLoginModal(
                    lang === "en"
                      ? "Sign in to start a timed exam."
                      : "برای شروع آزمون زمان‌دار، ابتدا با شماره موبایل وارد شوید."
                  );
                  return;
                }
                setExamSetupOpen(true);
              }}
            >
              <GraduationCap size={15} />
              {lang === "en" ? "Timed Exam" : "آزمون زمان‌دار"}
            </button>
          </div>
          <span className="grounding-note">
            <ShieldCheck size={14} />{" "}
            {lang === "en" ? "Grounded in selected textbook" : "پاسخ مستند از کتاب انتخابی"}
          </span>
        </div>

        <section className={`conversation ${visibleMessages.length ? "has-messages" : ""}`}>
          {!visibleMessages.length ? (
            <div className="welcome-state">
              <div className="welcome-orb">
                <Sparkles size={25} />
              </div>
              <span className="eyebrow">
                {lang === "en" ? "CONVERSATIONAL STUDY" : "یادگیری با گفت‌وگو"}
              </span>
              <h1>
                {lang === "en" ? (
                  <>
                    Ready to learn
                    <br />
                    <em>together today?</em>
                  </>
                ) : (
                  <>
                    سلام! آماده‌ای
                    <br />
                    <em>با هم یاد بگیریم؟</em>
                  </>
                )}
              </h1>
              <p>
                {lang === "en" ? (
                  <>
                    Write your question, snap a photo of an exercise, or ask with voice.
                    <br />I will retrieve grounded answers straight from your textbook.
                  </>
                ) : (
                  <>
                    پرسشت را بنویس، از تمرین عکس بگیر یا با صدایت بپرس.
                    <br />
                    من پاسخ را از کتاب درسی انتخابی‌ات پیدا می‌کنم.
                  </>
                )}
              </p>
              {authReady && !currentUser && (
                <div className="auth-gate-banner">
                  <div>
                    <b>
                      {lang === "en"
                        ? "Sign in via SMS to start learning"
                        : "ورود پیامکی برای شروع یادگیری"}
                    </b>
                    <span>
                      {lang === "en"
                        ? `Enter your mobile number to receive ${formatNumber(
                            plansPayload?.starter_tokens ?? 15000,
                            lang
                          )} starter tokens.`
                        : `با شماره موبایل وارد شو و ${formatNumber(
                            plansPayload?.starter_tokens ?? 15000,
                            lang
                          )} توکن هدیهٔ شروع دریافت کن.`}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => openLoginModal()}
                  >
                    <Phone size={15} /> {lang === "en" ? "SMS Login" : "ورود با پیامک"}
                  </button>
                </div>
              )}
              <div className="suggestion-grid">
                {suggestions.map((text) => (
                  <button
                    key={text}
                    onClick={() => {
                      setDraft(text);
                      inputRef.current?.focus();
                    }}
                  >
                    <span>{text}</span>
                    <ArrowUp size={15} />
                  </button>
                ))}
              </div>
              <div className="trust-note">
                <ShieldCheck size={15} />{" "}
                {lang === "en"
                  ? "Every response cites the exact chapter and printed textbook page."
                  : "پاسخ‌ها همراه با ارجاع به فصل و صفحهٔ کتاب ارائه می‌شوند."}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {visibleMessages.map((message) => (
                <article key={message.id} className={`message-row ${message.role}`}>
                  {message.role === "assistant" ? (
                    <div className="assistant-avatar">
                      <Sparkles size={15} />
                    </div>
                  ) : (
                    <AccountAvatar size={29} className="user-avatar-wrap" />
                  )}
                  <div className="message-body">
                    {message.attachment && (
                      <div className="attachment-chip">
                        {message.attachment.endsWith(".webm") ? (
                          <AudioLines size={15} />
                        ) : (
                          <FileImage size={15} />
                        )}
                        {message.attachment}
                      </div>
                    )}
                    {message.routedMode && (
                      <div className="routed-chip">
                        <Wand2 size={12} />{" "}
                        {lang === "en" ? "Auto mode:" : "حالت خودکار:"}{" "}
                        {message.routedMode === "problem_solver"
                          ? lang === "en"
                            ? "Problem Solver"
                            : "حل تمرین"
                          : message.routedMode === "question_designer"
                          ? lang === "en"
                            ? "Question Designer"
                            : "طراحی سؤال"
                          : lang === "en"
                          ? "Personal Tutor"
                          : "معلم خصوصی"}
                        {message.routerSource === "heuristic" && (
                          <span className="routed-fallback">{lang === "en" ? " (rule-based)" : " (قاعده‌ای)"}</span>
                        )}
                      </div>
                    )}
                    <div className={`message-bubble ${message.role}`}>
                      {message.pending ? (
                        <p className="stream-text" aria-live="polite">
                          {message.content || (lang === "en" ? "…" : "…")}
                        </p>
                      ) : message.role === "assistant" ? (
                        message.blocks && message.blocks.length > 0 ? (
                          <LearningBlockRenderer
                            blocks={message.blocks.filter(
                              (block) =>
                                !(block && typeof block === "object" && (block as { type?: unknown }).type === "citation_ref")
                            )}
                            fallbackMarkdown={message.content}
                          />
                        ) : (
                          <MathContent content={message.content} />
                        )
                      ) : (
                        <p>{message.content}</p>
                      )}
                    </div>
                    {!!message.sources?.length && (
                      <div className="source-list">
                        <span>
                          <BookOpen size={13} />{" "}
                          {lang === "en" ? "Textbook Sources" : "منابع کتاب"}
                        </span>
                        {uniqueSourceTexts(message.sources, lang).map((text) => (
                          <div className="source-pill" key={text}>
                            {text}
                          </div>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" &&
                      !message.pending &&
                      !busy &&
                      !!message.id &&
                      message.id === lastAssistantId && (
                        <div className="regenerate-row">
                          <button
                            type="button"
                            className="regenerate-btn"
                            onClick={() => void regenerateLastAnswer()}
                            disabled={!!visibleMessages[visibleMessages.length - 1]?.attachment}
                          >
                            <RefreshCw size={13} /> {lang === "en" ? "Regenerate" : "تولید دوباره"}
                          </button>
                        </div>
                      )}
                    {message.role === "assistant" &&
                      !!message.sources?.length &&
                      (capabilityMenuEnabled("flashcards") ||
                        capabilityMenuEnabled("learning_notebook")) && (
                        <div className="fc-convert-row">
                          {capabilityMenuEnabled("flashcards") && (
                          <button
                            type="button"
                            className="fc-convert-btn"
                            disabled={!activeChatId || flashcardBusyId !== null}
                            onClick={() => void convertMessageToFlashcards(message)}
                            title={
                              activeChatId
                                ? undefined
                                : "برای تبدیل به فلش‌کارت، «ذخیرهٔ تاریخچهٔ گفت‌وگو» را در تنظیمات حریم خصوصی روشن کنید."
                            }
                          >
                            <Layers size={13} />{" "}
                            {flashcardBusyId === message.id
                              ? lang === "en"
                                ? "Creating…"
                                : "در حال ساخت…"
                              : lang === "en"
                              ? "Convert to flashcards"
                              : "تبدیل به فلش‌کارت"}
                          </button>
                          )}
                          {capabilityMenuEnabled("learning_notebook") && (
                          <button
                            type="button"
                            className="fc-convert-btn"
                            disabled={selectedBook === null || notebookBusyId !== null}
                            onClick={() => void convertMessageToNotebook(message)}
                            title={
                              selectedBook
                                ? undefined
                                : lang === "en"
                                  ? "Pick the book of this conversation first."
                                  : "ابتدا کتاب همین گفت‌وگو را انتخاب کن."
                            }
                          >
                            <NotebookPen size={13} />{" "}
                            {notebookBusyId === message.id
                              ? lang === "en"
                                ? "Saving…"
                                : "در حال ذخیره…"
                              : lang === "en"
                                ? "Add to notebook"
                                : "افزودن به دفترچه"}
                          </button>
                          )}
                          {!activeChatId && (
                            <span className="fc-convert-hint">
                              برای این کار «ذخیرهٔ تاریخچهٔ گفت‌وگو» را در تنظیمات حریم خصوصی روشن کنید.
                            </span>
                          )}
                        </div>
                      )}
                  </div>
                </article>
              ))}
              {busy && !streamingId && (
                <div className="typing-row" role="status">
                  <div className="assistant-avatar">
                    <Sparkles size={15} />
                  </div>
                  <div className="typing-bubble">
                    <span />
                    <span />
                    <span />
                    {lang === "en"
                      ? "Tutor is checking your textbook"
                      : "معلم در حال بررسی کتاب است"}
                  </div>
                </div>
              )}
              <div id="message-end" />
            </div>
          )}
        </section>

        {flashcardNotice && (
          <div className="fc-chat-notice" role="status">
            <span>{flashcardNotice.text}</span>
            {flashcardNotice.deckId !== null && (
              <Link href={`/flashcards`} onClick={() => setFlashcardNotice(null)}>
                مشاهدهٔ فلش‌کارت‌ها
              </Link>
            )}
          </div>
        )}
        {notebookNotice && (
          <div className="fc-chat-notice" role="status">
            <span>{notebookNotice.text}</span>
            {notebookNotice.notebookId !== null && (
              <Link href={`/notebook`} onClick={() => setNotebookNotice(null)}>
                {lang === "en" ? "Open notebook" : "مشاهدهٔ دفترچه"}
              </Link>
            )}
          </div>
        )}

        <footer className="composer-area">
          {messageError && (
            <div className="inline-error composer-error">
              {messageError}
              <button onClick={() => setMessageError("")} aria-label="بستن">
                <X size={15} />
              </button>
            </div>
          )}
          {(imageFile || audioFile) && (
            <div className="attachment-preview">
              <span>
                {imageFile ? <FileImage size={15} /> : <AudioLines size={15} />}
                {imageFile?.name ?? audioFile?.name}
              </span>
              <button onClick={clearAttachments} aria-label="حذف فایل">
                <X size={15} />
              </button>
            </div>
          )}
          <div className="composer-box">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder={
                !bookId
                  ? lang === "en"
                    ? "Select grade, major, and textbook first"
                    : "اول پایه، رشته و کتابت را انتخاب کن"
                  : !currentUser
                  ? lang === "en"
                    ? "Write your question or sign in to ask..."
                    : "برای پرسش از معلم، پیام خود را بنویس یا وارد شو..."
                  : tutoringMode === "problem_solver"
                  ? lang === "en"
                    ? "Type or attach a photo of your exercise..."
                    : "صورت تمرینت را بنویس یا از آن عکس بگیر..."
                  : tutoringMode === "question_designer"
                  ? lang === "en"
                    ? "Which chapter or topic should I design questions from?"
                    : "از کدام مبحث برایت سؤال طراحی کنم؟"
                  : lang === "en"
                  ? "Ask your tutor anything about this textbook..."
                  : "از معلمت هر چیزی دربارهٔ درس بپرس..."
              }
              disabled={!bookId || busy}
              rows={2}
            />
            <div className="composer-tools">
              <div className="tool-group">
                <button
                  className="tool-button"
                  disabled={!bookId || busy}
                  onClick={() => {
                    if (!currentUser || !getActiveToken()) {
                      openLoginModal(
                        lang === "en"
                          ? "Sign in with your mobile number to attach exercise images."
                          : "برای ارسال تصویر سؤال، ابتدا با شماره موبایل وارد شوید."
                      );
                      return;
                    }
                    imageInputRef.current?.click();
                  }}
                  title={lang === "en" ? "Attach image" : "پیوست تصویر"}
                >
                  <Paperclip size={18} />
                  <span>{lang === "en" ? "Question Image" : "تصویر سؤال"}</span>
                </button>
                <input
                  ref={imageInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) {
                      setImageFile(file);
                      setAudioFile(null);
                    }
                  }}
                />
                <button
                  className={`tool-button ${recording ? "recording" : ""}`}
                  disabled={!bookId || busy}
                  onClick={() => void startRecording()}
                  title={
                    recording
                      ? lang === "en"
                        ? "Stop recording"
                        : "پایان ضبط"
                      : lang === "en"
                      ? "Record voice"
                      : "ضبط صدا"
                  }
                >
                  {recording ? <Square size={16} /> : <Mic size={18} />}
                  <span>
                    {recording
                      ? lang === "en"
                        ? "Stop"
                        : "پایان ضبط"
                      : lang === "en"
                      ? "Voice"
                      : "صدا"}
                  </span>
                </button>
                {recording && (
                  <span className="recording-status">
                    <i />
                    {lang === "en" ? "Recording" : "در حال ضبط"}
                  </span>
                )}
              </div>
              {busy && streamingId ? (
                <button
                  type="button"
                  className="send-button stop-button"
                  onClick={() => void stopCurrentTurn()}
                  aria-label={lang === "en" ? "Stop generating" : "توقف تولید پاسخ"}
                  title={lang === "en" ? "Stop" : "توقف"}
                >
                  <Square size={16} />
                </button>
              ) : (
                <button
                  className="send-button"
                  disabled={!canAsk || (!draft.trim() && !imageFile && !audioFile)}
                  onClick={() => void sendMessage()}
                  aria-label={lang === "en" ? "Send question" : "ارسال پرسش"}
                >
                  {busy ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />}
                </button>
              )}
            </div>
          </div>
          <div className="composer-disclaimer">
            <span>
              {lang === "en"
                ? "Darsyar can make mistakes; verify answers against your textbook."
                : "درسیار ممکن است اشتباه کند؛ پاسخ را با کتاب درسی تطبیق بده."}
            </span>
            <span>
              <Check size={13} />{" "}
              {lang === "en" ? "Metered by token usage" : "مصرف بر اساس توکن محاسبه می‌شود"}
            </span>
          </div>
        </footer>
      </main>

      {examHistoryOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setExamHistoryOpen(false);
          }}
        >
          <section
            className="exam-setup-modal history-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="exam-history-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setExamHistoryOpen(false)}
              aria-label="بستن"
            >
              <X size={18} />
            </button>
            <div className="history-head">
              <div>
                <span className="eyebrow">
                  {lang === "en" ? "Exam History" : "تاریخچهٔ آزمون‌ها"}
                </span>
                <h2 id="exam-history-title">
                  {lang === "en" ? "My Exams" : "آزمون‌های من"}
                </h2>
                <p>
                  {lang === "en"
                    ? "Review past report cards or create a new timed exam."
                    : "کارنامهٔ آزمون‌های قبلی را مرور کن یا آزمون جدید بساز."}
                </p>
              </div>
              <button
                className="primary-button"
                type="button"
                onClick={() => {
                  setExamHistoryOpen(false);
                  setExamSetupOpen(true);
                }}
              >
                <Plus size={16} /> {lang === "en" ? "New Exam" : "آزمون جدید"}
              </button>
            </div>

            {historyLoading ? (
              <div className="history-empty">
                <LoaderCircle className="spin" size={18} />
                <span>
                  {lang === "en" ? "Loading exams..." : "در حال بارگذاری آزمون‌ها..."}
                </span>
              </div>
            ) : visibleExamHistory.length === 0 ? (
              <div className="history-empty">
                <GraduationCap size={22} />
                <span>
                  {lang === "en" ? "No exams recorded yet." : "هنوز آزمونی ثبت نشده است."}
                </span>
              </div>
            ) : (
              <div className="exam-history-list">
                {visibleExamHistory.map((item) => {
                  const summary = item.report_summary;
                  const canOpen = item.status === "submitted" || item.status === "active";
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className="exam-history-item"
                      disabled={!canOpen || busy}
                      onClick={() => void openSavedExam(item.id)}
                    >
                      <div className="exam-history-main">
                        <div className="exam-history-top">
                          <b>{item.title}</b>
                          <span className={`history-status ${item.status}`}>
                            {item.status === "submitted"
                              ? lang === "en"
                                ? "Report Ready"
                                : "کارنامه آماده"
                              : item.status === "active"
                              ? lang === "en"
                                ? "In Progress"
                                : "در حال اجرا"
                              : lang === "en"
                              ? "Expired"
                              : "منقضی‌شده"}
                          </span>
                        </div>
                        <small>
                          {item.book_title ?? `${lang === "en" ? "Book" : "کتاب"} #${item.book_id}`} ·{" "}
                          {item.exam_type === "konkoor"
                            ? lang === "en"
                              ? "Konkoor"
                              : "کنکوری"
                            : lang === "en"
                            ? "Practice"
                            : "تمرینی"}{" "}
                          · {formatNumber(item.question_count, lang)}{" "}
                          {lang === "en" ? "questions" : "سؤال"}
                        </small>
                        <span className="exam-history-date">
                          <Clock3 size={12} />{" "}
                          {formatDateTime(item.submitted_at ?? item.created_at, lang, tz)}
                        </span>
                      </div>
                      <div className="exam-history-score">
                        {summary ? (
                          <>
                            <strong>{formatNumber(summary.score, lang)}</strong>
                            <span>
                              {summary.scale === "percent"
                                ? lang === "en"
                                  ? "%"
                                  : "درصد"
                                : lang === "en"
                                ? "/ 20"
                                : "از ۲۰"}
                            </span>
                          </>
                        ) : (
                          <span>
                            {item.status === "active"
                              ? lang === "en"
                                ? "Resume"
                                : "ادامه"
                              : lang === "en"
                              ? "Closed"
                              : "بسته"}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      {examSetupOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget) setExamSetupOpen(false);
          }}
        >
          <section
            className="exam-setup-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="exam-modal-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setExamSetupOpen(false)}
              aria-label="بستن"
            >
              <X size={18} />
            </button>
            <div className="modal-icon">
              <GraduationCap size={22} />
            </div>
            <span className="eyebrow">
              {lang === "en" ? "ASSESSMENT" : "سنجش یادگیری"}
            </span>
            <h2 id="exam-modal-title">
              {lang === "en" ? "Configure Your Exam" : "آزمونت را تنظیم کن"}
            </h2>
            <p>
              {lang === "en"
                ? "Questions are generated exclusively from approved pages of the selected textbook."
                : "سؤال‌ها از صفحه‌های تأییدشدهٔ کتاب انتخابی طراحی می‌شوند."}
            </p>
            <label className="form-field">
              <span>{lang === "en" ? "Exam Format" : "نوع آزمون"}</span>
              <select
                value={examType}
                onChange={(event) => setExamType(event.target.value as "konkoor" | "final")}
              >
                <option value="konkoor">
                  {lang === "en"
                    ? "Konkoor — with 1/3 negative marking"
                    : "کنکوری — با نمرهٔ منفی"}
                </option>
                <option value="final">
                  {lang === "en" ? "Practice — scored out of 20" : "تمرینی — نمره از ۲۰"}
                </option>
              </select>
            </label>
            <div className="form-row">
              <label className="form-field">
                <span>{lang === "en" ? "Questions" : "تعداد سؤال"}</span>
                <select
                  value={questionCount}
                  onChange={(event) => setQuestionCount(Number(event.target.value))}
                >
                  {[3, 5, 10, 15, 20].map((count) => (
                    <option key={count} value={count}>
                      {formatNumber(count, lang)} {lang === "en" ? "questions" : "سؤال"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="form-field">
                <span>{lang === "en" ? "Time Limit" : "زمان"}</span>
                <select
                  value={timeLimit}
                  onChange={(event) => setTimeLimit(Number(event.target.value))}
                >
                  {[5, 10, 15, 20, 30, 45, 60].map((minutes) => (
                    <option key={minutes} value={minutes}>
                      {formatNumber(minutes, lang)} {lang === "en" ? "min" : "دقیقه"}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {messageError && <div className="inline-error">{messageError}</div>}
            <button
              className="primary-button modal-submit"
              disabled={!bookId || busy}
              onClick={() => void createExam()}
            >
              {busy ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <GraduationCap size={17} />
              )}
              {lang === "en" ? "Start Exam" : "شروع آزمون"}
            </button>
            {visibleExamHistory.length > 0 && (
              <button
                type="button"
                className="outline-button modal-submit"
                onClick={() => {
                  setExamSetupOpen(false);
                  void openExamHistory();
                }}
              >
                <MessageSquare size={15} />{" "}
                {lang === "en"
                  ? `View Previous Exams (${visibleExamHistory.length})`
                  : `مشاهدهٔ آزمون‌های قبلی (${formatNumber(visibleExamHistory.length, lang)})`}
              </button>
            )}
            {!bookId && (
              <small className="modal-hint">
                {lang === "en"
                  ? "Select a textbook first to create an exam."
                  : "برای ساخت آزمون، ابتدا کتابت را انتخاب کن."}
              </small>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
