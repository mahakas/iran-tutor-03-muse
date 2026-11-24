"use client";

import { useCallback, useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";

// ─── Student home data (Phase 02) ──────────────────────────────────────────────
// Every value comes from an existing, user-scoped endpoint. No synthetic
// counters: when a source fails, its own error flag turns on and the UI shows an
// honest "unavailable" state instead of a guess.

export type DeckLite = { id: number; title: string; due: number; total: number };
export type NotebookLite = { id: number; title: string; book_id: number | null; block_count: number };

export type StudentHomeData = {
  /** Real SM-2 due count (null = not loaded / capability off). */
  dueFlashcards: number | null;
  decks: DeckLite[] | null;
  notebooks: NotebookLite[] | null;
  /** Real unresolved-mistake count (null = not loaded / capability off). */
  openMistakes: number | null;
  loading: boolean;
  errors: { due: boolean; decks: boolean; notebooks: boolean; mistakes: boolean };
};

type Settled = { due: boolean; decks: boolean; notebooks: boolean; mistakes: boolean };

export type StudentHomeDataOptions = {
  /** True only when the user is authenticated AND the related capability is on. */
  flashcardsEnabled: boolean;
  mistakeBankEnabled: boolean;
  notebookEnabled: boolean;
};

const MISTAKE_UNRESOLVED_LIMIT = 1;

function extractCount(payload: unknown): number | null {
  if (payload && typeof payload === "object" && "due_count" in (payload as Record<string, unknown>)) {
    const value = (payload as { due_count: unknown }).due_count;
    return typeof value === "number" ? value : null;
  }
  if (payload && typeof payload === "object" && "total" in (payload as Record<string, unknown>)) {
    const value = (payload as { total: unknown }).total;
    return typeof value === "number" ? value : null;
  }
  return null;
}

export function useStudentHomeData({
  flashcardsEnabled,
  mistakeBankEnabled,
  notebookEnabled,
}: StudentHomeDataOptions): StudentHomeData {
  const { authFetch } = useAppContext();
  const [dueFlashcards, setDueFlashcards] = useState<number | null>(null);
  const [decks, setDecks] = useState<DeckLite[] | null>(null);
  const [notebooks, setNotebooks] = useState<NotebookLite[] | null>(null);
  const [openMistakes, setOpenMistakes] = useState<number | null>(null);
  const [errors, setErrors] = useState({ due: false, decks: false, notebooks: false, mistakes: false });
  const [settled, setSettled] = useState<Settled>({ due: false, decks: false, notebooks: false, mistakes: false });

  const markSettled = useCallback((keys: Array<keyof Settled>) => {
    setSettled((prev) => {
      const next = { ...prev };
      for (const key of keys) next[key] = true;
      return next;
    });
  }, []);

  const fetchFlashcards = useCallback(async () => {
    try {
      const dueRes = await authFetch("/api/v1/flashcards/due?limit=1");
      const duePayload = dueRes.ok ? await dueRes.json().catch(() => null) : null;
      setDueFlashcards(duePayload && dueRes.ok ? extractCount(duePayload) : null);
      if (!dueRes.ok) setErrors((prev) => ({ ...prev, due: true }));
      const decksRes = await authFetch("/api/v1/flashcards/decks");
      const decksPayload = decksRes.ok ? await decksRes.json().catch(() => null) : null;
      if (decksRes.ok && Array.isArray(decksPayload)) {
        setDecks(
          decksPayload.map((deck: Record<string, unknown>) => ({
            id: Number(deck.id),
            title: String(deck.title ?? ""),
            due: Number(deck.due ?? 0),
            total: Number(deck.total ?? 0),
          }))
        );
      } else {
        setDecks(null);
        setErrors((prev) => ({ ...prev, decks: true }));
      }
    } catch {
      setDueFlashcards(null);
      setDecks(null);
      setErrors((prev) => ({ ...prev, due: true, decks: true }));
    } finally {
      markSettled(["due", "decks"]);
    }
  }, [authFetch, markSettled]);

  const fetchNotebooks = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/notebooks");
      const payload = res.ok ? await res.json().catch(() => null) : null;
      // The endpoint returns {"items": [...]} (same envelope NotebookWorkspace
      // reads); tolerate a bare array defensively but never accept garbage.
      const list = Array.isArray(payload)
        ? payload
        : payload && typeof payload === "object" && Array.isArray((payload as { items?: unknown }).items)
          ? ((payload as { items: unknown[] }).items as Record<string, unknown>[])
          : null;
      if (res.ok && list) {
        setNotebooks(
          list.map((nb: Record<string, unknown>) => ({
            id: Number(nb.id),
            title: String(nb.title ?? ""),
            book_id: nb.book_id === null || nb.book_id === undefined ? null : Number(nb.book_id),
            block_count: Number(nb.block_count ?? 0),
          }))
        );
      } else {
        setNotebooks(null);
        setErrors((prev) => ({ ...prev, notebooks: true }));
      }
    } catch {
      setNotebooks(null);
      setErrors((prev) => ({ ...prev, notebooks: true }));
    } finally {
      markSettled(["notebooks"]);
    }
  }, [authFetch, markSettled]);

  const fetchMistakes = useCallback(async () => {
    try {
      const res = await authFetch(
        `/api/v1/mistakes?status=unresolved&limit=${MISTAKE_UNRESOLVED_LIMIT}`
      );
      const payload = res.ok ? await res.json().catch(() => null) : null;
      setOpenMistakes(res.ok ? extractCount(payload) : null);
      if (!res.ok) setErrors((prev) => ({ ...prev, mistakes: true }));
    } catch {
      setOpenMistakes(null);
      setErrors((prev) => ({ ...prev, mistakes: true }));
    } finally {
      markSettled(["mistakes"]);
    }
  }, [authFetch, markSettled]);

  const loading =
    (flashcardsEnabled && (!settled.due || !settled.decks)) ||
    (mistakeBankEnabled && !settled.mistakes) ||
    (notebookEnabled && !settled.notebooks);

  useEffect(() => {
    // Defer one microtask so the loads are not synchronous inside the effect
    // (react-hooks/set-state-in-effect; same shape as MistakeBankWorkspace/MasteryWorkspace).
    void (async () => {
      await Promise.resolve();
      if (flashcardsEnabled) await fetchFlashcards();
      if (mistakeBankEnabled) await fetchMistakes();
      if (notebookEnabled) await fetchNotebooks();
    })();
  }, [flashcardsEnabled, mistakeBankEnabled, notebookEnabled, fetchFlashcards, fetchMistakes, fetchNotebooks]);

  return { dueFlashcards, decks, notebooks, openMistakes, loading, errors };
}
