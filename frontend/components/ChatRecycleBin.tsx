"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, RotateCcw, Search, Trash2, X } from "lucide-react";
import type { AuthFetch } from "@/lib/tutorStream";

type ChatSummary = {
  id: string;
  title: string;
  book_title: string | null;
  mode: string;
  updated_at: string | null;
  deleted_at?: string | null;
  match?: { snippet: string; role: string | null };
};

type Props = {
  authFetch: AuthFetch;
  lang: "fa" | "en";
  initialTab?: "search" | "bin";
  onOpenChat: (chatId: string) => void;
  onChanged: () => void;
  onClose: () => void;
};

/** Student-side chat search and Recycle Bin (soft delete with restore). */
export default function ChatRecycleBin({
  authFetch,
  lang,
  initialTab = "search",
  onOpenChat,
  onChanged,
  onClose,
}: Props) {
  const en = lang === "en";
  const [tab, setTab] = useState<"search" | "bin">(initialTab);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChatSummary[]>([]);
  const [searched, setSearched] = useState(false);
  const [bin, setBin] = useState<ChatSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // Inline (single caller) and defer one microtask: effects run after paint and
    // microtasks run before the next paint, so the load sequence is unchanged — it is
    // just not synchronous inside the effect (React 19 cascading-render rule).
    if (tab !== "bin") return;
    void (async () => {
      await Promise.resolve();
      setBusy(true);
      try {
        const response = await authFetch("/api/v1/tutor/sessions/trash");
        if (response.ok) setBin((await response.json()) as ChatSummary[]);
        else setError(en ? "Could not load the recycle bin." : "سطل بازیافت بارگذاری نشد.");
      } catch {
        setError(en ? "Network error." : "خطای شبکه.");
      } finally {
        setBusy(false);
      }
    })();
  }, [tab, authFetch, en]);

  const runSearch = async () => {
    const needle = query.trim();
    setError("");
    if (!needle) {
      setResults([]);
      setSearched(false);
      return;
    }
    setBusy(true);
    try {
      const params = new URLSearchParams({ q: needle });
      const response = await authFetch(`/api/v1/tutor/sessions/search?${params.toString()}`);
      if (!response.ok) throw new Error("search failed");
      const payload = (await response.json()) as { results: Array<ChatSummary & { match: ChatSummary["match"] }> };
      setResults(payload.results);
      setSearched(true);
    } catch {
      setError(en ? "Search failed. Try again." : "جستجو انجام نشد. دوباره تلاش کن.");
    } finally {
      setBusy(false);
    }
  };

  const restore = async (chatId: string) => {
    setError("");
    const response = await authFetch(`/api/v1/tutor/sessions/${chatId}/restore`, { method: "POST" });
    if (!response.ok) {
      setError(en ? "Restore failed." : "بازیابی انجام نشد.");
      return;
    }
    setBin((prev) => prev.filter((item) => item.id !== chatId));
    onChanged();
  };

  const purge = async (chatId: string) => {
    if (!window.confirm(en ? "This chat will be deleted permanently. Continue?" : "این گفت‌وگو برای همیشه حذف شود؟")) {
      return;
    }
    setError("");
    const response = await authFetch(`/api/v1/tutor/sessions/${chatId}/permanent`, { method: "DELETE" });
    if (!response.ok) {
      setError(en ? "Permanent delete failed." : "حذف دائمی انجام نشد.");
      return;
    }
    setBin((prev) => prev.filter((item) => item.id !== chatId));
  };

  return (
    <div className="chat-bin-overlay" role="dialog" aria-modal="true" aria-label={en ? "Chat search" : "جستجو و سطل بازیافت"}>
      <div className="chat-bin-panel">
        <div className="chat-bin-head">
          <div className="chat-bin-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "search"}
              className={tab === "search" ? "selected" : ""}
              onClick={() => setTab("search")}
            >
              <Search size={14} /> {en ? "Search" : "جستجو"}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "bin"}
              className={tab === "bin" ? "selected" : ""}
              onClick={() => setTab("bin")}
            >
              <Trash2 size={14} /> {en ? "Recycle Bin" : "سطل بازیافت"}
            </button>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={en ? "Close" : "بستن"}>
            <X size={18} />
          </button>
        </div>

        {error && <div className="notice-error">{error}</div>}

        {tab === "search" ? (
          <div className="chat-bin-body">
            <form
              className="chat-search-form"
              onSubmit={(event) => {
                event.preventDefault();
                void runSearch();
              }}
            >
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={en ? "Search your chats…" : "در گفت‌وگوهایت جستجو کن…"}
                maxLength={120}
                aria-label={en ? "Search query" : "عبارت جستجو"}
              />
              <button type="submit" disabled={busy || !query.trim()}>
                {busy ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}
              </button>
            </form>
            {searched && results.length === 0 && (
              <p className="chat-bin-empty">{en ? "No chats matched." : "گفت‌وگویی با این عبارت پیدا نشد."}</p>
            )}
            <ul className="chat-bin-list">
              {results.map((item) => (
                <li key={item.id}>
                  <button type="button" className="chat-bin-item" onClick={() => onOpenChat(item.id)}>
                    <strong>{item.title}</strong>
                    {item.book_title && <span>{item.book_title}</span>}
                    {item.match?.snippet && <em>{item.match.snippet}</em>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="chat-bin-body">
            <p className="chat-bin-hint">
              {en
                ? "Deleted chats stay here until you restore or permanently delete them."
                : "گفت‌وگوهای حذف‌شده تا زمان بازیابی یا حذف دائمی اینجا می‌مانند."}
            </p>
            {bin.length === 0 && !busy && (
              <p className="chat-bin-empty">{en ? "The recycle bin is empty." : "سطل بازیافت خالی است."}</p>
            )}
            <ul className="chat-bin-list">
              {bin.map((item) => (
                <li key={item.id} className="chat-bin-row">
                  <div className="chat-bin-item static">
                    <strong>{item.title}</strong>
                    {item.book_title && <span>{item.book_title}</span>}
                  </div>
                  <div className="chat-bin-actions">
                    <button type="button" onClick={() => void restore(item.id)}>
                      <RotateCcw size={14} /> {en ? "Restore" : "بازیابی"}
                    </button>
                    <button type="button" className="danger" onClick={() => void purge(item.id)}>
                      <Trash2 size={14} /> {en ? "Delete forever" : "حذف دائمی"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
