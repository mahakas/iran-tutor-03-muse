/** Phase 6 shared types and helpers: notebook, Inline AI, visualize, Living Book, TTS. */

export type NotebookSummary = {
  id: number;
  title: string;
  book_id: number | null;
  grade_number: number | null;
  major_code: string | null;
  block_count?: number;
  updated_at: string | null;
};

export type NotebookBlockItem = {
  id: number;
  position: number;
  block_type: NotebookBlockType;
  content: string;
  metadata: Record<string, unknown>;
};

export type NotebookBlockType =
  | "text_markdown"
  | "formula_latex"
  | "callout_tip"
  | "comparison_table"
  | "diagram_mermaid"
  | "diagram_svg";

export type NotebookDetail = NotebookSummary & { blocks: NotebookBlockItem[] };

export type InlineAction = "simplify" | "summarize" | "example" | "to_formula_or_table" | "to_flashcard";

export const INLINE_ACTION_LABELS: Record<InlineAction, string> = {
  simplify: "ساده‌تر توضیح بده",
  summarize: "خلاصه کن",
  example: "مثال بزن",
  to_formula_or_table: "به فرمول/جدول تبدیل کن",
  to_flashcard: "به فلش‌کارت تبدیل کن",
};

export type InlineProposal = {
  notebook_id: number;
  block_id: number;
  action: InlineAction;
  kind: "text" | "flashcard";
  selection: string;
  proposed: string | { front: string; back: string };
  citations: string[];
  audit_id: string;
};

export type LivingBookBlock = { type: string; content: string; metadata: Record<string, unknown> };

export type LivingBookPayload = {
  book_id: number;
  book_title: string;
  chapter_number: number;
  chapter_title: string;
  content_hash: string;
  printed_pages: number[];
  cache_hit: boolean;
  blocks: LivingBookBlock[];
  rejected_count: number;
};

export function phase6ErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

export function toFaDigits(value: number | string): string {
  return String(value).replace(/[0-9]/g, (digit) => PERSIAN_DIGITS[Number(digit)]);
}
