import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PodcastWorkspace from "@/components/PodcastWorkspace";
import PodcastPlayerProvider, { usePodcastPlayer } from "@/components/PodcastPlayerProvider";
import type { PodcastEpisode } from "@/lib/podcast";

const authFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({
    authFetch: (input: string, init?: RequestInit) => authFetchMock(input, init),
    getActiveToken: () => "test-token",
  }),
  buildUserAuthHeaders: (token: string | null) => ({ Authorization: `Bearer ${token}` }),
}));

vi.mock("@/lib/capabilities", () => ({
  fetchMyCapabilities: vi.fn(async () => capabilityGranted),
}));

/** Mutable so individual tests can flip the capability flag. */
let capabilityGranted = new Set(["audio_podcast"]);

type Handler = (init: RequestInit, url: string) => unknown;

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

function installAuth(handlers: Record<string, Handler>) {
  const calls: { url: string; method: string; body: Record<string, unknown> | undefined }[] = [];
  authFetchMock.mockImplementation(async (input: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ url: input, method, body });
    const key = `${method} ${input.split("?")[0]}`;
    const handler = handlers[key] ?? handlers[`${method} ${input}`];
    if (!handler) return jsonResponse({ detail: `unhandled ${key}` }, 404);
    const result = handler(init, input);
    if (result instanceof Response) return result;
    return jsonResponse(result);
  });
  return calls;
}

function episode(overrides: Partial<PodcastEpisode> = {}): PodcastEpisode {
  return {
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
    duration_seconds: 42.5,
    byte_size: 120000,
    has_audio: true,
    single_speaker_mode: false,
    speakers: {},
    suggested_questions: ["مهم‌ترین نکتهٔ این فصل چیست؟"],
    created_at: "2026-11-23T09:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

const CONFIG = {
  formats: [
    { key: "deep_dive" as const, label: "گفت‌وگوی عمیق" },
    { key: "brief" as const, label: "پادکست کوتاه" },
    { key: "critique" as const, label: "نقد و بررسی" },
    { key: "debate" as const, label: "مناظرهٔ آموزشی" },
  ],
  languages: [{ code: "fa", label: "فارسی" }],
  lengths: [
    { key: "short" as const, label: "کوتاه", target_minutes: "3-5" },
    { key: "standard" as const, label: "استاندارد", target_minutes: "8-12" },
    { key: "long" as const, label: "طولانی", target_minutes: "15-20" },
  ],
  dual_voice_available: true,
  single_speaker_mode: false,
  max_custom_prompt_chars: 800,
};

function installCurriculum() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/api/v1/curriculum/grades")) {
        return jsonResponse([{ number: 10, title: "دهم", has_major: false }]);
      }
      if (url.includes("/api/v1/curriculum/majors")) {
        return jsonResponse([{ code: "general", title: "عمومی" }]);
      }
      if (url.includes("/api/v1/curriculum/books")) {
        return jsonResponse([{ id: 5, title: "فیزیک دهم" }]);
      }
      return jsonResponse({ detail: "unhandled" }, 404);
    }),
  );
}

beforeEach(() => {
  authFetchMock.mockReset();
  capabilityGranted = new Set(["audio_podcast"]);
  installCurriculum();
  window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  window.HTMLMediaElement.prototype.pause = vi.fn();
  window.HTMLMediaElement.prototype.load = vi.fn();
  // jsdom lacks object URLs (used for the authenticated audio blob).
  window.URL.createObjectURL = vi.fn(() => "blob:mock");
  window.URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PodcastWorkspace", () => {
  it("shows the empty library and opens the create form with the NotebookLM-style options", async () => {
    installAuth({
      "GET /api/v1/podcasts": () => ({ items: [] }),
      "GET /api/v1/podcasts/config": () => CONFIG,
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );
    expect(await screen.findByText(/هنوز پادکستی ندارید/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /ساخت پادکست جدید/ }));

    expect(await screen.findByText("۲. قالب پادکست")).toBeInTheDocument();
    expect(screen.getByText("دوست داری گویندگان در این قسمت روی چه موضوعی تمرکز کنند؟")).toBeInTheDocument();
    // Only languages the TTS actually supports are offered.
    expect(screen.getByLabelText("زبان")).toHaveTextContent("فارسی");
    expect(screen.getByText(/فقط صفحات تأییدشده با متن معتبر استفاده می‌شوند/)).toBeInTheDocument();
  });

  it("sends source selection, format, length and custom prompt to the API", async () => {
    const queued = episode({ status: "queued", progress: 10, progress_stage: "آماده‌سازی منابع", has_audio: false });
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({ items: [] }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "POST /api/v1/podcasts": () => jsonResponse({ episode_id: 11, status: "queued", progress: 0 }, 202),
      "GET /api/v1/podcasts/11": () => queued,
      "GET /api/v1/podcasts/11/status": () => ({
        episode_id: 11, status: "queued", progress: 10, progress_stage: "آماده‌سازی منابع",
        error_code: null, error_detail: null, has_audio: false, duration_seconds: null,
      }),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /ساخت پادکست جدید/ }));

    await userEvent.selectOptions(screen.getByLabelText("پایه"), "10");
    await screen.findByRole("option", { name: "فیزیک دهم" });
    await userEvent.selectOptions(screen.getByLabelText("کتاب"), "5");
    await userEvent.type(screen.getByLabelText(/فصل‌ها/), "۲، 3");
    await userEvent.click(screen.getByRole("radio", { name: /پادکست کوتاه/ }));
    await userEvent.click(screen.getByRole("radio", { name: /طولانی/ }));
    await userEvent.type(
      screen.getByPlaceholderText(/فقط نکات امتحانی/),
      "فقط نکات امتحانی فصل را توضیح بدهند",
    );
    await userEvent.click(screen.getByRole("button", { name: /تولید پادکست/ }));

    // Phase 04: explicit source confirmation appears BEFORE any generation request.
    expect(await screen.findByText("۵. تأیید منبع و محدوده")).toBeInTheDocument();
    expect(screen.getByText(/اگر برای این محدوده منبع کافی پیدا نشود، تولید همان ابتدا متوقف می‌شود/)).toBeInTheDocument();
    expect(calls.some((call) => call.url === "/api/v1/podcasts" && call.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: /تأیید و شروع تولید/ }));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/podcasts" && call.method === "POST")).toBe(true),
    );
    const created = calls.find((call) => call.url === "/api/v1/podcasts" && call.method === "POST");
    expect(created?.body).toMatchObject({
      book_id: 5,
      format: "brief",
      language: "fa",
      length: "long",
      chapter_numbers: [2, 3],
      custom_prompt: "فقط نکات امتحانی فصل را توضیح بدهند",
    });
    // After submission the user lands on the detail view with live status.
    expect(await screen.findByText(/در صف تولید/)).toBeInTheDocument();
  });

  it("renders the library with status badges and live progress, and renames/deletes", async () => {
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({
        items: [
          episode(),
          episode({
            id: 12,
            title: "پادکست در حال تولید",
            status: "generating_audio",
            progress: 55,
            progress_stage: "تولید صوت: نوبت ۲ از ۴",
            has_audio: false,
          }),
        ],
      }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "PATCH /api/v1/podcasts/11": () => ({ id: 11, title: "مرور فیزیک" }),
      "DELETE /api/v1/podcasts/11": () => new Response(null, { status: 204 }),
      "GET /api/v1/podcasts/11": () => episode(),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );

    expect(await screen.findByText("پادکست حرکت بر خط راست")).toBeInTheDocument();
    expect(screen.getByText(/تولید صوت: نوبت ۲ از ۴/)).toBeInTheDocument();
    expect(screen.getByText(/55٪/)).toBeInTheDocument();

    vi.spyOn(window, "prompt").mockReturnValue("مرور فیزیک");
    const renameButtons = screen.getAllByRole("button", { name: "تغییر عنوان" });
    await userEvent.click(renameButtons[0]);
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/podcasts/11" && call.method === "PATCH")).toBe(true),
    );
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toEqual({ title: "مرور فیزیک" });

    vi.spyOn(window, "confirm").mockReturnValue(true);
    const deleteButtons = screen.getAllByRole("button", { name: "حذف پادکست" });
    await userEvent.click(deleteButtons[0]);
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/podcasts/11" && call.method === "DELETE")).toBe(true),
    );
  });

  it("plays through the global player and shows transcript with citations, suggested questions and feedback", async () => {
    const detailed = episode({
      segments: [
        {
          id: 1, position: 0, speaker: "host_a" as const, speaker_label: "گویندهٔ اول (مدرس)",
          text: "امروز حرکت بر خط راست را مرور میکنیم.", source_refs: [1],
          start_time: 0, end_time: 21.2, duration_seconds: 21.2, estimated_seconds: 4, status: "ready",
        },
        {
          id: 2, position: 1, speaker: "host_b" as const, speaker_label: "گویندهٔ دوم (هم‌صحبت)",
          text: "سرعت متوسط چطور تعریف میشود؟", source_refs: [2],
          start_time: 21.2, end_time: 42.5, duration_seconds: 21.3, estimated_seconds: 3, status: "ready",
        },
      ],
      sources: [
        { index: 1, citation: "[کتاب: فیزیک دهم | پایه 10 | صفحه 25 | قطعه 1]", kind: "book" },
        { index: 2, citation: "[کتاب: فیزیک دهم | پایه 10 | صفحه 26 | قطعه 2]", kind: "book" },
      ],
      questions: [],
      feedback: undefined,
    });
    const audioBlob = new Blob([new Uint8Array([1, 2, 3])], { type: "audio/mpeg" });
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({ items: [detailed] }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "GET /api/v1/podcasts/11": () => detailed,
      "GET /api/v1/podcasts/11/audio": () => new Response(audioBlob, { headers: { "Content-Type": "audio/mpeg" } }),
      "POST /api/v1/podcasts/11/questions": () => jsonResponse({ id: 1, question: "س", answer_md: "پ", citations: [] }, 201),
      "POST /api/v1/podcasts/11/feedback": (init) => jsonResponse(JSON.parse(String(init.body))),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );

    await screen.findByText("پادکست حرکت بر خط راست");
    await userEvent.click(screen.getAllByRole("button", { name: /پخش/ })[0]);
    // Mini player appears and keeps playing across pages (global provider).
    await screen.findByLabelText("پخش‌کنندهٔ پادکست");
    expect(screen.getByText("فیزیک دهم · گفت‌وگوی عمیق")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /جزئیات/ }));
    expect(await screen.findByText("متن پادکست")).toBeInTheDocument();
    expect(screen.getByText("امروز حرکت بر خط راست را مرور میکنیم.")).toBeInTheDocument();
    expect(screen.getAllByText(/قطعه 1/).length).toBeGreaterThan(0);

    // Phase 04: segment timeline built from backend-measured times; clicking seeks.
    const timeline = screen.getByLabelText("خط زمانی بخش‌های پادکست");
    const segButtons = within(timeline).getAllByRole("button");
    expect(segButtons).toHaveLength(2);
    expect(segButtons[0]).toHaveAttribute("aria-label", expect.stringContaining("پرش به بخش 1"));
    await userEvent.click(segButtons[1]);
    const bar = screen.getByRole("slider", { name: "نوار پیشرفت" });
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "21"));

    // Phase 04A: the ±15s skip buttons move the real position (21.2 − 15 → ≈6).
    await userEvent.click(screen.getByRole("button", { name: "−۱۵ ثانیه" }));
    await waitFor(() => expect(bar).toHaveAttribute("aria-valuenow", "6"));

    await userEvent.click(screen.getByRole("button", { name: /از گویندگان سؤال بپرس/ }));
    expect(screen.getByText("مهم‌ترین نکتهٔ این فصل چیست؟")).toBeInTheDocument();
    await userEvent.type(
      screen.getByPlaceholderText(/چرا در این مثال/),
      "سرعت متوسط را ساده توضیح بده",
    );
    await userEvent.click(screen.getByRole("button", { name: /پرسش از گویندگان/ }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url === "/api/v1/podcasts/11/questions" && call.method === "POST"),
      ).toBe(true),
    );

    await userEvent.click(screen.getByRole("button", { name: "پسندیدم" }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url === "/api/v1/podcasts/11/feedback" && call.body?.liked === true),
      ).toBe(true),
    );
  });

  it("04C: the detail big button toggles pause for the current episode instead of re-loading it", async () => {
    // Phase 04C root-cause fix: the big button showed a pause icon/label while
    // playing but actually re-loaded the episode, so it never paused. It must
    // toggle the global player when the episode is current.
    const audioInstances: HTMLAudioElement[] = [];
    const CapturedAudio = function () {
      const element = document.createElement("audio");
      audioInstances.push(element);
      return element;
    } as unknown as typeof Audio;
    vi.stubGlobal("Audio", CapturedAudio);

    const detailed = episode();
    const audioBlob = new Blob([new Uint8Array([1, 2, 3])], { type: "audio/mpeg" });
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({ items: [detailed] }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "GET /api/v1/podcasts/11": () => detailed,
      "GET /api/v1/podcasts/11/audio": () => new Response(audioBlob, { headers: { "Content-Type": "audio/mpeg" } }),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );

    await screen.findByText("پادکست حرکت بر خط راست");
    await userEvent.click(screen.getAllByRole("button", { name: /پخش/ })[0]);
    await screen.findByLabelText("پخش‌کنندهٔ پادکست");
    const el = audioInstances[0];
    // jsdom does not track playing state, so mirror the browser's paused flag
    // (the toggle branches on audio.paused).
    let playingFlag = false;
    Object.defineProperty(el, "paused", { configurable: true, get: () => !playingFlag });
    el.dispatchEvent(new Event("play")); // the browser would emit this after play()
    playingFlag = true;
    // Playing: both the mini toggle and the big button show the pause action.
    await waitFor(() => expect(screen.getByRole("button", { name: "توقف پخش" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /جزئیات/ }));
    const bigPlay = await screen.findByRole("button", { name: "توقف" });
    expect(bigPlay).toHaveClass("pc-big-play");

    // Clicking the big "توقف" button must PAUSE the current episode...
    const pauseSpy = window.HTMLMediaElement.prototype.pause as ReturnType<typeof vi.fn>;
    await userEvent.click(bigPlay);
    expect(pauseSpy).toHaveBeenCalled();
    playingFlag = false;
    el.dispatchEvent(new Event("pause")); // the browser emits pause after pause()
    // ...and must NOT re-fetch the audio (it used to call load() again).
    expect(calls.filter((call) => call.url === "/api/v1/podcasts/11/audio").length).toBe(1);
    expect(screen.getAllByRole("button", { name: "پخش" }).length).toBeGreaterThan(0);

    // Clicking again resumes playback without another fetch.
    const playSpy = window.HTMLMediaElement.prototype.play as ReturnType<typeof vi.fn>;
    const playsBefore = playSpy.mock.calls.length;
    await userEvent.click(screen.getAllByRole("button", { name: "پخش" })[0]);
    expect(playSpy.mock.calls.length).toBeGreaterThan(playsBefore);
    expect(calls.filter((call) => call.url === "/api/v1/podcasts/11/audio").length).toBe(1);
  });

  it("shows the disabled state when the capability is off", async () => {
    capabilityGranted = new Set(["chat"]);
    installAuth({});
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );
    expect(await screen.findByText(/پادکست آموزشی توسط مدیر درسیار غیرفعال شده است/)).toBeInTheDocument();
  });

  it("cancels an in-progress job through the real backend cancel endpoint (Phase 04)", async () => {
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({
        items: [
          episode({
            id: 13,
            title: "پادکست در حال تولید",
            status: "generating_audio",
            progress: 55,
            progress_stage: "تولید صوت: نوبت ۲ از ۴",
            has_audio: false,
          }),
        ],
      }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "POST /api/v1/podcasts/13/cancel": () => ({ id: 13, status: "cancelled" }),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "لغو تولید پادکست در حال تولید" }));
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/podcasts/13/cancel" && call.method === "POST")).toBe(true),
    );
    expect(await screen.findByText("تولید پادکست لغو شد.")).toBeInTheDocument();
    // No fake cancel: completed episodes never show a cancel action.
    expect(screen.queryByRole("button", { name: "لغو تولید پادکست حرکت بر خط راست" })).not.toBeInTheDocument();
  });

  it("offers retry for a cancelled episode too (Phase 04 — backend allows failed/cancelled)", async () => {
    const calls = installAuth({
      "GET /api/v1/podcasts": () => ({
        items: [
          episode({
            id: 14,
            title: "پادکست لغوشده",
            status: "cancelled",
            progress: 30,
            progress_stage: "لغو شد",
            has_audio: false,
          }),
        ],
      }),
      "GET /api/v1/podcasts/config": () => CONFIG,
      "POST /api/v1/podcasts/14/retry": () => ({ episode_id: 14, status: "queued", progress: 0 }),
    });
    render(
      <PodcastPlayerProvider>
        <PodcastWorkspace />
      </PodcastPlayerProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /تلاش مجدد/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/podcasts/14/retry" && call.method === "POST")).toBe(true),
    );
    expect(await screen.findByText("پادکست دوباره در صف تولید قرار گرفت.")).toBeInTheDocument();
  });
});

describe("PodcastPlayerProvider (mini player)", () => {
  beforeEach(() => {
    window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  function MiniHarness() {
    const player = usePodcastPlayer();
    return (
      <button
        type="button"
        onClick={() =>
          player.load({ episodeId: 7, title: "پادکست آزمایشی", subtitle: "فیزیک دهم", src: "blob:fake" })
        }
      >
        load
      </button>
    );
  }

  it("renders the mini player with title and speed once a track is loaded", async () => {
    render(
      <PodcastPlayerProvider>
        <MiniHarness />
      </PodcastPlayerProvider>,
    );
    expect(screen.queryByLabelText("پخش‌کنندهٔ پادکست")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "load" }));
    expect(screen.getByLabelText("پخش‌کنندهٔ پادکست")).toBeInTheDocument();
    expect(screen.getByText("پادکست آزمایشی")).toBeInTheDocument();
    expect(screen.getByText("فیزیک دهم")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "سرعت پخش" })).toHaveTextContent("1×");
  });
});
