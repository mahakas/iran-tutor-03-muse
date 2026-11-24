"use client";

import { useState } from "react";
import MathContent from "@/components/MathContent";
import { normalizeLearningBlocks, type LearningBlock } from "@/lib/learningBlocks";
import MermaidDiagram from "@/components/MermaidDiagram";
import SvgDiagram from "@/components/SvgDiagram";

type Props = {
  blocks: unknown;
  /** Optional fallback text when no typed blocks are present. */
  fallbackMarkdown?: string;
};

/**
 * Renders typed Learning Blocks with full RTL layout and KaTeX math.
 * Every block is wrapped in `dir="rtl"`; formulas and code stay LTR inside.
 */
export default function LearningBlockRenderer({ blocks, fallbackMarkdown }: Props) {
  const items = normalizeLearningBlocks(blocks);
  if (items.length === 0) {
    return fallbackMarkdown ? <MathContent content={fallbackMarkdown} /> : null;
  }
  return (
    <div className="learning-blocks" dir="rtl" lang="fa">
      {items.map((block, index) => (
        <BlockView key={`${block.type}-${index}`} block={block} />
      ))}
    </div>
  );
}

function BlockView({ block }: { block: LearningBlock }) {
  switch (block.type) {
    case "text_markdown":
      return <MathContent content={block.content} />;
    case "formula_latex":
      return <FormulaBlock latex={block.content} />;
    case "callout_tip":
      return <CalloutBlock block={block} />;
    case "citation_ref":
      return <CitationBlock block={block} />;
    case "quiz_item":
      return <QuizBlock block={block} />;
    case "flashcard_item":
      return <FlashcardBlock block={block} />;
    case "diagram_mermaid":
      return <MermaidDiagram source={block.content} caption={textOf(block.metadata.title) || textOf(block.metadata.caption)} />;
    case "diagram_svg":
      return (
        <figure className="lb-diagram">
          <SvgDiagram svg={block.content} />
          {textOf(block.metadata.caption) && (
            <figcaption className="lb-caption">{textOf(block.metadata.caption)}</figcaption>
          )}
        </figure>
      );
    default:
      return null;
  }
}

function textOf(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function FormulaBlock({ latex }: { latex: string }) {
  const cleaned = latex.replace(/^\s*\$+|\$+\s*$/g, "").trim();
  return (
    <div className="lb-formula" dir="ltr">
      <MathContent content={`$$\n${cleaned}\n$$`} />
    </div>
  );
}

function CalloutBlock({ block }: { block: LearningBlock }) {
  const tone = textOf(block.metadata.tone) || "tip";
  const title =
    textOf(block.metadata.title) || (tone === "warning" ? "هشدار" : tone === "note" ? "یادداشت" : "نکته");
  return (
    <aside className={`lb-callout lb-callout-${tone}`} role="note">
      <strong className="lb-callout-title">{title}</strong>
      <MathContent content={block.content} />
    </aside>
  );
}

function CitationBlock({ block }: { block: LearningBlock }) {
  const meta = block.metadata;
  const parts: string[] = [];
  if (textOf(meta.book_title)) parts.push(textOf(meta.book_title));
  if (typeof meta.chapter_number === "number") parts.push(`فصل ${meta.chapter_number}`);
  if (typeof meta.printed_page_number === "number") parts.push(`صفحه ${meta.printed_page_number}`);
  const label = block.content || parts.join(" · ") || "منبع کتاب";
  return (
    <span className="lb-citation" title={parts.join(" · ")}>
      📖 {label}
    </span>
  );
}

function QuizBlock({ block }: { block: LearningBlock }) {
  const options = Array.isArray(block.metadata.options)
    ? (block.metadata.options as unknown[]).map((item) => String(item))
    : [];
  const answerIndex =
    typeof block.metadata.answer_index === "number" ? block.metadata.answer_index : null;
  const explanation = textOf(block.metadata.explanation);
  const [selected, setSelected] = useState<number | null>(null);
  const revealed = selected !== null;
  return (
    <div className="lb-quiz">
      <MathContent content={block.content} />
      <ol className="lb-quiz-options" type="1">
        {options.map((option, idx) => {
          const correct = answerIndex === idx;
          const state = revealed ? (correct ? "correct" : selected === idx ? "wrong" : "") : "";
          return (
            <li key={idx}>
              <button
                type="button"
                className={`lb-quiz-option ${state}`}
                onClick={() => setSelected(idx)}
                disabled={revealed}
              >
                <MathContent content={option} inline />
              </button>
            </li>
          );
        })}
      </ol>
      {revealed && explanation && (
        <div className="lb-quiz-explain">
          <MathContent content={explanation} />
        </div>
      )}
    </div>
  );
}

function FlashcardBlock({ block }: { block: LearningBlock }) {
  const back = textOf(block.metadata.back);
  const [flipped, setFlipped] = useState(false);
  return (
    <button
      type="button"
      className={`lb-flashcard ${flipped ? "flipped" : ""}`}
      onClick={() => setFlipped((value) => !value)}
      aria-pressed={flipped}
    >
      <span className="lb-caption">{flipped ? "پشت کارت" : "روی کارت"}</span>
      <MathContent content={flipped ? back : block.content} />
    </button>
  );
}
