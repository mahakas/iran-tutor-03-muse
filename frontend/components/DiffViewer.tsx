"use client";

import { useMemo } from "react";
import { computeLineDiff } from "@/lib/diff";

type DiffViewerProps = {
  beforeText: string;
  afterText: string;
  diffMarkersEnabled?: boolean;
  codeFontSize?: number;
  title?: string;
  emptyLabel?: string;
};

export default function DiffViewer({
  beforeText,
  afterText,
  diffMarkersEnabled = true,
  codeFontSize,
  title = "نمای تفاوت خطوط (Diff)",
  emptyLabel = "تفاوتی بین نسخه مرجع و متن فعلی وجود ندارد.",
}: DiffViewerProps) {
  const diff = useMemo(() => computeLineDiff(beforeText, afterText), [beforeText, afterText]);

  return (
    <div
      className={`diff-viewer ${diffMarkersEnabled ? "markers-on" : "markers-off"}`}
      role="region"
      aria-label={title}
    >
      <div className="diff-viewer-head">
        <b>{title}</b>
        <div className="diff-summary-pills">
          <span className="diff-pill added" aria-label={`خطوط اضافه‌شده: ${diff.addedCount}`}>
            +{diff.addedCount} افزوده
          </span>
          <span className="diff-pill removed" aria-label={`خطوط حذف‌شده: ${diff.removedCount}`}>
            -{diff.removedCount} حذف
          </span>
          <span className="diff-pill mode-note">
            {diffMarkersEnabled ? "نشانگر رنگی + نماد فعال" : "نشانگر رنگی خاموش"}
          </span>
        </div>
      </div>

      {!diff.hasChanges ? (
        <div className="diff-empty-note">{emptyLabel}</div>
      ) : (
        <div
          className="diff-lines-scroll"
          style={codeFontSize ? { fontSize: `${codeFontSize}px` } : undefined}
        >
          {diff.lines.map((line, index) => {
            const symbol = line.kind === "added" ? "+" : line.kind === "removed" ? "-" : "·";
            const srPrefix =
              line.kind === "added" ? "افزوده: " : line.kind === "removed" ? "حذف: " : "ثابت: ";
            return (
              <div
                key={`${index}-${line.oldLine ?? "x"}-${line.newLine ?? "y"}`}
                className={`diff-line ${line.kind}`}
              >
                <span className="diff-line-nums" dir="ltr" aria-hidden="true">
                  <span>{line.oldLine ?? ""}</span>
                  <span>{line.newLine ?? ""}</span>
                </span>
                <span className="diff-gutter" aria-hidden="true">
                  {symbol}
                </span>
                <span className="diff-line-text" dir="auto">
                  <span className="sr-only">{srPrefix}</span>
                  {line.text.length > 0 ? line.text : "\u00A0"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
