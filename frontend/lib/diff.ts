export type DiffLineKind = "context" | "added" | "removed";

export type DiffLine = {
  kind: DiffLineKind;
  oldLine: number | null;
  newLine: number | null;
  text: string;
};

export type LineDiffResult = {
  lines: DiffLine[];
  addedCount: number;
  removedCount: number;
  hasChanges: boolean;
};

function splitLines(text: string): string[] {
  const normalized = (text ?? "").replace(/\r\n/g, "\n");
  return normalized.length === 0 ? [] : normalized.split("\n");
}

/**
 * Compute an accessible line-by-line LCS diff between `beforeText` and `afterText`.
 * Safely caps quadratic matrix work for very large inputs with a clean prefix/suffix trim.
 */
export function computeLineDiff(beforeText: string, afterText: string): LineDiffResult {
  const a = splitLines(beforeText);
  const b = splitLines(afterText);

  // Trim identical prefix & suffix first to speed up typical page edits dramatically.
  let prefixLen = 0;
  while (prefixLen < a.length && prefixLen < b.length && a[prefixLen] === b[prefixLen]) {
    prefixLen += 1;
  }

  let suffixLen = 0;
  while (
    suffixLen < a.length - prefixLen &&
    suffixLen < b.length - prefixLen &&
    a[a.length - 1 - suffixLen] === b[b.length - 1 - suffixLen]
  ) {
    suffixLen += 1;
  }

  const aMid = a.slice(prefixLen, a.length - suffixLen);
  const bMid = b.slice(prefixLen, b.length - suffixLen);

  const lines: DiffLine[] = [];
  let addedCount = 0;
  let removedCount = 0;

  for (let i = 0; i < prefixLen; i += 1) {
    lines.push({ kind: "context", oldLine: i + 1, newLine: i + 1, text: a[i] });
  }

  if (aMid.length === 0 && bMid.length === 0) {
    return { lines, addedCount: 0, removedCount: 0, hasChanges: false };
  }

  if (aMid.length * bMid.length > 40_000) {
    // Fallback for huge multi-thousand-line diffs
    aMid.forEach((line, idx) => {
      removedCount += 1;
      lines.push({ kind: "removed", oldLine: prefixLen + idx + 1, newLine: null, text: line });
    });
    bMid.forEach((line, idx) => {
      addedCount += 1;
      lines.push({ kind: "added", oldLine: null, newLine: prefixLen + idx + 1, text: line });
    });
  } else {
    const m = aMid.length;
    const n = bMid.length;
    const dp: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
    for (let i = m - 1; i >= 0; i -= 1) {
      for (let j = n - 1; j >= 0; j -= 1) {
        if (aMid[i] === bMid[j]) {
          dp[i][j] = 1 + dp[i + 1][j + 1];
        } else {
          dp[i][j] = dp[i + 1][j] >= dp[i][j + 1] ? dp[i + 1][j] : dp[i][j + 1];
        }
      }
    }

    let i = 0;
    let j = 0;
    let oldNum = prefixLen + 1;
    let newNum = prefixLen + 1;
    while (i < m && j < n) {
      if (aMid[i] === bMid[j]) {
        lines.push({ kind: "context", oldLine: oldNum, newLine: newNum, text: aMid[i] });
        i += 1;
        j += 1;
        oldNum += 1;
        newNum += 1;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        removedCount += 1;
        lines.push({ kind: "removed", oldLine: oldNum, newLine: null, text: aMid[i] });
        i += 1;
        oldNum += 1;
      } else {
        addedCount += 1;
        lines.push({ kind: "added", oldLine: null, newLine: newNum, text: bMid[j] });
        j += 1;
        newNum += 1;
      }
    }
    while (i < m) {
      removedCount += 1;
      lines.push({ kind: "removed", oldLine: oldNum, newLine: null, text: aMid[i] });
      i += 1;
      oldNum += 1;
    }
    while (j < n) {
      addedCount += 1;
      lines.push({ kind: "added", oldLine: null, newLine: newNum, text: bMid[j] });
      j += 1;
      newNum += 1;
    }
  }

  for (let k = 0; k < suffixLen; k += 1) {
    const oldLine = a.length - suffixLen + k + 1;
    const newLine = b.length - suffixLen + k + 1;
    lines.push({
      kind: "context",
      oldLine,
      newLine,
      text: a[a.length - suffixLen + k],
    });
  }

  return {
    lines,
    addedCount,
    removedCount,
    hasChanges: addedCount > 0 || removedCount > 0,
  };
}
