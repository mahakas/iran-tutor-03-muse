"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Pause, Play, Volume2, X } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import { toast } from "@/lib/toast";
import {
  clearSavedPlayback,
  loadSavedPlayback,
  saveSavedPlayback,
} from "@/lib/podcastPlaybackStore";
import type { PodcastEpisode } from "@/lib/podcast";

/** One playable episode. `src` is a blob: URL created after an authenticated fetch,
 * so the private audio file is never exposed via a public path. `artworkUrl` is
 * optional and only used for MediaSession metadata when it is a valid image URL. */
export type PlayerTrack = {
  episodeId: number;
  title: string;
  subtitle?: string;
  src: string;
  artworkUrl?: string;
};

export type PodcastPlayerApi = {
  current: PlayerTrack | null;
  isPlaying: boolean;
  position: number;
  duration: number;
  speed: number;
  volume: number;
  load: (track: PlayerTrack, autoplay?: boolean) => void;
  toggle: () => void;
  seek: (time: number) => void;
  skip: (seconds: number) => void;
  setSpeed: (speed: number) => void;
  setVolume: (volume: number) => void;
  close: () => void;
};

const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2] as const;

/** Rate limit for writing the playback record on `timeupdate` (Phase 04B). */
const SAVE_INTERVAL_MS = 5000;
/** A position within this distance of the end counts as "already finished". */
const FINISHED_EPSILON_SECONDS = 1;
/** Default jump used by MediaSession seekbackward/seekforward handlers. */
const MEDIA_SEEK_SECONDS = 15;

const RESTORE_NOTICE_TEXT = "ادامهٔ پخش از موقعیت قبلی";

const PodcastPlayerContext = createContext<PodcastPlayerApi | null>(null);

export function usePodcastPlayer(): PodcastPlayerApi {
  const context = useContext(PodcastPlayerContext);
  if (!context) {
    throw new Error("usePodcastPlayer must be used inside PodcastPlayerProvider");
  }
  return context;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "۰:۰۰";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

function mediaSessionSupported(): boolean {
  return typeof navigator !== "undefined" && "mediaSession" in navigator;
}

/** Only a real http(s) or data:image URL may become cover art (Phase 04B rule). */
function artworkEntries(url: string | undefined): MediaImage[] | undefined {
  if (!url || typeof url !== "string") return undefined;
  if (!/^https?:\/\//i.test(url) && !/^data:image\//i.test(url)) return undefined;
  return [{ src: url, sizes: "512x512" }];
}

export default function PodcastPlayerProvider({ children }: { children: ReactNode }) {
  const { user, authFetch } = useAppContext();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [current, setCurrent] = useState<PlayerTrack | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeedState] = useState(1);
  const [volume, setVolumeState] = useState(1);
  const [restoreNotice, setRestoreNotice] = useState(false);

  // Mirrors of state for stable event handlers (registered once per element).
  const currentRef = useRef<PlayerTrack | null>(null);
  const speedRef = useRef(speed);
  const volumeRef = useRef(volume);
  const isPlayingRef = useRef(false);
  const lastSavedRef = useRef(0);
  /** Episode id claimed by an in-flight/finished restore; guards double restore. */
  const restoredEpisodeRef = useRef<number | null>(null);
  const authFetchRef = useRef(authFetch);
  const userIdRef = useRef<string | null>(null);

  const persist = useCallback((opts?: { force?: boolean; wasPlaying?: boolean }) => {
    const audio = audioRef.current;
    const track = currentRef.current;
    const userId = userIdRef.current;
    if (!audio || !track || !userId) return;
    const now = Date.now();
    if (!opts?.force && now - lastSavedRef.current < SAVE_INTERVAL_MS) return;
    lastSavedRef.current = now;
    saveSavedPlayback(userId, {
      episodeId: track.episodeId,
      position: Math.max(0, audio.currentTime || 0),
      speed: speedRef.current,
      wasPlaying: opts?.wasPlaying ?? isPlayingRef.current,
      updatedAt: now,
    });
  }, []);

  const persistRef = useRef(persist);

  const syncPositionState = useCallback(() => {
    if (!mediaSessionSupported()) return;
    const audio = audioRef.current;
    if (!audio || !currentRef.current) return;
    const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
    if (dur <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: dur,
        position: Math.min(Math.max(0, audio.currentTime), dur),
        playbackRate: audio.playbackRate > 0 ? audio.playbackRate : 1,
      });
    } catch {
      // Invalid values or unsupported operation must never break the player.
    }
  }, []);

  const syncPositionStateRef = useRef(syncPositionState);

  const clearSavedRef = useRef<(opts?: { wasPlaying?: boolean }) => void>(() => undefined);

  const ensureAudio = useCallback((): HTMLAudioElement => {
    if (!audioRef.current) {
      const element = new Audio();
      element.preload = "metadata";
      element.addEventListener("timeupdate", () => {
        setPosition(element.currentTime);
        persistRef.current();
        syncPositionStateRef.current();
      });
      element.addEventListener("durationchange", () =>
        setDuration(Number.isFinite(element.duration) ? element.duration : 0),
      );
      element.addEventListener("loadedmetadata", () => {
        setDuration(Number.isFinite(element.duration) ? element.duration : 0);
        syncPositionStateRef.current();
      });
      element.addEventListener("play", () => {
        isPlayingRef.current = true;
        setIsPlaying(true);
        syncPositionStateRef.current();
      });
      element.addEventListener("pause", () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        if (element.ended) {
          // The pause that accompanies the end of the file (Chromium fires
          // pause before ended) must not re-save a finished position after
          // the 'ended' handler has cleared the record.
          clearSavedRef.current();
          syncPositionStateRef.current();
          return;
        }
        // Pause is a deliberate stop: always write the last known position.
        persistRef.current({ force: true, wasPlaying: false });
        syncPositionStateRef.current();
      });
      element.addEventListener("ended", () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        clearSavedRef.current();
        syncPositionStateRef.current();
      });
      audioRef.current = element;
    }
    return audioRef.current;
  }, []);

  const load = useCallback(
    (track: PlayerTrack, autoplay = true) => {
      const audio = ensureAudio();
      const isSame = currentRef.current?.episodeId === track.episodeId;
      if (!isSame) {
        if (currentRef.current?.src.startsWith("blob:")) URL.revokeObjectURL(currentRef.current.src);
        audio.src = track.src;
        audio.load();
        setCurrent(track);
        currentRef.current = track;
        setPosition(0);
        setDuration(0);
      }
      audio.playbackRate = speedRef.current;
      audio.volume = volumeRef.current;
      if (autoplay) void audio.play().catch(() => undefined);
      else setIsPlaying(false);
    },
    [ensureAudio],
  );

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !current) return;
    if (audio.paused) void audio.play().catch(() => undefined);
    else audio.pause();
  }, [current]);

  const seek = useCallback((time: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Math.min(time, audio.duration || time));
    setPosition(audio.currentTime);
    persistRef.current({ force: true });
    syncPositionStateRef.current();
  }, []);

  const skip = useCallback(
    (seconds: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      seek(audio.currentTime + seconds);
    },
    [seek],
  );

  const setSpeed = useCallback((value: number) => {
    setSpeedState(value);
    speedRef.current = value;
    if (audioRef.current) audioRef.current.playbackRate = value;
    persistRef.current({ force: true });
    syncPositionStateRef.current();
  }, []);

  const setVolume = useCallback((value: number) => {
    setVolumeState(value);
    volumeRef.current = value;
    if (audioRef.current) audioRef.current.volume = value;
  }, []);

  const close = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if (currentRef.current?.src.startsWith("blob:")) URL.revokeObjectURL(currentRef.current.src);
    // Closing the player is an explicit dismissal: drop the resume record.
    clearSavedPlayback(userIdRef.current);
    setCurrent(null);
    currentRef.current = null;
    setPosition(0);
    setDuration(0);
    setIsPlaying(false);
    isPlayingRef.current = false;
    setRestoreNotice(false);
    restoredEpisodeRef.current = null;
  }, []);

  // Stable handles so event listeners and MediaSession handlers never go stale.
  const toggleRef = useRef(toggle);
  const seekRef = useRef(seek);
  const skipRef = useRef(skip);
  const closeRef = useRef(close);

  useEffect(() => {
    currentRef.current = current;
  }, [current]);

  useEffect(() => {
    speedRef.current = speed;
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed]);

  useEffect(() => {
    volumeRef.current = volume;
  }, [volume]);

  // Keep every ref mirror fresh after each commit (react-hooks/refs forbids
  // writing refs during render). Declared before the restore effect so the
  // mirrors are always up to date when it runs.
  useEffect(() => {
    authFetchRef.current = authFetch;
    userIdRef.current = user?.id ?? null;
    persistRef.current = persist;
    syncPositionStateRef.current = syncPositionState;
    toggleRef.current = toggle;
    seekRef.current = seek;
    skipRef.current = skip;
    closeRef.current = close;
  });

  // Keep the record fresh when the tab is hidden or the page is being left.
  useEffect(() => {
    const saveNow = () => persistRef.current({ force: true });
    const onPageHide = () => saveNow();
    const onVisibility = () => {
      if (typeof document !== "undefined" && document.hidden) saveNow();
    };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibility);
      saveNow();
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Restore after a full reload (Phase 04B Feature 1).
  // Runs once the signed-in user is known and nothing is currently playing.
  // ---------------------------------------------------------------------------
  const prevUserIdRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const userId = user?.id ?? null;
    const prev = prevUserIdRef.current;
    prevUserIdRef.current = userId;
    // Only a REAL account switch (A→B) or logout (A→null) wipes state. The
    // mount/login transition (null→A) must keep the saved record so the
    // restore below can offer "continue where you left off".
    const switchingAway = prev !== undefined && prev !== null && prev !== userId;
    if (switchingAway) {
      clearSavedPlayback(prev);
      closeRef.current();
    }
    if (!userId || currentRef.current || restoredEpisodeRef.current !== null) return;
    const saved = loadSavedPlayback(userId);
    if (!saved) return;
    restoredEpisodeRef.current = saved.episodeId;
    let cancelled = false;
    let metaHandler: (() => void) | null = null;
    void (async () => {
      try {
        const detailResp = await authFetchRef.current(`/api/v1/podcasts/${saved.episodeId}`);
        if (cancelled) return;
        if (!detailResp.ok) {
          // Deleted episode or no longer accessible: recover safely.
          if ([401, 403, 404].includes(detailResp.status)) clearSavedPlayback(userId);
          restoredEpisodeRef.current = null;
          return;
        }
        const detail = (await detailResp.json().catch(() => null)) as PodcastEpisode | null;
        if (cancelled) return;
        if (!detail || detail.status !== "completed" || !detail.has_audio) {
          // Audio not ready yet: tell the student, keep the saved position.
          toast.info("فایل صوتی این پادکست هنوز آماده نیست؛ موقعیت ذخیره‌شده حفظ شد.");
          restoredEpisodeRef.current = null;
          return;
        }
        const audioResp = await authFetchRef.current(`/api/v1/podcasts/${saved.episodeId}/audio`);
        if (cancelled) return;
        if (!audioResp.ok) {
          if ([401, 403, 404].includes(audioResp.status)) clearSavedPlayback(userId);
          else toast.error("دریافت فایل صوتی ناموفق بود؛ دوباره تلاش کنید.");
          restoredEpisodeRef.current = null;
          return;
        }
        const blob = await audioResp.blob();
        if (cancelled) return;
        const audio = ensureAudio();
        const track: PlayerTrack = {
          episodeId: detail.id,
          title: detail.title,
          subtitle: [detail.book_title, detail.format_label].filter(Boolean).join(" · "),
          src: URL.createObjectURL(blob),
        };
        if (currentRef.current?.src.startsWith("blob:")) URL.revokeObjectURL(currentRef.current.src);
        audio.src = track.src;
        audio.load();
        currentRef.current = track;
        setCurrent(track);
        setPosition(0);
        setDuration(0);
        setIsPlaying(false);
        isPlayingRef.current = false;
        audio.playbackRate = saved.speed;
        speedRef.current = saved.speed;
        setSpeedState(saved.speed);
        audio.volume = volumeRef.current;
        setRestoreNotice(true);
        // Restore the exact position once the real duration is known, so the
        // saved time can never exceed the file's true duration.
        const applySavedPosition = () => {
          if (metaHandler) {
            audio.removeEventListener("loadedmetadata", metaHandler);
            metaHandler = null;
          }
          const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
          setDuration(dur);
          let restored = saved.position;
          if (dur > 0) restored = Math.min(restored, dur);
          if (dur > 0 && saved.position >= dur - FINISHED_EPSILON_SECONDS) {
            // The episode had effectively finished: start fresh next time and
            // drop the now-pointless "continue" banner.
            clearSavedPlayback(userId);
            setRestoreNotice(false);
            restored = 0;
          }
          audio.currentTime = restored;
          setPosition(restored);
          syncPositionStateRef.current();
        };
        if (Number.isFinite(audio.duration) && audio.duration > 0) {
          applySavedPosition();
        } else {
          metaHandler = applySavedPosition;
          audio.addEventListener("loadedmetadata", applySavedPosition);
        }
      } catch {
        if (!cancelled) restoredEpisodeRef.current = null;
      }
    })();
    return () => {
      cancelled = true;
      if (metaHandler) {
        audioRef.current?.removeEventListener("loadedmetadata", metaHandler);
        metaHandler = null;
      }
    };
  }, [user?.id, ensureAudio]);

  const clearSavedNow = useCallback(() => {
    clearSavedPlayback(userIdRef.current);
  }, []);
  useEffect(() => {
    clearSavedRef.current = clearSavedNow;
  });
  const continueRestored = useCallback(() => {
    setRestoreNotice(false);
    const audio = audioRef.current;
    if (audio && currentRef.current) void audio.play().catch(() => undefined);
  }, []);

  const restartFromBeginning = useCallback(() => {
    setRestoreNotice(false);
    clearSavedPlayback(userIdRef.current);
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = 0;
    setPosition(0);
    // The record stays cleared; the next natural timeupdate/pause save starts
    // tracking from zero again.
    void audio.play().catch(() => undefined);
  }, []);

  // ---------------------------------------------------------------------------
  // MediaSession integration (Phase 04B Feature 2).
  // Action handlers are registered exactly once for the lifetime of the page and
  // always act on the single global audio element — never a parallel one.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!mediaSessionSupported()) return;
    const session = navigator.mediaSession;
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      ["play", () => toggleRef.current()],
      ["pause", () => toggleRef.current()],
      ["seekbackward", () => skipRef.current(-MEDIA_SEEK_SECONDS)],
      ["seekforward", () => skipRef.current(MEDIA_SEEK_SECONDS)],
      ["seekto", (details) => {
        const seekTime = (details as MediaSessionActionDetails | undefined)?.seekTime;
        if (typeof seekTime === "number" && Number.isFinite(seekTime)) seekRef.current(seekTime);
      }],
      // previoustrack/nexttrack are intentionally NOT registered: the player
      // has no real previous/next-episode concept yet.
    ];
    for (const [action, handler] of handlers) {
      try {
        session.setActionHandler(action, handler);
      } catch {
        // Unsupported action types must not break the player.
      }
    }
    return () => {
      for (const [action] of handlers) {
        try {
          session.setActionHandler(action, null);
        } catch {
          // ignore
        }
      }
    };
  }, []);

  useEffect(() => {
    if (!mediaSessionSupported() || typeof MediaMetadata === "undefined") return;
    try {
      if (!current) {
        navigator.mediaSession.metadata = null;
        return;
      }
      const artwork = artworkEntries(current.artworkUrl);
      navigator.mediaSession.metadata = new MediaMetadata({
        title: current.title,
        artist: current.subtitle || "درسیار",
        album: "درسیار",
        ...(artwork ? { artwork } : {}),
      });
    } catch {
      // Metadata failures must not break the player.
    }
  }, [current]);

  useEffect(() => {
    if (!mediaSessionSupported()) return;
    try {
      navigator.mediaSession.playbackState = !current
        ? "none"
        : isPlaying
          ? "playing"
          : "paused";
    } catch {
      // ignore
    }
  }, [current, isPlaying]);

  const api = useMemo<PodcastPlayerApi>(
    () => ({ current, isPlaying, position, duration, speed, volume, load, toggle, seek, skip, setSpeed, setVolume, close }),
    [current, isPlaying, position, duration, speed, volume, load, toggle, seek, skip, setSpeed, setVolume, close],
  );

  const progressPercent = duration > 0 ? Math.min(100, (position / duration) * 100) : 0;

  return (
    <PodcastPlayerContext.Provider value={api}>
      {children}
      {current && (
        <aside className="pc-mini" dir="rtl" aria-label="پخش‌کنندهٔ پادکست">
          {restoreNotice && (
            <div className="pc-restore" role="status">
              <span className="pc-restore-text">{RESTORE_NOTICE_TEXT}</span>
              <div className="pc-restore-actions">
                <button type="button" className="pc-restore-btn" onClick={continueRestored}>
                  ادامه
                </button>
                <button type="button" className="pc-restore-btn" onClick={restartFromBeginning}>
                  از ابتدا
                </button>
              </div>
            </div>
          )}
          <div className="pc-mini-info">
            <span className="pc-mini-title">{current.title}</span>
            {current.subtitle && <span className="pc-mini-sub">{current.subtitle}</span>}
          </div>
          <div className="pc-mini-controls">
            <button type="button" className="pc-mini-btn" onClick={toggle} aria-label={isPlaying ? "توقف پخش" : "پخش"}>
              {isPlaying ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <span className="pc-mini-time">
              {formatTime(position)} / {formatTime(duration)}
            </span>
            <button
              type="button"
              className="pc-mini-btn pc-mini-speed"
              onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed as (typeof SPEEDS)[number]) + 1) % SPEEDS.length])}
              aria-label="سرعت پخش"
              title="تغییر سرعت پخش"
            >
              {speed}×
            </button>
            <div className="pc-mini-volume" aria-hidden="true">
              <Volume2 size={14} />
            </div>
            <button type="button" className="pc-mini-btn" onClick={close} aria-label="بستن پخش‌کننده">
              <X size={16} />
            </button>
          </div>
          <div className="pc-mini-bar">
            <span style={{ width: `${progressPercent}%` }} />
          </div>
        </aside>
      )}
    </PodcastPlayerContext.Provider>
  );
}
