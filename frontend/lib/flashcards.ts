/** Phase 3 flashcard types shared by the student workspace, chat button and admin panel. */

export type FlashcardStats = {
  total: number;
  due: number;
  mastered: number;
  new: number;
  progress_percent: number;
  /** ISO timestamp of the most recent real SM-2 review in the deck; null = never studied. */
  last_review: string | null;
};

export type FlashcardDeck = {
  id: number;
  title: string;
  book_id: number | null;
  chapter_number: number | null;
  page_start: number | null;
  page_end: number | null;
  source_type: "book" | "chat" | "mistake" | "manual";
  is_public: boolean;
  admin_approved: boolean;
  created_at: string | null;
  stats: FlashcardStats;
};

export type FlashcardCitation = {
  book_id: number | null;
  book_title: string | null;
  chapter_number: number | null;
  chapter_title: string | null;
  pdf_page_index: number | null;
  printed_page_number: number | null;
  citation: string;
};

export type FlashcardReview = {
  ease_factor: number;
  interval_days: number;
  repetitions: number;
  next_review_at: string;
  last_rating: number | null;
  review_count: number;
};

export type Flashcard = {
  id: number;
  deck_id: number;
  front_md: string;
  back_md: string;
  hint_md: string;
  citations: FlashcardCitation[];
  tags: string[];
  review: FlashcardReview | null;
  deck_title?: string;
};

export type FlashcardDeckDetail = FlashcardDeck & { cards: Flashcard[] };

export type DueQueue = { due_count: number; cards: Flashcard[] };

/** Issue-report reasons, mirroring the shared backend feedback vocabulary. */
export const CARD_REPORT_REASONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "wrong_answer", label: "پاسخ نادرست است" },
  { value: "not_from_book", label: "از کتاب رسمی نیست" },
  { value: "unclear", label: "نامفهوم است" },
  { value: "inappropriate", label: "محتوای نامناسب" },
  { value: "other", label: "دلیل دیگر" },
];

export const RATING_BUTTONS: ReadonlyArray<{ rating: 1 | 2 | 3 | 4; label: string; tone: string }> = [
  { rating: 1, label: "فراموش کردم", tone: "again" },
  { rating: 2, label: "سخت", tone: "hard" },
  { rating: 3, label: "خوب", tone: "good" },
  { rating: 4, label: "آسان", tone: "easy" },
];

// ---------------------------------------------------------------------------
// NotebookLM-style generation options + study sessions
// ---------------------------------------------------------------------------

export type GenerateDifficulty = "easy" | "medium" | "hard";

export type CountPresetKey = "fewer" | "standard" | "more";

export const COUNT_PRESETS: ReadonlyArray<{ key: CountPresetKey; label: string; value: number }> = [
  { key: "fewer", label: "کمتر", value: 3 },
  { key: "standard", label: "استاندارد", value: 5 },
  { key: "more", label: "بیشتر", value: 10 },
];

export const DIFFICULTY_OPTIONS: ReadonlyArray<{ key: GenerateDifficulty; label: string; hint: string }> = [
  { key: "easy", label: "آسان", hint: "تعاریف ساده و مفاهیم پایه" },
  { key: "medium", label: "متوسط", hint: "مفاهیم اصلی فصل و روابط بین مطالب" },
  { key: "hard", label: "سخت", hint: "مقایسهٔ مفاهیم و سنجش فهم عمیق" },
];

export const MAX_FOCUS_PROMPT_CHARS = 500;

export type StudyMode = "full" | "smart" | "subset";
export type StudyResult = "got" | "missed";

export type StudySessionSummary = {
  total: number;
  answered: number;
  got: number;
  missed: number;
  percent: number;
  status: string;
};

export type StudySessionPayload = {
  id: number;
  deck_id: number;
  mode: StudyMode;
  status: "active" | "completed";
  position: number;
  flipped: boolean;
  card_order: number[];
  results: Record<string, StudyResult>;
  total_cards: number;
  summary: StudySessionSummary;
  started_at: string | null;
  last_activity_at: string | null;
  completed_at: string | null;
  cards?: Flashcard[];
};

export type ExplainPayload = {
  explain_md: string;
  audit_id: string | null;
  grounded_in_book: boolean;
  citations: FlashcardCitation[];
};

/** Reads FastAPI's `detail` (string or validation list) and falls back to a Persian message. */
export function flashcardErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
      return detail[0].msg as string;
    }
  }
  return fallback;
}
