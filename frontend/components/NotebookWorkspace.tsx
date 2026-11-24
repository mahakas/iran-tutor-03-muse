"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Plus, Sparkles, Trash2, Pencil } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import BookGradePicker from "@/components/BookGradePicker";
import DiffViewer from "@/components/DiffViewer";
import AudioButton from "@/components/AudioButton";
import LearningBlockRenderer from "@/components/LearningBlockRenderer";
import {
  INLINE_ACTION_LABELS,
  phase6ErrorMessage,
  toFaDigits,
  type InlineAction,
  type InlineProposal,
  type NotebookBlockItem,
  type NotebookBlockType,
  type NotebookDetail,
  type NotebookSummary,
} from "@/lib/phase6";

const BLOCK_LABELS: Record<NotebookBlockType, string> = {
  text_markdown: "متن",
  formula_latex: "فرمول (LaTeX)",
  callout_tip: "نکته",
  comparison_table: "جدول مقایسه (JSON)",
  diagram_mermaid: "نمودار Mermaid",
  diagram_svg: "SVG",
};

const TEXT_EDITABLE: NotebookBlockType[] = ["text_markdown", "formula_latex", "callout_tip"];
const INLINE_TEXT: NotebookBlockType[] = ["text_markdown", "callout_tip"];
const TABLE_TEMPLATE = JSON.stringify({ headers: ["ویژگی", "الف", "ب"], rows: [["نماد", "F", "v"]] }, null, 2);

type Selection = { blockId: number; text: string };

export default function NotebookWorkspace() {
  const { authFetch } = useAppContext();
  const [list, setList] = useState<NotebookSummary[]>([]);
  const [active, setActive] = useState<NotebookDetail | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newBook, setNewBook] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [proposal, setProposal] = useState<InlineProposal | null>(null);
  const [newType, setNewType] = useState<NotebookBlockType>("text_markdown");
  const [newContent, setNewContent] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [vizKind, setVizKind] = useState<"mermaid" | "svg" | "table">("mermaid");
  const [vizPrompt, setVizPrompt] = useState("");

  const run = useCallback(
    async (url: string, init?: RequestInit): Promise<{ ok: boolean; status: number; payload: unknown }> => {
      const res = await authFetch(url, {
        ...init,
        headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers ?? {}) },
      });
      const payload = res.status === 204 ? null : await res.json().catch(() => null);
      return { ok: res.ok, status: res.status, payload };
    },
    [authFetch]
  );

  const loadList = useCallback(async () => {
    const r = await run("/api/v1/notebooks");
    if (r.ok) setList(((r.payload as { items: NotebookSummary[] }).items) ?? []);
    else setMessage(phase6ErrorMessage(r.payload, "فهرست دفترچه‌ها بارگذاری نشد."));
  }, [run]);

  const open = useCallback(
    async (id: number) => {
      const r = await run(`/api/v1/notebooks/${id}`);
      if (r.ok) {
        setActive(r.payload as NotebookDetail);
        setSelection(null);
        setProposal(null);
      } else setMessage(phase6ErrorMessage(r.payload, "دفترچه باز نشد."));
    },
    [run]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await run("/api/v1/notebooks");
      if (cancelled) return;
      if (r.ok) setList(((r.payload as { items: NotebookSummary[] }).items) ?? []);
      else setMessage(phase6ErrorMessage(r.payload, "فهرست دفترچه‌ها بارگذاری نشد."));
    })();
    return () => {
      cancelled = true;
    };
  }, [run]);

  const create = async () => {
    if (!newTitle.trim()) return setMessage("عنوان دفترچه را وارد کنید.");
    setBusy(true);
    const r = await run("/api/v1/notebooks", { method: "POST", body: JSON.stringify({ title: newTitle, book_id: newBook }) });
    setBusy(false);
    if (!r.ok) return setMessage(phase6ErrorMessage(r.payload, "ساخت دفترچه ممکن نشد."));
    setNewTitle("");
    setMessage(null);
    await loadList();
    await open((r.payload as NotebookSummary).id);
  };

  const remove = async (id: number) => {
    if (!window.confirm("این دفترچه و همهٔ بلوک‌های آن حذف شود؟")) return;
    const r = await run(`/api/v1/notebooks/${id}`, { method: "DELETE" });
    if (!r.ok) return setMessage("حذف دفترچه ممکن نشد.");
    if (active?.id === id) setActive(null);
    await loadList();
  };

  const reload = async () => {
    if (active) await open(active.id);
  };

  const addBlock = async (type: NotebookBlockType, content: string, metadata: Record<string, unknown> = {}) => {
    if (!active) return;
    setBusy(true);
    const r = await run(`/api/v1/notebooks/${active.id}/blocks`, {
      method: "POST",
      body: JSON.stringify({ block_type: type, content, metadata }),
    });
    setBusy(false);
    if (!r.ok) return setMessage(phase6ErrorMessage(r.payload, "افزودن بلوک ممکن نشد؛ محتوا از بررسی ایمنی یا ساختار نگذشت."));
    setMessage(null);
    await reload();
  };

  const submitNewBlock = async () => {
    if (!newContent.trim()) return setMessage("محتوای بلوک را وارد کنید.");
    await addBlock(newType, newContent);
    setNewContent("");
  };

  const generateVisual = async () => {
    if (!active?.book_id) return setMessage("برای تولید نمودار، دفترچه باید به یک کتاب وصل باشد.");
    if (!vizPrompt.trim()) return setMessage("موضوع نمودار را بنویسید.");
    setBusy(true);
    const r = await run("/api/v1/visualize", {
      method: "POST",
      body: JSON.stringify({ kind: vizKind, prompt: vizPrompt, book_id: active.book_id }),
    });
    setBusy(false);
    if (!r.ok) return setMessage(phase6ErrorMessage(r.payload, "تولید نمودار ممکن نشد."));
    const block = (r.payload as { block: { type: string; content: string; metadata: Record<string, unknown> } }).block;
    const type = block.type as NotebookBlockType;
    setVizPrompt("");
    await addBlock(type, block.content, { title: String(block.metadata.title ?? ""), caption: String(block.metadata.caption ?? ""), citation: String(block.metadata.citation ?? "") });
  };

  const saveEdit = async () => {
    if (!active || editId === null) return;
    const r = await run(`/api/v1/notebooks/${active.id}/blocks/${editId}`, { method: "PATCH", body: JSON.stringify({ content: editText }) });
    if (!r.ok) return setMessage(phase6ErrorMessage(r.payload, "ذخیرهٔ بلوک ممکن نشد."));
    setEditId(null);
    await reload();
  };

  const deleteBlock = async (blockId: number) => {
    if (!active) return;
    await run(`/api/v1/notebooks/${active.id}/blocks/${blockId}`, { method: "DELETE" });
    await reload();
  };

  const propose = async (action: InlineAction) => {
    if (!active || !selection) return;
    setBusy(true);
    setMessage(null);
    const r = await run(`/api/v1/notebooks/${active.id}/blocks/${selection.blockId}/inline/propose`, {
      method: "POST",
      body: JSON.stringify({ action, selection: selection.text }),
    });
    setBusy(false);
    if (!r.ok) return setMessage(phase6ErrorMessage(r.payload, "پیشنهاد هوشمند ساخته نشد."));
    setProposal(r.payload as InlineProposal);
  };

  const decide = async (accept: boolean) => {
    if (!active || !proposal) return;
    const url = `/api/v1/notebooks/${active.id}/blocks/${proposal.block_id}/inline/${accept ? "accept" : "reject"}`;
    const r = await run(url, {
      method: "POST",
      body: JSON.stringify({ audit_id: proposal.audit_id, action: proposal.action, selection: proposal.selection }),
    });
    if (!r.ok && r.status !== 204) return setMessage(phase6ErrorMessage(r.payload, "ثبت تصمیم ممکن نشد."));
    setProposal(null);
    setSelection(null);
    await reload();
    if (accept && proposal.kind === "flashcard") setMessage("فلش‌کارت به دستهٔ «دفترچهٔ یادداشت هوشمند» اضافه شد.");
  };

  const exportMarkdown = async () => {
    if (!active) return;
    const res = await authFetch(`/api/v1/notebooks/${active.id}/export.md`);
    if (!res.ok) return setMessage("خروجی گرفتن ممکن نشد.");
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `${active.title}.md`;
    anchor.click();
    URL.revokeObjectURL(href);
  };

  const captureSelection = (blockId: number) => {
    const text = window.getSelection()?.toString().trim() ?? "";
    if (text.length >= 2 && text.length <= 1500) setSelection({ blockId, text });
  };

  return (
    <div className="notebook-workspace" dir="rtl" lang="fa">
      {message && <div role="alert" className="lb-caption">{message}</div>}

      <section className="glass-panel" aria-label="دفترچه‌ها">
        <h2>دفترچه‌های من</h2>
        <div className="notebook-create">
          <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="عنوان دفترچه" maxLength={255} />
          <BookGradePicker value={newBook} onChange={setNewBook} />
          <button type="button" className="btn-primary" onClick={create} disabled={busy}>
            <Plus size={15} /> <span>دفترچهٔ جدید</span>
          </button>
        </div>
        <ul className="notebook-list">
          {list.map((item) => (
            <li key={item.id}>
              <button type="button" className="btn-ghost" onClick={() => open(item.id)} aria-current={active?.id === item.id}>
                {item.title} <small>({toFaDigits(item.block_count ?? 0)} بلوک)</small>
              </button>
              <button type="button" className="btn-ghost" onClick={() => remove(item.id)} aria-label="حذف دفترچه">
                <Trash2 size={14} />
              </button>
            </li>
          ))}
          {list.length === 0 && (
            <li className="empty-state">
              <b>هنوز دفترچه‌ای ندارید</b>
              <span>با ساخت یک دفترچه، یادداشت‌ها و نمودارهای درسی‌تان را جمع کنید.</span>
            </li>
          )}
        </ul>
      </section>

      {active && (
        <section className="glass-panel" aria-label="ویرایشگر دفترچه">
          <header className="notebook-head">
            <h2>{active.title}</h2>
            <button type="button" className="btn-ghost" onClick={exportMarkdown}>
              <Download size={15} /> <span>خروجی Markdown</span>
            </button>
          </header>

          {selection && (
            <div className="notebook-selection" role="toolbar" aria-label="اقدامات متن انتخاب‌شده">
              <p className="lb-caption">متن انتخاب‌شده: «{selection.text.slice(0, 120)}»</p>
              {(Object.keys(INLINE_ACTION_LABELS) as InlineAction[]).map((action) => (
                <button key={action} type="button" className="btn-ghost" onClick={() => propose(action)} disabled={busy}>
                  <Sparkles size={14} /> <span>{INLINE_ACTION_LABELS[action]}</span>
                </button>
              ))}
              <AudioButton text={selection.text} bookId={active.book_id} label="خواندن متن" />
            </div>
          )}

          {proposal && (
            <div className="notebook-proposal" aria-label="پیشنهاد هوشمند">
              <h3>پیشنهاد: {INLINE_ACTION_LABELS[proposal.action]}</h3>
              {proposal.kind === "text" ? (
                <DiffViewer beforeText={proposal.selection} afterText={String(proposal.proposed)} title="تفاوت پیشنهاد" />
              ) : (
                <div>
                  <p><strong>روی کارت:</strong> {(proposal.proposed as { front: string }).front}</p>
                  <p><strong>پشت کارت:</strong> {(proposal.proposed as { back: string }).back}</p>
                </div>
              )}
              {proposal.citations.length > 0 && (
                <p className="lb-caption">منبع: {proposal.citations.join("؛ ")}</p>
              )}
              <div className="notebook-decision">
                <button type="button" className="btn-primary" onClick={() => decide(true)}>پذیرش</button>
                <button type="button" className="btn-ghost" onClick={() => decide(false)}>رد</button>
              </div>
            </div>
          )}

          <ol className="notebook-blocks">
            {active.blocks.map((block: NotebookBlockItem) => (
              <li key={block.id} className="notebook-block" onMouseUp={() => captureSelection(block.id)}>
                {editId === block.id ? (
                  <div>
                    <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={4} />
                    <button type="button" className="btn-primary" onClick={saveEdit}>ذخیره</button>
                    <button type="button" className="btn-ghost" onClick={() => setEditId(null)}>انصراف</button>
                  </div>
                ) : (
                  <>
                    {block.block_type === "comparison_table" ? (
                      <ComparisonTableView content={block.content} />
                    ) : (
                      <LearningBlockRenderer
                        blocks={[{ type: block.block_type, content: block.content, metadata: block.metadata }]}
                      />
                    )}
                    {typeof block.metadata.citation === "string" && <p className="lb-caption">منبع: {block.metadata.citation}</p>}
                    <div className="notebook-block-actions">
                      <span className="lb-caption">{BLOCK_LABELS[block.block_type]}</span>
                      {TEXT_EDITABLE.includes(block.block_type) && (
                        <button type="button" className="btn-ghost" onClick={() => { setEditId(block.id); setEditText(block.content); }} aria-label="ویرایش">
                          <Pencil size={13} />
                        </button>
                      )}
                      {INLINE_TEXT.includes(block.block_type) && (
                        <AudioButton text={block.content} bookId={active.book_id} label="پخش" />
                      )}
                      <button type="button" className="btn-ghost" onClick={() => deleteBlock(block.id)} aria-label="حذف بلوک">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ol>
          {active.blocks.length === 0 && <p className="lb-caption">هنوز بلوکی ندارید. متنی را بنویسید یا نموداری بسازید.</p>}

          <div className="notebook-add">
            <h3>افزودن بلوک</h3>
            <select value={newType} onChange={(e) => setNewType(e.target.value as NotebookBlockType)} aria-label="نوع بلوک">
              {(Object.keys(BLOCK_LABELS) as NotebookBlockType[]).map((type) => (
                <option key={type} value={type}>{BLOCK_LABELS[type]}</option>
              ))}
            </select>
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              rows={4}
              dir="auto"
              placeholder={newType === "comparison_table" ? TABLE_TEMPLATE : "محتوا"}
            />
            <button type="button" className="btn-primary" onClick={submitNewBlock} disabled={busy}>افزودن</button>
          </div>

          <div className="notebook-viz">
            <h3>تولید نمودار از کتاب</h3>
            <select value={vizKind} onChange={(e) => setVizKind(e.target.value as "mermaid" | "svg" | "table")} aria-label="نوع نمودار">
              <option value="mermaid">Mermaid</option>
              <option value="svg">SVG</option>
              <option value="table">جدول مقایسه</option>
            </select>
            <input value={vizPrompt} onChange={(e) => setVizPrompt(e.target.value)} placeholder="مثلاً: مفاهیم نیرو و شتاب" maxLength={500} />
            <button type="button" className="btn-primary" onClick={generateVisual} disabled={busy || !active.book_id}>
              ساخت نمودار
            </button>
            {!active.book_id && <p className="lb-caption">برای ساخت نمودار، دفترچه را به یک کتاب وصل کنید.</p>}
          </div>
        </section>
      )}
    </div>
  );
}

/** Comparison table from validated JSON (`headers`, `rows`). Cells are plain text (React escapes them). */
function ComparisonTableView({ content }: { content: string }) {
  let table: { headers?: unknown; rows?: unknown } = {};
  try {
    table = JSON.parse(content) as { headers?: unknown; rows?: unknown };
  } catch {
    return <p className="lb-caption">جدول نامعتبر است.</p>;
  }
  const headers = Array.isArray(table.headers) ? table.headers.map((cell) => String(cell)) : [];
  const rows = Array.isArray(table.rows)
    ? table.rows.map((row) => (Array.isArray(row) ? row.map((cell) => String(cell)) : []))
    : [];
  return (
    <div className="lb-table-wrap" dir="rtl">
      <table className="admin-table">
        <thead>
          <tr>{headers.map((header, i) => <th key={i}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>{row.map((cell, c) => <td key={c}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
