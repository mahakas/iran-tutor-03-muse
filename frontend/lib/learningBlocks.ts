/**
 * Typed Learning Blocks (Phase 2) — frontend mirror of the backend
 * `app/services/learning_blocks.py` contract.
 */

export const LEARNING_BLOCK_TYPES = [
  "text_markdown",
  "formula_latex",
  "callout_tip",
  "citation_ref",
  "quiz_item",
  "flashcard_item",
  "diagram_mermaid",
  "diagram_svg",
] as const;

export type LearningBlockType = (typeof LEARNING_BLOCK_TYPES)[number];

export type LearningBlock = {
  type: LearningBlockType;
  content: string;
  metadata: Record<string, unknown>;
};

export function isLearningBlock(value: unknown): value is LearningBlock {
  if (!value || typeof value !== "object") return false;
  const candidate = value as { type?: unknown; content?: unknown };
  return (
    typeof candidate.type === "string" &&
    (LEARNING_BLOCK_TYPES as readonly string[]).includes(candidate.type) &&
    typeof candidate.content === "string"
  );
}

export function normalizeLearningBlocks(raw: unknown): LearningBlock[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isLearningBlock).map((block) => ({
    type: block.type,
    content: block.content,
    metadata:
      block.metadata && typeof block.metadata === "object"
        ? (block.metadata as Record<string, unknown>)
        : {},
  }));
}
