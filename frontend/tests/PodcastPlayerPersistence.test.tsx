/** Phase 04B: persistent playback + MediaSession integration tests.
 *
 * The provider's single audio element is captured by stubbing the global
 * `Audio` constructor with a factory over `document.createElement("audio")`,
 * so tests can dispatch real media events (timeupdate/pause/ended/loadedmetadata)
 * and inspect currentTime/playbackRate like a browser would.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PodcastPlayerProvider, {
  usePodcastPlayer,
  type PlayerTrack,
} from "@/components/PodcastPlayerProvider";
import { TOAST_EVENT } from "@/lib/toast";

const state = vi.hoisted(() => ({
  authFetch: vi.fn(),
  userId: null as string | null,
}));

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({
    user: state.userId ? { id: state.userId } : null,
    authFetch: (input: string, init?: RequestInit) => state.authFetch(input, init),
    getActiveToken: () => "test-token",
  }),
  buildUserAuthHeaders: (token: string | null) => ({ Authorization: `Bearer ${token}` }),
}));

const mediaSessionStub = vi.hoisted(() => {
  return {
    metadata: null as unknown,
    playbackState: "none",
    setPositionState: vi.fn(),
    setActionHandler: vi.fn(),
  };
});

function installMediaSession() {
  Object.defineProperty(window.navigator, "mediaSession", {
    value: mediaSessionStub,
    configurable: true,
  });
  (window as unknown as { MediaMetadata?: unknown }).MediaMetadata = class {
    init: unknown;
    constructor(init: unknown) {
      this.init = init;
    }
  };
}

const STORAGE_KEY = "darsyar:podcast:playback:v1:student-1";
const OTHER_KEY = "darsyar:podcast:playback:v1:student-2";

const EPISODE_DETAIL = {
  id: 11,
  title: "پادکست حرکت بر خط راست",
  description: "مرور فصل",
  format: "deep_dive",
  format_label: "گفت‌وگوی عمیق",
  language: "fa",
  length: "standard",
  book_id: 5,
  book_title: "فیزیک دهم",
  chapters: [2],
  status: "completed",
  progress: 100,
  progress_stage: "تکمیل",
  error_code: null,
  error_detail: null,
  duration_seconds: 200,
  byte_size: 120000,
  has_audio: true,
  single_speaker_mode: false,
  speakers: {},
  suggested_questions: [],
  created_at: "2026-11-23T09:00:00Z",
  completed_at: null,
};

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function audioResponse() {
  return new Response(new Blob([new Uint8Array([1, 2, 3])], { type: "audio/wav" }), {
    status: 200,
    headers: { "Content-Type": "audio/wav" },
  });
}

function installDetailHandlers(overrides: Record<string, () => Response> = {}) {
  state.authFetch.mockImplementation((input: string) => {
    const override = overrides[input];
    if (override) return override();
    if (input.endsWith("/api/v1/podcasts/11")) return jsonResponse(EPISODE_DETAIL);
    if (input.endsWith("/api/v1/podcasts/11/audio")) return audioResponse();
    return jsonResponse({ detail: `unhandled ${input}` }, 404);
  });
}

function savedRecord(userId = "student-1", overrides: Record<string, unknown> = {}) {
  return {
    episodeId: 11,
    position: 120,
    speed: 1,
    wasPlaying: false,
    updatedAt: Date.now(),
    ...overrides,
  };
}

const audioInstances: HTMLAudioElement[] = [];

function lastAudio(): HTMLAudioElement {
  const el = audioInstances.at(-1);
  if (!el) throw new Error("no audio element captured");
  return el;
}

function defineDuration(el: HTMLAudioElement, seconds: number) {
  Object.defineProperty(el, "duration", { configurable: true, get: () => seconds });
}

function Harness({ overrides }: { overrides?: Partial<PlayerTrack> }) {
  const player = usePodcastPlayer();
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          player.load({
            episodeId: 11,
            title: "پادکست آزمایشی",
            subtitle: "فیزیک دهم",
            src: "blob:mock",
            ...overrides,
          })
        }
      >
        load
      </button>
      <button type="button" onClick={() => player.toggle()}>toggle</button>
      <button type="button" onClick={() => player.seek(88)}>seek88</button>
      <button type="button" onClick={() => player.setSpeed(1.5)}>speed15</button>
    </div>
  );
}

function renderPlayer(overrides?: Partial<PlayerTrack>) {
  return render(
    <PodcastPlayerProvider>
      <Harness overrides={overrides} />
    </PodcastPlayerProvider>,
  );
}

const toasts: string[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  audioInstances.length = 0;
  toasts.length = 0;
  state.userId = "student-1";
  state.authFetch.mockReset();
  window.localStorage.clear();
  window.addEventListener(TOAST_EVENT, (event) => {
    const detail = (event as CustomEvent<{ message: string }>).detail;
    if (detail) toasts.push(detail.message);
  });
  window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  window.HTMLMediaElement.prototype.pause = vi.fn();
  window.HTMLMediaElement.prototype.load = vi.fn();
  window.URL.createObjectURL = vi.fn(() => "blob:mock");
  window.URL.revokeObjectURL = vi.fn();
  const CapturedAudio = function () {
    const element = document.createElement("audio");
    audioInstances.push(element);
    return element;
  } as unknown as typeof Audio;
  vi.stubGlobal("Audio", CapturedAudio);
});

afterEach(() => {
  vi.unstubAllGlobals();
  // @ts-expect-error test cleanup of the stubbed MediaSession
  delete window.navigator.mediaSession;
  // @ts-expect-error test cleanup of the stubbed MediaMetadata
  delete window.MediaMetadata;
});

describe("persistent playback (Phase 04B)", () => {
  it("saves the position during playback, rate-limited on timeupdate", async () => {
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    el.dispatchEvent(new Event("play"));
    el.currentTime = 42;
    el.dispatchEvent(new Event("timeupdate"));
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).not.toBeNull());
    const record = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(record.episodeId).toBe(11);
    expect(record.position).toBe(42);
    expect(record.wasPlaying).toBe(true);
    // A second immediate timeupdate must NOT overwrite the record (5s throttle).
    el.currentTime = 50;
    el.dispatchEvent(new Event("timeupdate"));
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").position).toBe(42);
  });

  it("saves the position immediately when paused", async () => {
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    el.dispatchEvent(new Event("play"));
    el.dispatchEvent(new Event("timeupdate"));
    el.currentTime = 77;
    el.dispatchEvent(new Event("pause"));
    const record = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(record.position).toBe(77);
    expect(record.wasPlaying).toBe(false);
  });

  it("restores the episode, position and player UI after a full reload", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const calls = state.authFetch.mock.calls.map((c) => String(c[0]));
    expect(calls).toContain("/api/v1/podcasts/11");
    expect(calls).toContain("/api/v1/podcasts/11/audio"); // re-fetched via the authed endpoint
    expect(screen.getByText("ادامهٔ پخش از موقعیت قبلی")).toBeInTheDocument();
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(screen.getByText("2:00 / 3:20")).toBeInTheDocument());
    expect(el.currentTime).toBe(120);
    expect(el.getAttribute("src") ?? el.src).toContain("blob:");
  });

  it("restores the previous playback speed", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord("student-1", { speed: 1.5 })));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(screen.getByRole("button", { name: "سرعت پخش" })).toHaveTextContent("1.5×"));
    expect(el.playbackRate).toBe(1.5);
  });

  it("starts from the beginning on request and clears the saved position", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await userEvent.click(screen.getByRole("button", { name: "از ابتدا" }));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(el.currentTime).toBe(0);
  });

  it("clears the saved record when the episode finishes", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    el.dispatchEvent(new Event("ended"));
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
  });

  it("keeps the record cleared when the browser fires pause after ended (real Chromium order)", async () => {
    // Regression: a seek to the exact end while playing makes Chromium emit
    // pause -> ended. The pause that carries ended=true must never re-save a
    // finished position after the ended handler cleared the record.
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    el.dispatchEvent(new Event("ended"));
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
    Object.defineProperty(el, "ended", { configurable: true, get: () => true });
    el.dispatchEvent(new Event("pause"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    Object.defineProperty(el, "ended", { configurable: true, get: () => false });
  });

  it("treats a saved position at the very end as finished: clears it and starts from zero", async () => {
    // A user who seeked to the end while paused leaves a record at ~duration;
    // the next restore must recognize "already finished" instead of resuming
    // at a frozen end position.
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord("student-1", { position: 199.8 })));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
    expect(el.currentTime).toBe(0);
    // The resume banner is pointless for a finished episode: it must not show.
    expect(screen.queryByText("ادامهٔ پخش از موقعیت قبلی")).not.toBeInTheDocument();
  });

  it("never restores another user's record", async () => {
    installDetailHandlers();
    const seeded = savedRecord("student-1");
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
    state.userId = "student-2";
    renderPlayer();
    await waitFor(() => expect(screen.getByRole("button", { name: "load" })).toBeInTheDocument());
    await new Promise((resolve) => setTimeout(resolve, 50));
    const calls = state.authFetch.mock.calls.map((c) => String(c[0]));
    expect(calls).not.toContain("/api/v1/podcasts/11");
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(OTHER_KEY)).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(JSON.stringify(seeded));
  });

  it("drops the record for a deleted or unauthorized episode", async () => {
    installDetailHandlers({ "/api/v1/podcasts/11": () => jsonResponse({ detail: "یافت نشد" }, 404) });
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();
  });

  it("ignores invalid saved metadata without crashing", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, "{not json at all");
    renderPlayer();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(state.authFetch).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    // Invalid shape (wrong types) is dropped too.
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ episodeId: "x", position: "NaN" }));
    renderPlayer();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();
  });

  it("keeps the saved position when audio is not ready or the fetch fails", async () => {
    // Episode detail says audio is not ready yet.
    installDetailHandlers({
      "/api/v1/podcasts/11": () => jsonResponse({ ...EPISODE_DETAIL, has_audio: false }),
    });
    const seeded = savedRecord();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
    renderPlayer();
    await waitFor(() => expect(toasts.some((t) => t.includes("هنوز آماده نیست"))).toBe(true));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(JSON.stringify(seeded));
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();

    // A transient server error while fetching audio keeps the record too.
    toasts.length = 0;
    installDetailHandlers({
      "/api/v1/podcasts/11/audio": () => jsonResponse({ detail: "server error" }, 500),
    });
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() =>
      expect(toasts.some((t) => t.includes("دریافت فایل صوتی ناموفق بود"))).toBe(true),
    );
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toBeNull();
  });

  it("integration: restore → continue → save → finish clears", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await userEvent.click(screen.getByRole("button", { name: "ادامه" }));
    el.dispatchEvent(new Event("play"));
    el.currentTime = 150;
    el.dispatchEvent(new Event("timeupdate"));
    await waitFor(() => {
      const record = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
      expect(record.position).toBe(150);
    });
    el.dispatchEvent(new Event("ended"));
    await waitFor(() => expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull());
  });

  it("integration: user arrives after mount (login) and restore is preserved", async () => {
    // Production sequence: provider mounts before /auth/me resolves, so the user
    // id goes null → "student-1". That transition must NOT wipe the saved record
    // (it wiped it before Phase 04B QA caught the bug in the real browser).
    installDetailHandlers();
    const seeded = savedRecord();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded));
    state.userId = null;
    const view = renderPlayer();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(JSON.stringify(seeded));
    state.userId = "student-1";
    view.rerender(
      <PodcastPlayerProvider>
        <Harness />
      </PodcastPlayerProvider>,
    );
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const calls = state.authFetch.mock.calls.map((c) => String(c[0]));
    expect(calls).toContain("/api/v1/podcasts/11");
    expect(calls).toContain("/api/v1/podcasts/11/audio");
    expect(screen.getByText("ادامهٔ پخش از موقعیت قبلی")).toBeInTheDocument();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(JSON.stringify(seeded));
  });

  it("integration: closing the player dismisses the resume record", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "بستن پخش‌کننده" }));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();
  });
});

describe("playback state contract (Phase 04C)", () => {
  it("seek writes the record with the REAL element state: playing while playing, paused while paused", async () => {
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    // Seek while playing.
    el.dispatchEvent(new Event("play"));
    await userEvent.click(screen.getByRole("button", { name: "seek88" }));
    const playing = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(playing.position).toBe(88);
    expect(playing.wasPlaying).toBe(true);
    // Seek again while paused (no play event in between).
    el.dispatchEvent(new Event("pause"));
    await userEvent.click(screen.getByRole("button", { name: "seek88" }));
    const paused = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    expect(paused.position).toBe(88);
    expect(paused.wasPlaying).toBe(false);
  });

  it("pagehide and tab-hidden saves keep the real playing state", async () => {
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    el.dispatchEvent(new Event("play"));
    el.currentTime = 31;
    // pagehide while playing -> wasPlaying must be true.
    window.dispatchEvent(new Event("pagehide"));
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").wasPlaying).toBe(true);
    // visibilitychange(hidden) while playing -> wasPlaying must be true too.
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").wasPlaying).toBe(true);
  });

  it("restore never autoplays: play() runs only after the user acts", async () => {
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(el.play).not.toHaveBeenCalled();
    expect(screen.getByText("ادامهٔ پخش از موقعیت قبلی")).toBeInTheDocument();
    // Only the user's explicit action starts playback.
    await userEvent.click(screen.getByRole("button", { name: "ادامه" }));
    expect(el.play).toHaveBeenCalledTimes(1);
  });

  it("loads a legacy record without wasPlaying/updatedAt and tolerates unknown fields (no migration needed)", async () => {
    // The 04C contract analysis found wasPlaying already stores the REAL
    // element state, so the store keeps version 1: an old record that omits
    // the newer optional fields must still restore safely.
    installDetailHandlers();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ episodeId: 11, position: 120, speed: 1.25, someFutureField: "x" }),
    );
    renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    const el = lastAudio();
    defineDuration(el, 200);
    el.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(el.currentTime).toBe(120));
    expect(el.playbackRate).toBe(1.25);
    expect(screen.getByText("ادامهٔ پخش از موقعیت قبلی")).toBeInTheDocument();
  });
});

describe("MediaSession integration (Phase 04B)", () => {
  it("registers metadata once a track loads (title/artist, artwork only when valid)", async () => {
    installMediaSession();
    const first = renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    await waitFor(() => expect(mediaSessionStub.metadata).not.toBeNull());
    const init = (mediaSessionStub.metadata as { init: Record<string, unknown> }).init;
    expect(init.title).toBe("پادکست آزمایشی");
    expect(init.artist).toBe("فیزیک دهم");
    expect(init.album).toBe("درسیار");
    expect(init.artwork).toBeUndefined(); // no cover URL → no artwork claim
    first.unmount();

    // A valid https URL becomes artwork...
    mediaSessionStub.metadata = null;
    renderPlayer({ artworkUrl: "https://cdn.example/cover.png" });
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const goodInit = (mediaSessionStub.metadata as { init: Record<string, unknown> }).init;
    expect(goodInit.artwork).toEqual([{ src: "https://cdn.example/cover.png", sizes: "512x512" }]);
    // ...while a javascript: URL never does.
    mediaSessionStub.metadata = null;
    renderPlayer({ artworkUrl: "javascript:alert(1)" });
    await userEvent.click(screen.getAllByRole("button", { name: "load" }).at(-1) as HTMLElement);
    const badInit = (mediaSessionStub.metadata as { init: Record<string, unknown> }).init;
    expect(badInit.artwork).toBeUndefined();
  });

  it("wires play and pause handlers to the same global audio element", async () => {
    installMediaSession();
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const handlers = new Map(
      mediaSessionStub.setActionHandler.mock.calls.map(([action, handler]) => [action, handler]),
    );
    const el = lastAudio();
    expect(el).toBe(audioInstances[0]); // exactly one audio element, ever
    (handlers.get("play") as () => void)();
    expect(el.play).toHaveBeenCalled();
    Object.defineProperty(el, "paused", { configurable: true, get: () => false });
    (handlers.get("pause") as () => void)();
    expect(el.pause).toHaveBeenCalled();
  });

  it("seekbackward/seekforward default to 15 seconds and seekto uses the requested time", async () => {
    installMediaSession();
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const handlers = new Map(
      mediaSessionStub.setActionHandler.mock.calls.map(([action, handler]) => [action, handler]),
    );
    const el = lastAudio();
    defineDuration(el, 200);
    el.currentTime = 50;
    (handlers.get("seekbackward") as () => void)();
    expect(el.currentTime).toBe(35);
    (handlers.get("seekforward") as () => void)();
    expect(el.currentTime).toBe(50);
    (handlers.get("seekto") as (d: { seekTime: number }) => void)({ seekTime: 100 });
    expect(el.currentTime).toBe(100);
  });

  it("updates playbackState after every real change", async () => {
    installMediaSession();
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    expect(mediaSessionStub.playbackState).toBe("paused");
    el.dispatchEvent(new Event("play"));
    await waitFor(() => expect(mediaSessionStub.playbackState).toBe("playing"));
    el.dispatchEvent(new Event("pause"));
    await waitFor(() => expect(mediaSessionStub.playbackState).toBe("paused"));
    await userEvent.click(screen.getByRole("button", { name: "بستن پخش‌کننده" }));
    expect(mediaSessionStub.playbackState).toBe("none");
  });

  it("updates positionState with the real duration and playback rate", async () => {
    installMediaSession();
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    defineDuration(el, 42.5);
    el.dispatchEvent(new Event("loadedmetadata"));
    await waitFor(() => expect(mediaSessionStub.setPositionState).toHaveBeenCalled());
    const latest = mediaSessionStub.setPositionState.mock.calls.at(-1)?.[0];
    expect(latest).toMatchObject({ duration: 42.5, position: 0, playbackRate: 1 });
    el.currentTime = 21;
    el.dispatchEvent(new Event("timeupdate"));
    await waitFor(() => {
      const next = mediaSessionStub.setPositionState.mock.calls.at(-1)?.[0];
      expect(next).toMatchObject({ duration: 42.5, position: 21, playbackRate: 1 });
    });
  });

  it("does not crash without MediaSession support", async () => {
    // navigator.mediaSession intentionally NOT installed in this test.
    renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    const el = lastAudio();
    el.dispatchEvent(new Event("play"));
    el.dispatchEvent(new Event("pause"));
    el.dispatchEvent(new Event("ended"));
    expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument();
  });

  it("does not re-register handlers after rerenders", async () => {
    installMediaSession();
    const view = renderPlayer();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    expect(mediaSessionStub.setActionHandler.mock.calls.filter((c) => c[1] !== null).length).toBe(5);
    mediaSessionStub.setActionHandler.mockClear();
    view.rerender(
      <PodcastPlayerProvider>
        <Harness />
      </PodcastPlayerProvider>,
    );
    view.rerender(
      <PodcastPlayerProvider>
        <Harness />
      </PodcastPlayerProvider>,
    );
    expect(
      mediaSessionStub.setActionHandler.mock.calls.filter((c) => c[1] !== null).length,
    ).toBe(0);
  });

  it("stops playback and drops state when the account changes", async () => {
    installMediaSession();
    installDetailHandlers();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(savedRecord()));
    const view = renderPlayer();
    await waitFor(() => expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument());
    state.userId = "student-2";
    view.rerender(
      <PodcastPlayerProvider>
        <Harness />
      </PodcastPlayerProvider>,
    );
    await waitFor(() => expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument());
    // The previous user's record must not be readable by the new account.
    expect(window.localStorage.getItem(OTHER_KEY)).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
