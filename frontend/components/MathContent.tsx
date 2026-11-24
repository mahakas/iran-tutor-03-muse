"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { normalizeLatexMarkdown } from "@/lib/math";

type Props = {
  content: string;
  inline?: boolean;
  className?: string;
};

export default function MathContent({ content, inline = false, className = "" }: Props) {
  const normalized = normalizeLatexMarkdown(content);
  const classes = [inline ? "math-inline" : "markdown-body", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
