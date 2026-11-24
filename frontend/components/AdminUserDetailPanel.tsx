"use client";

import { useCallback, useEffect, useState } from "react";
import { Brain, Link2, Pencil, RotateCcw, Save, Trash2, X } from "lucide-react";

type MemoryItem = {
  id: number;
  layer: "L1" | "L2" | "L3";
  kind: string;
  book_id: number | null;
  chapter_number: number | null;
  session_id: string | null;
  topic_key: string | null;
  content_fa: string;
  evidence_count: number;
  source_type: string | null;
  created_by: string;
  edited_by_admin: boolean;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type MemoryResponse = {
  user: { id: string; phone_number: string; full_name: string | null; grade_level: number | null; major: string | null };
  counts: { L1: number; L2: number; L3: number };
  items: MemoryItem[];
};

type BookRow = { id: number; title: string; grade_number: number | null; major_code: string | null };

type ConceptEnd = { book_id: number; book_title: string | null; grade_number: number | null; chapter_number: number };
type ConceptLink = { id: number; relation: string; label_fa: string; source: ConceptEnd; target: ConceptEnd };

type DeletedChat = {
  id: string;
  title: string;
  book_title: string | null;
  mode: string;
  message_count: number;
  deleted_at: string | null;
};

type Auth = { authHeaders: Record<string, string>; onUnauthorized: () => void };

const KIND_LABELS: Record<string, string> = {
  mastered: "تسلط",
  weak: "ضعف",
  note: "یادداشت",
  profile: "پروفایل",
  turn: "نوبت گفت‌وگو",
};

const RELATION_LABELS: Record<string, string> = {
  same_concept: "مفهوم یکسان",
  prerequisite: "پیش‌نیاز",
  related: "مرتبط",
};

const SOURCE_LABELS: Record<string, string> = {
  chat: "گفت‌وگو",
  quiz: "آزمون",
  flashcard: "فلش‌کارت",
  rollup: "جمع‌بندی خودکار",
  admin: "مدیر",
};

function formatWhen(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("fa-IR");
}

/** Phase 4 admin user page: Memory Inspector (L1/L2/L3), deleted chats, concept links. */
export default function AdminUserDetailPanel({
  userId,
  authHeaders,
  onUnauthorized,
}: Auth & { userId: string }) {
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [books, setBooks] = useState<BookRow[]>([]);
  const [links, setLinks] = useState<ConceptLink[]>([]);
  const [deleted, setDeleted] = useState<DeletedChat[]>([]);
  const [tab, setTab] = useState<"memory" | "bin">("memory");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [newFact, setNewFact] = useState({ kind: "note", book_id: "", chapter: "", topic: "", content: "" });
  const [linkForm, setLinkForm] = useState({
    source_book_id: "",
    source_chapter: "",
    relation: "same_concept",
    target_book_id: "",
    target_chapter: "",
    label_fa: "",
  });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  const loadMemory = useCallback(async () => {
    const response = await fetch(`/api/v1/admin/users/${userId}/memory`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    if (!response.ok) throw new Error("memory");
    setMemory((await response.json()) as MemoryResponse);
  }, [authHeaders, onUnauthorized, userId]);

  const loadLinks = useCallback(async () => {
    const [linkRes, bookRes] = await Promise.all([
      fetch("/api/v1/admin/concept-links", { cache: "no-store", credentials: "same-origin", headers: authHeaders }),
      fetch("/api/v1/admin/books", { cache: "no-store", credentials: "same-origin", headers: authHeaders }),
    ]);
    if (linkRes.status === 401 || linkRes.status === 403) return onUnauthorized();
    if (linkRes.ok) setLinks(((await linkRes.json()) as { items: ConceptLink[] }).items);
    if (bookRes.ok) setBooks((await bookRes.json()) as BookRow[]);
  }, [authHeaders, onUnauthorized]);

  const loadDeleted = useCallback(async () => {
    const response = await fetch(`/api/v1/admin/chat-sessions?status=deleted&user_id=${userId}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.ok) setDeleted(((await response.json()) as { items: DeletedChat[] }).items);
  }, [authHeaders, userId]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        await Promise.all([loadMemory(), loadLinks(), loadDeleted()]);
      } catch {
        if (active) setError("بارگذاری اطلاعات کاربر انجام نشد.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [loadMemory, loadLinks, loadDeleted]);

  const flash = (text: string) => {
    setNotice(text);
    setError("");
    window.setTimeout(() => setNotice(""), 2500);
  };

  const putItems = async (items: Record<string, unknown>[]) => {
    const response = await fetch(`/api/v1/admin/users/${userId}/memory`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders },
      credentials: "same-origin",
      body: JSON.stringify({ items }),
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    const payload = (await response.json().catch(() => ({}))) as { detail?: string } & Partial<MemoryResponse>;
    if (!response.ok) {
      setError(payload.detail ?? "ذخیرهٔ حافظه انجام نشد.");
      return;
    }
    setMemory(payload as MemoryResponse);
    flash("ذخیره شد. این ویرایش دست‌نخورده می‌ماند و در به‌روزرسانی خودکار بازنویسی نمی‌شود.");
  };

  const saveEdit = async (item: MemoryItem) => {
    const text = draftText.trim();
    if (!text) return;
    await putItems([{ id: item.id, layer: item.layer, kind: item.kind, content_fa: text }]);
    setEditingId(null);
  };

  const deleteItem = async (item: MemoryItem) => {
    if (!window.confirm("این مورد حافظه حذف شود؟")) return;
    const response = await fetch(`/api/v1/admin/users/${userId}/memory?memory_id=${item.id}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    if (!response.ok) {
      setError("حذف انجام نشد.");
      return;
    }
    await loadMemory();
    flash("مورد حافظه حذف شد.");
  };

  const resetMemory = async () => {
    if (!window.confirm("کل حافظهٔ این کاربر (L1، L2 و L3) پاک شود؟ این کار برگشت‌پذیر نیست.")) return;
    const response = await fetch(`/api/v1/admin/users/${userId}/memory`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    if (response.ok) {
      await loadMemory();
      flash("حافظه بازنشانی شد.");
    }
  };

  const addFact = async () => {
    const content = newFact.content.trim();
    if (!content) return;
    await putItems([
      {
        layer: "L2",
        kind: newFact.kind,
        book_id: newFact.book_id ? Number(newFact.book_id) : null,
        chapter_number: newFact.chapter ? Number(newFact.chapter) : null,
        topic_key: newFact.topic.trim() || null,
        content_fa: content,
      },
    ]);
    setNewFact({ kind: "note", book_id: "", chapter: "", topic: "", content: "" });
  };

  const createLink = async () => {
    const response = await fetch("/api/v1/admin/concept-links", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      credentials: "same-origin",
      body: JSON.stringify({
        source_book_id: Number(linkForm.source_book_id),
        source_chapter: Number(linkForm.source_chapter),
        target_book_id: Number(linkForm.target_book_id),
        target_chapter: Number(linkForm.target_chapter),
        relation: linkForm.relation,
        label_fa: linkForm.label_fa,
      }),
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    const payload = (await response.json().catch(() => ({}))) as { detail?: string };
    if (!response.ok) {
      setError(payload.detail ?? "ثبت پیوند انجام نشد.");
      return;
    }
    setLinkForm((prev) => ({ ...prev, source_chapter: "", target_chapter: "", label_fa: "" }));
    await loadLinks();
    flash("پیوند مفهومی ثبت شد.");
  };

  const deleteLink = async (linkId: number) => {
    if (!window.confirm("این پیوند حذف شود؟")) return;
    const response = await fetch(`/api/v1/admin/concept-links/${linkId}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.ok) await loadLinks();
  };

  if (loading) return <div className="admin-panel p4-admin">در حال بارگذاری…</div>;
  if (!memory) return <div className="admin-panel p4-admin inline-error">{error || "کاربر یافت نشد."}</div>;

  const l2 = memory.items.filter((item) => item.layer === "L2");
  const l3 = memory.items.filter((item) => item.layer === "L3");
  const l1 = memory.items.filter((item) => item.layer === "L1");
  const bookTitle = (id: number | null) => books.find((book) => book.id === id)?.title ?? (id ? `کتاب #${id}` : "کلی");

  return (
    <div className="admin-panel p4-admin">
      <div className="admin-panel-header">
        <div>
          <h2>
            <Brain size={18} /> {memory.user.full_name || memory.user.phone_number}
          </h2>
          <p className="admin-muted">
            {memory.user.phone_number}
            {memory.user.grade_level ? ` · پایه ${memory.user.grade_level}` : ""}
            {memory.user.major ? ` · ${memory.user.major}` : ""}
          </p>
        </div>
        <div className="p4-counts">
          <span className="admin-chip-btn">L1 · {memory.counts.L1}</span>
          <span className="admin-chip-btn">L2 · {memory.counts.L2}</span>
          <span className="admin-chip-btn">L3 · {memory.counts.L3}</span>
        </div>
      </div>

      {notice && <div className="admin-success">{notice}</div>}
      {error && <div className="inline-error">{error}</div>}

      <div className="p4-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "memory"} className={tab === "memory" ? "selected" : ""} onClick={() => setTab("memory")}>
          بازرس حافظه
        </button>
        <button type="button" role="tab" aria-selected={tab === "bin"} className={tab === "bin" ? "selected" : ""} onClick={() => setTab("bin")}>
          گفت‌وگوهای حذف‌شده ({deleted.length})
        </button>
      </div>

      {tab === "memory" ? (
        <div className="p4-memory">
          <section className="p4-layer" data-layer="L3">
            <h3>L3 · پروفایل بلندمدت</h3>
            {l3.length === 0 && <p className="admin-muted">هنوز پروفایلی ساخته نشده است.</p>}
            {l3.map((item) => (
              <article key={item.id} className="p4-item">
                <div className="p4-item-meta">
                  <span>{item.edited_by_admin ? "ویرایش مدیر" : SOURCE_LABELS[item.source_type ?? ""] ?? "خودکار"}</span>
                  <span>به‌روزرسانی: {formatWhen(item.updated_at)}</span>
                </div>
                {editingId === item.id ? (
                  <textarea value={draftText} onChange={(event) => setDraftText(event.target.value)} rows={3} />
                ) : (
                  <p>{item.content_fa}</p>
                )}
                <div className="p4-item-actions">
                  {editingId === item.id ? (
                    <>
                      <button type="button" className="admin-chip-btn" onClick={() => void saveEdit(item)}>
                        <Save size={13} /> ذخیره
                      </button>
                      <button type="button" className="admin-chip-btn" onClick={() => setEditingId(null)}>
                        <X size={13} /> انصراف
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="admin-chip-btn"
                      onClick={() => {
                        setEditingId(item.id);
                        setDraftText(item.content_fa);
                      }}
                    >
                      <Pencil size={13} /> ویرایش
                    </button>
                  )}
                </div>
              </article>
            ))}
          </section>

          <section className="p4-layer" data-layer="L2">
            <h3>L2 · واقعیت‌های هر کتاب و فصل</h3>
            {l2.length === 0 && <p className="admin-muted">هنوز واقعیتی ثبت نشده است.</p>}
            {l2.map((item) => (
              <article key={item.id} className={`p4-item kind-${item.kind}`}>
                <div className="p4-item-meta">
                  <span className="p4-kind">{KIND_LABELS[item.kind] ?? item.kind}</span>
                  <span>{bookTitle(item.book_id)}</span>
                  {item.chapter_number !== null && <span>فصل {item.chapter_number}</span>}
                  <span>شواهد: {item.evidence_count}</span>
                  <span>منبع: {SOURCE_LABELS[item.source_type ?? ""] ?? item.source_type ?? "—"}</span>
                  {item.edited_by_admin && <span className="p4-admin-badge">ویرایش مدیر</span>}
                </div>
                {editingId === item.id ? (
                  <textarea value={draftText} onChange={(event) => setDraftText(event.target.value)} rows={2} />
                ) : (
                  <p>{item.content_fa}</p>
                )}
                <div className="p4-item-actions">
                  {editingId === item.id ? (
                    <>
                      <button type="button" className="admin-chip-btn" onClick={() => void saveEdit(item)}>
                        <Save size={13} /> ذخیره
                      </button>
                      <button type="button" className="admin-chip-btn" onClick={() => setEditingId(null)}>
                        <X size={13} /> انصراف
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="admin-chip-btn"
                      onClick={() => {
                        setEditingId(item.id);
                        setDraftText(item.content_fa);
                      }}
                    >
                      <Pencil size={13} /> ویرایش
                    </button>
                  )}
                  <button type="button" className="admin-chip-btn danger" onClick={() => void deleteItem(item)}>
                    <Trash2 size={13} /> حذف
                  </button>
                </div>
              </article>
            ))}

            <div className="p4-new-fact">
              <h4>افزودن واقعیت (توسط مدیر)</h4>
              <div className="p4-form-row">
                <select value={newFact.kind} onChange={(event) => setNewFact({ ...newFact, kind: event.target.value })}>
                  <option value="note">یادداشت</option>
                  <option value="mastered">تسلط</option>
                  <option value="weak">ضعف</option>
                </select>
                <select value={newFact.book_id} onChange={(event) => setNewFact({ ...newFact, book_id: event.target.value })}>
                  <option value="">بدون کتاب (کلی)</option>
                  {books.map((book) => (
                    <option key={book.id} value={book.id}>
                      {book.title} · پایه {book.grade_number ?? "؟"}
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  min={1}
                  max={60}
                  placeholder="فصل"
                  value={newFact.chapter}
                  onChange={(event) => setNewFact({ ...newFact, chapter: event.target.value })}
                />
                <input
                  placeholder="موضوع کوتاه"
                  value={newFact.topic}
                  onChange={(event) => setNewFact({ ...newFact, topic: event.target.value })}
                />
              </div>
              <textarea
                rows={2}
                placeholder="متن واقعیت به فارسی"
                value={newFact.content}
                onChange={(event) => setNewFact({ ...newFact, content: event.target.value })}
              />
              <button type="button" className="admin-chip-btn" onClick={() => void addFact()}>
                افزودن
              </button>
            </div>
          </section>

          <section className="p4-layer" data-layer="L1">
            <h3>L1 · ردپای نشست‌ها (فقط خواندنی)</h3>
            {l1.length === 0 && <p className="admin-muted">ردپای نشستی ثبت نشده است.</p>}
            <details>
              <summary>نمایش {l1.length} نوبت اخیر</summary>
              <ul className="p4-trace">
                {l1.map((item) => (
                  <li key={item.id}>
                    <span dir="ltr">{item.session_id?.slice(0, 8)}</span> · {item.content_fa}
                  </li>
                ))}
              </ul>
            </details>
          </section>

          <div className="p4-reset">
            <button type="button" className="admin-chip-btn danger" onClick={() => void resetMemory()}>
              <RotateCcw size={13} /> بازنشانی کل حافظه
            </button>
          </div>
        </div>
      ) : (
        <div className="p4-bin">
          {deleted.length === 0 && <p className="admin-muted">گفت‌وگوی حذف‌شده‌ای وجود ندارد.</p>}
          <ul className="p4-trace">
            {deleted.map((chat) => (
              <li key={chat.id}>
                <strong>{chat.title}</strong> · {chat.book_title ?? "—"} · {chat.message_count} پیام · حذف:{" "}
                {formatWhen(chat.deleted_at)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <section className="p4-layer p4-links">
        <h3>
          <Link2 size={16} /> پیوندهای مفهومی بین پایه‌ها (Konkoor)
        </h3>
        <p className="admin-muted">
          پیوند فصل‌ها به هم اجازه می‌دهد جستجوی چندپایه، منبع‌های مرتبط از پایهٔ دیگر را هم پیدا کند. هر پیوند فقط
          با تأیید مدیر ساخته می‌شود.
        </p>
        <ul className="p4-trace">
          {links.map((link) => (
            <li key={link.id}>
              <span>
                {link.source.book_title} · فصل {link.source.chapter_number} (پایه {link.source.grade_number})
              </span>{" "}
              ⟷{" "}
              <span>
                {link.target.book_title} · فصل {link.target.chapter_number} (پایه {link.target.grade_number})
              </span>{" "}
              <em>{RELATION_LABELS[link.relation] ?? link.relation}</em>
              {link.label_fa && <> · {link.label_fa}</>}{" "}
              <button type="button" className="admin-chip-btn danger" onClick={() => void deleteLink(link.id)}>
                <Trash2 size={12} /> حذف
              </button>
            </li>
          ))}
          {links.length === 0 && <li className="admin-muted">پیوندی ثبت نشده است.</li>}
        </ul>
        <div className="p4-form-grid">
          <select value={linkForm.source_book_id} onChange={(event) => setLinkForm({ ...linkForm, source_book_id: event.target.value })}>
            <option value="">کتاب مبدأ</option>
            {books.map((book) => (
              <option key={book.id} value={book.id}>
                {book.title} · پایه {book.grade_number ?? "؟"}
              </option>
            ))}
          </select>
          <input type="number" min={1} max={60} placeholder="فصل مبدأ" value={linkForm.source_chapter} onChange={(event) => setLinkForm({ ...linkForm, source_chapter: event.target.value })} />
          <select value={linkForm.relation} onChange={(event) => setLinkForm({ ...linkForm, relation: event.target.value })}>
            <option value="same_concept">مفهوم یکسان</option>
            <option value="prerequisite">پیش‌نیاز</option>
            <option value="related">مرتبط</option>
          </select>
          <select value={linkForm.target_book_id} onChange={(event) => setLinkForm({ ...linkForm, target_book_id: event.target.value })}>
            <option value="">کتاب مقصد</option>
            {books.map((book) => (
              <option key={book.id} value={book.id}>
                {book.title} · پایه {book.grade_number ?? "؟"}
              </option>
            ))}
          </select>
          <input type="number" min={1} max={60} placeholder="فصل مقصد" value={linkForm.target_chapter} onChange={(event) => setLinkForm({ ...linkForm, target_chapter: event.target.value })} />
          <input placeholder="برچسب (اختیاری)" maxLength={255} value={linkForm.label_fa} onChange={(event) => setLinkForm({ ...linkForm, label_fa: event.target.value })} />
          <button
            type="button"
            className="admin-chip-btn"
            disabled={!linkForm.source_book_id || !linkForm.target_book_id || !linkForm.source_chapter || !linkForm.target_chapter}
            onClick={() => void createLink()}
          >
            ثبت پیوند
          </button>
        </div>
      </section>
    </div>
  );
}
