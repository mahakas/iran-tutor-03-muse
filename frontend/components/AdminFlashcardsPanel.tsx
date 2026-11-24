"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Eye, EyeOff, Globe2, ShieldCheck, Trash2 } from "lucide-react";
import MathContent from "@/components/MathContent";

type AdminStats = {
  decks: number;
  cards: number;
  reviews: number;
  public_decks: number;
  due_reviews_now: number;
  average_ease_factor: number | null;
  rating_distribution: Record<string, number>;
};

type AdminDeckRow = {
  id: number;
  title: string;
  source_type: string;
  is_public: boolean;
  admin_approved: boolean;
  created_at: string | null;
  owner: { id: string; name: string | null };
  card_count: number;
  review_count: number;
};

type AdminCard = { id: number; front_md: string; back_md: string; citations: { citation: string }[] };
type AdminDeckDetail = AdminDeckRow & { cards: AdminCard[] };

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

const SOURCE_LABELS: Record<string, string> = {
  book: "کتاب",
  chat: "گفت‌وگو",
  mistake: "اشتباهات آزمون",
  manual: "دستی",
};

/** Admin oversight of all flashcard decks, cards, review stats, and public-deck moderation. */
export default function AdminFlashcardsPanel({ authHeaders, onUnauthorized }: Props) {
  // Phase 06: deck filters persist in the URL (read on mount, mirrored on change).
  const urlParams = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search);
    } catch {
      return new URLSearchParams();
    }
  }, []);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [decks, setDecks] = useState<AdminDeckRow[]>([]);
  const [sourceFilter, setSourceFilter] = useState(urlParams.get("source") ?? "");
  const [publicOnly, setPublicOnly] = useState(urlParams.get("public") === "true");
  const [openDeck, setOpenDeck] = useState<AdminDeckDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (sourceFilter) params.set("source", sourceFilter);
      else params.delete("source");
      if (publicOnly) params.set("public", "true");
      else params.delete("public");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      // history is best-effort
    }
  }, [sourceFilter, publicOnly]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (sourceFilter) params.set("source_type", sourceFilter);
      if (publicOnly) params.set("public_only", "true");
      const [statsRes, decksRes] = await Promise.all([
        fetch("/api/v1/admin/flashcards/stats", { cache: "no-store", credentials: "same-origin", headers: authHeaders }),
        fetch(`/api/v1/admin/flashcards/decks?${params.toString()}`, {
          cache: "no-store",
          credentials: "same-origin",
          headers: authHeaders,
        }),
      ]);
      if ([statsRes.status, decksRes.status].some((code) => code === 401 || code === 403)) {
        onUnauthorized();
        return;
      }
      if (!statsRes.ok || !decksRes.ok) throw new Error("load failed");
      setStats((await statsRes.json()) as AdminStats);
      setDecks((await decksRes.json()) as AdminDeckRow[]);
      setError("");
    } catch {
      setError("بارگذاری فلش‌کارت‌ها ناموفق بود.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, onUnauthorized, publicOnly, sourceFilter]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    void load();
  }, [load]);

  async function moderate(deck: AdminDeckRow, next: { is_public: boolean; admin_approved: boolean }) {
    setError("");
    setNotice("");
    const response = await fetch(`/api/v1/admin/flashcards/decks/${deck.id}/moderation`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      setError(typeof payload?.detail === "string" ? payload.detail : "به‌روزرسانی ناموفق بود.");
      return;
    }
    setNotice(next.is_public ? "دسته به کتابخانهٔ عمومی منتشر شد." : "دسته از کتابخانهٔ عمومی خارج شد.");
    await load();
  }

  async function toggleDetail(deckId: number) {
    if (openDeck?.id === deckId) {
      setOpenDeck(null);
      return;
    }
    const response = await fetch(`/api/v1/admin/flashcards/decks/${deckId}`, {
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    if (response.ok) setOpenDeck((await response.json()) as AdminDeckDetail);
  }

  async function removeDeck(deck: AdminDeckRow) {
    if (!window.confirm(`دستهٔ «${deck.title}» برای همیشه حذف شود؟`)) return;
    const response = await fetch(`/api/v1/admin/flashcards/decks/${deck.id}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.status === 401 || response.status === 403) return onUnauthorized();
    if (!response.ok) {
      setError("حذف دسته ناموفق بود.");
      return;
    }
    setOpenDeck(null);
    setNotice("دسته حذف شد.");
    await load();
  }

  return (
    <section className="admin-panel fc-admin" dir="rtl">
      <header className="admin-panel-header">
        <h2>
          <ShieldCheck size={18} /> فلش‌کارت‌ها و مرور SM-2
        </h2>
        <p className="admin-muted">
          نظارت بر همهٔ دسته‌ها و کارت‌ها، آمار مرور دانش‌آموزان و تأیید یا حذف دسته‌های عمومی.
        </p>
      </header>

      {error && <div className="inline-error">{error}</div>}
      {notice && <div className="admin-success">{notice}</div>}

      {stats && (
        <div className="fc-admin-stats">
          <div><span>دسته‌ها</span><strong>{stats.decks}</strong></div>
          <div><span>کارت‌ها</span><strong>{stats.cards}</strong></div>
          <div><span>مرورها</span><strong>{stats.reviews}</strong></div>
          <div><span>سررسید امروز</span><strong>{stats.due_reviews_now}</strong></div>
          <div><span>عمومی و تأییدشده</span><strong>{stats.public_decks}</strong></div>
          <div>
            <span>میانگین ضریب آسانی</span>
            <strong>{stats.average_ease_factor ?? "—"}</strong>
          </div>
        </div>
      )}

      <div className="fc-admin-filters">
        <label>
          منبع
          <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
            <option value="">همه</option>
            {Object.entries(SOURCE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="fc-check">
          <input type="checkbox" checked={publicOnly} onChange={(event) => setPublicOnly(event.target.checked)} />
          فقط عمومی
        </label>
      </div>

      {loading && <p className="admin-muted">در حال بارگذاری…</p>}

      {!loading && (
        <div className="fc-admin-table-wrap">
          <table className="fc-admin-table">
            <thead>
              <tr>
                <th>عنوان</th>
                <th>مالک</th>
                <th>منبع</th>
                <th>کارت</th>
                <th>مرور</th>
                <th>وضعیت</th>
                <th>عملیات</th>
              </tr>
            </thead>
            <tbody>
              {decks.map((deck) => (
                <tr key={deck.id}>
                  <td>{deck.title}</td>
                  <td>{deck.owner.name ?? deck.owner.id}</td>
                  <td>{SOURCE_LABELS[deck.source_type] ?? deck.source_type}</td>
                  <td>{deck.card_count}</td>
                  <td>{deck.review_count}</td>
                  <td>
                    {deck.is_public && deck.admin_approved
                      ? "عمومی (تأییدشده)"
                      : deck.is_public
                      ? "عمومی (تأیید نشده)"
                      : "خصوصی"}
                  </td>
                  <td className="fc-admin-actions">
                    <button type="button" className="admin-chip-btn" onClick={() => void toggleDetail(deck.id)}>
                      {openDeck?.id === deck.id ? <EyeOff size={14} /> : <Eye size={14} />} کارت‌ها
                    </button>
                    {deck.is_public && deck.admin_approved ? (
                      <button
                        type="button"
                        className="admin-chip-btn"
                        onClick={() => void moderate(deck, { is_public: false, admin_approved: false })}
                      >
                        لغو انتشار
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="admin-chip-btn"
                        onClick={() => void moderate(deck, { is_public: true, admin_approved: true })}
                      >
                        <Globe2 size={14} /> تأیید و انتشار
                      </button>
                    )}
                    <button type="button" className="admin-chip-btn danger" onClick={() => void removeDeck(deck)}>
                      <Trash2 size={14} /> حذف
                    </button>
                  </td>
                </tr>
              ))}
              {decks.length === 0 && (
                <tr>
                  <td colSpan={7} className="admin-muted">هیچ دسته‌ای با این فیلتر وجود ندارد.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {openDeck && (
        <div className="fc-admin-detail">
          <h3>{openDeck.title}</h3>
          {openDeck.cards.length === 0 && <p className="admin-muted">کارتی وجود ندارد.</p>}
          {openDeck.cards.map((card) => (
            <article key={card.id} className="fc-admin-card">
              <MathContent content={card.front_md} />
              <div className="fc-back-preview">
                <MathContent content={card.back_md} />
              </div>
              {card.citations.map((cite, index) => (
                <span key={index} className="fc-cite-chip">{cite.citation}</span>
              ))}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
