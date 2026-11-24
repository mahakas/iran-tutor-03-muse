/**
 * Persistent playback storage (Phase 04B).
 *
 * Where the "resume where you left off" record lives: `localStorage` under a
 * versioned, user-scoped key so two accounts on the same browser can never see
 * each other's playback position. Only non-sensitive fields are stored — no
 * tokens, cookies, signed URLs or blob: URLs (a blob URL would be dead after a
 * reload anyway; audio is always re-fetched through the authenticated endpoint).
 *
 * Chosen over IndexedDB because the app already caches preferences in
 * localStorage (`lib/preferences.ts`) and the record is a single small object.
 */

import { PLAYBACK_SPEEDS } from "./podcast";

const KEY_PREFIX = "darsyar:podcast:playback:v1:";

export type SavedPlayback = {
  episodeId: number;
  /** Last known playback position in seconds (never beyond the real duration). */
  position: number;
  speed: number;
  /** Whether audio was actively playing when this record was written. */
  wasPlaying: boolean;
  /** Epoch milliseconds of the last write. */
  updatedAt: number;
};

export function playbackStorageKey(userId: string): string {
  // The backend user id is a UUID; sanitize defensively so a hostile id can
  // never escape the key namespace.
  const safe = userId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64);
  return `${KEY_PREFIX}${safe}`;
}

/** Read + validate the saved record. Invalid/corrupt records are dropped. */
export function loadSavedPlayback(userId: string | null | undefined): SavedPlayback | null {
  if (!userId || typeof window === "undefined") return null;
  const key = playbackStorageKey(userId);
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<SavedPlayback> | null;
    const valid =
      parsed !== null &&
      typeof parsed === "object" &&
      typeof parsed.episodeId === "number" &&
      Number.isInteger(parsed.episodeId) &&
      parsed.episodeId >= 1 &&
      typeof parsed.position === "number" &&
      Number.isFinite(parsed.position) &&
      parsed.position >= 0;
    if (!valid) {
      window.localStorage.removeItem(key);
      return null;
    }
    const speed =
      typeof parsed.speed === "number" && (PLAYBACK_SPEEDS as readonly number[]).includes(parsed.speed)
        ? parsed.speed
        : 1;
    return {
      episodeId: parsed.episodeId as number,
      position: parsed.position as number,
      speed,
      wasPlaying: parsed.wasPlaying === true,
      updatedAt: typeof parsed.updatedAt === "number" ? parsed.updatedAt : 0,
    };
  } catch {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // ignore storage failures
    }
    return null;
  }
}

export function saveSavedPlayback(userId: string | null | undefined, state: SavedPlayback): void {
  if (!userId || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(playbackStorageKey(userId), JSON.stringify(state));
  } catch {
    // Quota/private-mode failures must never break playback.
  }
}

export function clearSavedPlayback(userId: string | null | undefined): void {
  if (!userId || typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(playbackStorageKey(userId));
  } catch {
    // ignore storage failures
  }
}
