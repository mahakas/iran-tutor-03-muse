import type { ChatMessage, ExamSummary, Source } from "@/lib/types";
import { toFaDigits } from "@/lib/phase6";

// ─── Handoff helpers (Phase 02) ────────────────────────────────────────────────
// Pure functions only: every value here comes from real user data the APIs
// already return. Nothing invents scores, streaks or recommendations.

export type ContinueTarget =
  | { kind: "exam"; id: string; title: string; status: ExamSummary["status"] }
  | { kind: "chat"; id: string; title: string }
  | { kind: "flashcards"; dueCount: number }
  | { kind: "mistakes"; openCount: number };

export type ContinueInputs = {
  /** Exams the user has started but not submitted (real resume targets). */
  activeExams: ExamSummary[];
  /** Chat sessions sorted newest-first (caller may pass any order). */
  chatSessions: Array<{ id: string; title: string; updated_at: string | null }>;
  /** Real SM-2 due count from /api/v1/flashcards/due. */
  dueFlashcards: number | null;
  /** Real unresolved-mistake count from /api/v1/mistakes?status=unresolved. */
  openMistakes: number | null;
  /** Submitted exams, newest-first — report card is still a "continue". */
  submittedExams: ExamSummary[];
};

/**
 * Picks the single most useful "continue" destination from real activity only.
 * Priority: an un-submitted exam > latest chat > due flashcard review >
 * unresolved mistakes > latest finished exam's report card > nothing.
 */
export function pickContinueTarget(inputs: ContinueInputs): ContinueTarget | null {
  const activeExam = [...inputs.activeExams].sort(
    (a, b) => (Date.parse(b.created_at ?? "") || 0) - (Date.parse(a.created_at ?? "") || 0)
  )[0];
  if (activeExam) {
    return { kind: "exam", id: activeExam.id, title: activeExam.title, status: activeExam.status };
  }

  const latestChat = [...inputs.chatSessions].sort(
    (a, b) => (Date.parse(b.updated_at ?? "") || 0) - (Date.parse(a.updated_at ?? "") || 0)
  )[0];
  if (latestChat) {
    return { kind: "chat", id: latestChat.id, title: latestChat.title };
  }

  if (inputs.dueFlashcards !== null && inputs.dueFlashcards > 0) {
    return { kind: "flashcards", dueCount: inputs.dueFlashcards };
  }
  if (inputs.openMistakes !== null && inputs.openMistakes > 0) {
    return { kind: "mistakes", openCount: inputs.openMistakes };
  }

  const lastExam = [...inputs.submittedExams].sort(
    (a, b) => (Date.parse(b.submitted_at ?? b.created_at ?? "") || 0) - (Date.parse(a.submitted_at ?? a.created_at ?? "") || 0)
  )[0];
  if (lastExam) {
    return { kind: "exam", id: lastExam.id, title: lastExam.title, status: lastExam.status };
  }
  return null;
}

/** Human-readable provenance line from a tutor answer's citation sources. */
export function citationTextFromSources(sources: Source[] | undefined, fallbackTitle: string): string {
  const source = sources?.[0];
  if (!source) return fallbackTitle;
  const parts: string[] = [];
  if (source.book_title) parts.push(source.book_title);
  else if (fallbackTitle) parts.push(fallbackTitle);
  if (source.chapter_title) parts.push(source.chapter_title);
  else if (source.chapter_number !== null && source.chapter_number !== undefined) {
    parts.push(`فصل ${toFaDigits(source.chapter_number)}`);
  }
  if (source.printed_page_number !== null && source.printed_page_number !== undefined) {
    parts.push(`صفحهٔ ${toFaDigits(source.printed_page_number)}`);
  }
  return parts.length > 0 ? parts.join(" — ") : fallbackTitle;
}

export type NotebookBlockDraft = {
  block_type: "text_markdown";
  content: string;
  metadata: { title: string; citation: string; conversation_id?: string; message_id?: string };
};

/**
 * Builds a notebook block from a tutor answer, carrying provenance (book, chapter,
 * printed page) into the next tool so the source is never lost or swapped.
 * conversation_id + message_id give the save a stable identity: the backend
 * replays the existing block instead of duplicating it on retries/parallel POSTs.
 */
export function buildNotebookBlockFromMessage(
  message: Pick<ChatMessage, "content" | "sources">,
  bookTitle: string,
  handoffRef?: { conversationId?: string | null; messageId?: string | null }
): NotebookBlockDraft {
  const content = (message.content ?? "").trim();
  return {
    block_type: "text_markdown",
    content,
    metadata: {
      title: bookTitle,
      citation: citationTextFromSources(message.sources, bookTitle),
      ...(handoffRef?.conversationId ? { conversation_id: handoffRef.conversationId } : {}),
      ...(handoffRef?.messageId ? { message_id: handoffRef.messageId } : {}),
    },
  };
}
