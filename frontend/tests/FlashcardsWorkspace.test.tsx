import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FlashcardsWorkspace from "@/components/FlashcardsWorkspace";
import type { Flashcard, FlashcardDeck, StudySessionPayload } from "@/lib/flashcards";

const authFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({
    authFetch: (input: string, init?: RequestInit) => authFetchMock(input, init),
    getActiveToken: () => "test-token",
  }),
  buildUserAuthHeaders: (token: string | null) => ({ Authorization: `Bearer ${token}` }),
}));

vi.mock("@/lib/capabilities", () => ({
  fetchMyCapabilities: vi.fn(async () => new Set(["flashcards"])),
}));

type Handler = (init: RequestInit, url: string) => unknown;

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

// Global fetch is used for curriculum lookups inside the generate modal.
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
        return jsonResponse([{ id: 5, title: "ریاضی دهم" }]);
      }
      return jsonResponse({ detail: "unhandled" }, 404);
    }),
  );
}

const CARD: Omit<Flashcard, "id"> = {
  deck_id: 7,
  front_md: "سؤال **مهم** با $x^2$",
  back_md: "پاسخ کامل",
  hint_md: "راهنمای ساده",
  citations: [],
  tags: [],
  review: null,
};

function cards(count: number): Flashcard[] {
  return Array.from({ length: count }, (_, index) => ({ ...CARD, id: 101 + index }));
}

function deck(statsOverride: Partial<FlashcardDeck["stats"]> = {}): FlashcardDeck {
  return {
    id: 7,
    title: "ریاضی — فصل ۳",
    book_id: null,
    chapter_number: null,
    page_start: null,
    page_end: null,
    source_type: "book",
    is_public: false,
    admin_approved: false,
    created_at: null,
    stats: {
      total: 3,
      due: 2,
      mastered: 0,
      new: 3,
      progress_percent: 0,
      last_review: null,
      ...statsOverride,
    },
  };
}

function sessionPayload(
  cardList: Flashcard[],
  overrides: Partial<StudySessionPayload> = {},
): StudySessionPayload {
  const total = cardList.length;
  return {
    id: 91,
    deck_id: 7,
    mode: "full",
    status: "active",
    position: 0,
    flipped: false,
    card_order: cardList.map((card) => card.id),
    results: {},
    total_cards: total,
    summary: { total, answered: 0, got: 0, missed: 0, percent: 0, status: "active" },
    started_at: "2026-11-23T09:00:00Z",
    last_activity_at: "2026-11-23T09:10:00Z",
    completed_at: null,
    cards: cardList,
    ...overrides,
  };
}

function answerResponse(session: StudySessionPayload, cardId: number, got: boolean) {
  const results = { ...session.results, [String(cardId)]: got ? ("got" as const) : ("missed" as const) };
  const answered = Object.keys(results).length;
  const gotCount = Object.values(results).filter((value) => value === "got").length;
  const nextPosition = session.card_order.findIndex((id) => !results[String(id)]);
  const completed = nextPosition === -1;
  return {
    card_id: cardId,
    result: got ? "got" : "missed",
    already_recorded: false,
    review: { last_rating: got ? 3 : 1, review_count: 1 },
    session: {
      ...session,
      results,
      position: completed ? session.card_order.length - 1 : nextPosition,
      status: completed ? "active" : "active",
      summary: {
        total: session.summary.total,
        answered,
        got: gotCount,
        missed: answered - gotCount,
        percent: Math.round((gotCount / answered) * 100),
        status: "active",
      },
      cards: undefined,
    },
  };
}

const baseHandlers = (): Record<string, Handler> => ({
  "GET /api/v1/flashcards/decks": () => [deck()],
  "GET /api/v1/flashcards/library": () => [],
  "GET /api/v1/flashcards/study-sessions/active": () => ({ session: null }),
});

describe("FlashcardsWorkspace", () => {
  beforeEach(() => {
    authFetchMock.mockReset();
    installCurriculum();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows resume banner and restores the saved session on click", async () => {
    const stored = sessionPayload(cards(3), { position: 1, total_cards: 3 });
    const calls = installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/study-sessions/active": () => ({ session: stored }),
      "GET /api/v1/flashcards/study-sessions/91": () => stored,
    });
    render(<FlashcardsWorkspace />);

    expect(await screen.findByText("یک جلسهٔ مطالعهٔ نیمه‌کاره دارید")).toBeInTheDocument();
    expect(screen.getByText(/کارت 2 از 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /ادامهٔ مطالعه/ }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url === "/api/v1/flashcards/study-sessions/91" && call.method === "GET"),
      ).toBe(true),
    );
    await waitFor(() => expect(screen.getByText("پاسخ کامل")).toBeInTheDocument()); // session cards are rendered
    expect(screen.getByText(/کارت 2 از 3/)).toBeInTheDocument();
  });

  it("generate modal sends count preset, difficulty and custom prompt to the API", async () => {
    const calls = installAuth({
      ...baseHandlers(),
      "GET /api/v1/exams": () => [],
      "POST /api/v1/flashcards/generate": () => jsonResponse({ deck_id: 7, created_count: 10, cards: [] }, 201),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(3) }),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));

    await screen.findByText("سطح دشواری");
    await userEvent.click(screen.getByRole("radio", { name: /بیشتر/ }));
    await userEvent.click(screen.getByRole("radio", { name: /سخت/ }));
    await userEvent.type(
      screen.getByPlaceholderText(/قانون دوم نیوتن/),
      "فقط فرمول‌های فصل را پوشش بده",
    );
    await userEvent.selectOptions(screen.getByLabelText("پایه"), "10");
    await screen.findByRole("option", { name: "ریاضی دهم" });
    await userEvent.selectOptions(screen.getByLabelText("کتاب"), "5");
    await userEvent.type(screen.getByLabelText("شمارهٔ فصل"), "3");
    await userEvent.click(screen.getByRole("button", { name: /ساخت کارت‌ها/ }));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/flashcards/generate")).toBe(true),
    );
    const generate = calls.find((call) => call.url === "/api/v1/flashcards/generate");
    expect(generate?.body).toMatchObject({
      source: "book",
      count: 10,
      difficulty: "hard",
      focus_prompt: "فقط فرمول‌های فصل را پوشش بده",
      book_id: 5,
      chapter_number: 3,
    });
    // After success the user lands inside the generated deck (no page reload).
    await waitFor(() => expect(screen.getByRole("button", { name: /دانلود CSV/ })).toBeInTheDocument());
  });

  it("keeps the form values when validation or generation fails", async () => {
    installAuth({
      ...baseHandlers(),
      "GET /api/v1/exams": () => [],
      "POST /api/v1/flashcards/generate": () => jsonResponse({ detail: "سهمیهٔ امروز شما تمام شده است." }, 402),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));
    await userEvent.click(await screen.findByRole("radio", { name: /سخت/ }));
    await userEvent.type(screen.getByPlaceholderText(/قانون دوم نیوتن/), "روی تعریف‌ها تمرکز کن");
    // No book chosen yet → server-side shape is still not submitted.
    await userEvent.click(screen.getByRole("button", { name: /ساخت کارت‌ها/ }));
    expect(await screen.findByText("کتاب را انتخاب کنید.")).toBeInTheDocument();
    // The chosen difficulty and the typed focus prompt survive the failed submit.
    expect(screen.getByRole("radio", { name: /سخت/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByPlaceholderText(/قانون دوم نیوتن/)).toHaveValue("روی تعریف‌ها تمرکز کن");

    // Now choose a book + chapter and submit → server error stays inline, form intact.
    await userEvent.selectOptions(screen.getByLabelText("پایه"), "10");
    await screen.findByRole("option", { name: "ریاضی دهم" });
    await userEvent.selectOptions(screen.getByLabelText("کتاب"), "5");
    await userEvent.type(screen.getByLabelText("شمارهٔ فصل"), "3");
    await userEvent.click(screen.getByRole("button", { name: /ساخت کارت‌ها/ }));
    expect(await screen.findByText("سهمیهٔ امروز شما تمام شده است.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /سخت/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByPlaceholderText(/قانون دوم نیوتن/)).toHaveValue("روی تعریف‌ها تمرکز کن");
  });

  it("flips cards, navigates, and records got/missed with SM-2 mapping", async () => {
    const initial = sessionPayload(cards(3));
    let state = initial;
    const calls = installAuth({
      ...baseHandlers(),
      "POST /api/v1/flashcards/decks/7/study-sessions": () => initial,
      "POST /api/v1/flashcards/study-sessions/91/progress": (init) => {
        const body = JSON.parse(String(init.body));
        state = { ...state, position: body.position, flipped: body.flipped };
        return { session: { ...state } };
      },
      "POST /api/v1/flashcards/study-sessions/91/answer": (init) => {
        const body = JSON.parse(String(init.body));
        const response = answerResponse(state, body.card_id, body.got);
        state = response.session as typeof state;
        return response;
      },
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مطالعهٔ کامل/ }));

    expect(await screen.findByText(/کارت 1 از 3/)).toBeInTheDocument();
    // Clicking the card flips it and the answer visibility is persisted.
    await userEvent.click(screen.getByRole("button", { name: /نمایش پاسخ/ }));
    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/progress") && call.body?.flipped === true)).toBe(true),
    );
    expect(screen.getByRole("button", { name: /بلد بودم/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /بلد بودم/ }));
    const answerCall = calls.find((call) => call.url.includes("/answer"));
    expect(answerCall?.body).toEqual({ card_id: 101, got: true });
    await waitFor(() => expect(screen.getByText(/کارت 2 از 3/)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /نمایش پاسخ/ }));
    await userEvent.click(screen.getByRole("button", { name: /بلد نبودم/ }));
    await waitFor(() => expect(screen.getByText(/کارت 3 از 3/)).toBeInTheDocument());
  });

  it("shows the results screen and replays only the missed cards of this session", async () => {
    const initial = sessionPayload(cards(3));
    const allCards = cards(3);
    let state = initial;
    const calls = installAuth({
      ...baseHandlers(),
      "POST /api/v1/flashcards/decks/7/study-sessions": (init) => {
        const body = JSON.parse(String(init.body));
        if (body.mode === "subset") {
          return sessionPayload(
            allCards.filter((card) => body.card_ids.includes(card.id)),
            { id: 92, mode: "subset" },
          );
        }
        return initial;
      },
      "POST /api/v1/flashcards/study-sessions/91/progress": (init) => {
        const body = JSON.parse(String(init.body));
        state = { ...state, position: body.position, flipped: body.flipped };
        return { session: { ...state } };
      },
      "POST /api/v1/flashcards/study-sessions/91/answer": (init) => {
        const body = JSON.parse(String(init.body));
        const response = answerResponse(state, body.card_id, body.got);
        state = response.session as typeof state;
        return response;
      },
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مطالعهٔ کامل/ }));
    await screen.findByText(/کارت 1 از 3/);

    // got, missed, missed → session complete
    await userEvent.click(screen.getByRole("button", { name: /نمایش پاسخ/ }));
    await userEvent.click(screen.getByRole("button", { name: /بلد بودم/ }));
    await userEvent.click(await screen.findByRole("button", { name: /نمایش پاسخ/ }));
    await userEvent.click(screen.getByRole("button", { name: /بلد نبودم/ }));
    await userEvent.click(await screen.findByRole("button", { name: /نمایش پاسخ/ }));
    await userEvent.click(screen.getByRole("button", { name: /بلد نبودم/ }));

    expect(await screen.findByText("آفرین، جلسهٔ مطالعه تمام شد!")).toBeInTheDocument();
    expect(screen.getByText(/درصد پاسخ‌های درست/)).toBeInTheDocument();
    expect(screen.getByText("بلد بودم")).toBeInTheDocument();
    expect(screen.getByText("بلد نبودم")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /مرور فقط بلد نبودم‌ها/ }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.url === "/api/v1/flashcards/decks/7/study-sessions" && call.body?.mode === "subset",
        ),
      ).toBe(true),
    );
    const subsetCall = calls.find(
      (call) => call.url === "/api/v1/flashcards/decks/7/study-sessions" && call.body?.mode === "subset",
    );
    expect(subsetCall?.body?.card_ids).toEqual([102, 103]);
    await waitFor(() => expect(screen.getByText(/کارت 1 از 2/)).toBeInTheDocument());
  });

  it("shuffles the session order on the server without losing results", async () => {
    const list = cards(4);
    const initial = sessionPayload(list);
    const shuffled = sessionPayload([list[2], list[0], list[3], list[1]], {
      id: 91,
      results: { "101": "got" },
      summary: { total: 4, answered: 1, got: 1, missed: 0, percent: 25, status: "active" },
    });
    let state = initial;
    installAuth({
      ...baseHandlers(),
      "POST /api/v1/flashcards/decks/7/study-sessions": () => initial,
      "POST /api/v1/flashcards/study-sessions/91/shuffle": () => {
        state = shuffled;
        return shuffled;
      },
      "POST /api/v1/flashcards/study-sessions/91/progress": (init) => {
        const body = JSON.parse(String(init.body));
        state = { ...state, position: body.position, flipped: body.flipped };
        return { session: { ...state } };
      },
      "POST /api/v1/flashcards/study-sessions/91/answer": (init) => {
        const body = JSON.parse(String(init.body));
        const response = answerResponse(state, body.card_id, body.got);
        state = response.session as typeof state;
        return response;
      },
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مطالعهٔ کامل/ }));
    await screen.findByText(/کارت 1 از 4/);

    await userEvent.click(screen.getByRole("button", { name: /نمایش پاسخ/ }));
    await userEvent.click(screen.getByRole("button", { name: /بلد بودم/ }));
    await waitFor(() => expect(screen.getByText(/کارت 2 از 4/)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "بر زدن کارت‌ها" }));
    await waitFor(() => expect(screen.getByText(/کارت 1 از 4/)).toBeInTheDocument());
    // The answered card is still recorded: the got counter chip keeps its 1.
    const gotChip = document.querySelector(".fc-chip.got");
    expect(gotChip?.textContent).toContain("1");
  });

  it("shows the Persian error when a session request fails", async () => {
    installAuth({
      ...baseHandlers(),
      "POST /api/v1/flashcards/decks/7/study-sessions": () =>
        jsonResponse({ detail: "در حال حاضر کارتی برای مرور هوشمند موعد ندارد." }, 422),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مرور هوشمند/ }));
    expect(
      await screen.findByText("در حال حاضر کارتی برای مرور هوشمند موعد ندارد."),
    ).toBeInTheDocument();
  });
});

describe("FlashcardsWorkspace — Phase 03 library, card details, generation preview", () => {
  beforeEach(() => {
    authFetchMock.mockReset();
    // Safe default so a stale effect from a previous test never crashes this one.
    authFetchMock.mockImplementation(async () => jsonResponse({ detail: "unhandled" }, 404));
    installCurriculum();
  });

  afterEach(() => {
    // NOTE: no explicit restoreAllMocks here — vitest config already has
    // restoreMocks: true (runs before each test, after RTL cleanup). Calling it
    // here too cleared mock implementations while a previous test's mounted
    // modal still had a queued effect flush, which crashed the next test with
    // `Cannot read properties of undefined (reading 'then')`.
    vi.unstubAllGlobals();
  });

  it("searches the deck library and filters by study status (real API list only)", async () => {
    installAuth({
      "GET /api/v1/flashcards/decks": () => [
        deck(),
        {
          ...deck(),
          id: 8,
          title: "حروف اضافه",
          stats: { total: 5, due: 0, mastered: 5, new: 0, progress_percent: 100, last_review: "2026-11-20T10:00:00Z" },
        },
      ],
      "GET /api/v1/flashcards/library": () => [],
      "GET /api/v1/flashcards/study-sessions/active": () => ({ session: null }),
    });
    render(<FlashcardsWorkspace />);

    expect(await screen.findByText("ریاضی — فصل ۳")).toBeInTheDocument();
    expect(screen.getByText("حروف اضافه")).toBeInTheDocument();
    expect(screen.getByText(/آخرین مرور/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("جست‌وجوی دسته…"), "حروف");
    expect(screen.queryByText("ریاضی — فصل ۳")).not.toBeInTheDocument();
    expect(screen.getByText("حروف اضافه")).toBeInTheDocument();

    await userEvent.clear(screen.getByPlaceholderText("جست‌وجوی دسته…"));
    await userEvent.click(screen.getByRole("button", { name: "برای مرور امروز" }));
    expect(screen.getByText("ریاضی — فصل ۳")).toBeInTheDocument();
    expect(screen.queryByText("حروف اضافه")).not.toBeInTheDocument();
  });

  it("shows an empty-library message when the filter matches nothing", async () => {
    installAuth({
      ...baseHandlers(),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: "تسلط‌یافته" }));
    expect(await screen.findByText("دسته‌ای با این جست‌وجو یا فیلتر پیدا نشد.")).toBeInTheDocument();
  });

  it("previews the generation scope before submitting", async () => {
    installAuth({
      ...baseHandlers(),
      "GET /api/v1/exams": () => [],
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /ساخت با هوش مصنوعی/ }));
    expect(await screen.findByText("ابتدا کتاب را انتخاب کنید تا محدودهٔ ساخت اینجا نمایش داده شود.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("پایه"), "10");
    await screen.findByRole("option", { name: "ریاضی دهم" });
    await userEvent.selectOptions(screen.getByLabelText("کتاب"), "5");
    const preview = await screen.findByLabelText("پیش‌نمایش درخواست");
    await waitFor(() => expect(preview).toHaveTextContent("ریاضی دهم"));
    expect(preview).toHaveTextContent("اعتبار فصل/صفحه‌ها هنگام ساخت");
  });

  it("opens card details, edits the card through PATCH and refreshes the deck", async () => {
    const calls = installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(1) }),
      "PATCH /api/v1/flashcards/cards/101": () => ({ ...CARD, id: 101, front_md: "سؤال ویرایش‌شده" }),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مشاهده/ }));

    await userEvent.click(await screen.findByRole("button", { name: "جزئیات کارت" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("پاسخ کامل")).toBeInTheDocument());
    expect(within(dialog).getByText(/این کارت ارجاع صفحه‌ای به کتاب رسمی ندارد/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /ویرایش/ }));
    const frontBox = screen.getByLabelText("روی کارت");
    await userEvent.clear(frontBox);
    await userEvent.type(frontBox, "سؤال ویرایش‌شده");
    await userEvent.click(screen.getByRole("button", { name: /ذخیرهٔ ویرایش/ }));

    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH" && call.url === "/api/v1/flashcards/cards/101")).toBe(true),
    );
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toMatchObject({ front_md: "سؤال ویرایش‌شده", back_md: "پاسخ کامل" });
    expect(await screen.findByText("ویرایش ذخیره شد.")).toBeInTheDocument();
  });

  it("keeps the editor open with values when the edit fails", async () => {
    installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(1) }),
      "PATCH /api/v1/flashcards/cards/101": () => jsonResponse({ detail: "متن کارت خالی است." }, 422),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مشاهده/ }));
    await userEvent.click(await screen.findByRole("button", { name: "جزئیات کارت" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /ویرایش/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: /ذخیرهٔ ویرایش/ }));
    expect(await screen.findByText("متن کارت خالی است.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("روی کارت")).toHaveValue("سؤال **مهم** با $x^2$");
  });

  it("reports a card issue once and treats a duplicate open report as 409", async () => {
    const calls = installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(1) }),
      "POST /api/v1/flashcards/cards/101/report": () => jsonResponse({ id: 1, status: "open" }, 201),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مشاهده/ }));
    await userEvent.click(await screen.findByRole("button", { name: "جزئیات کارت" }));

    const reportDialog = screen.getByRole("dialog");
    await userEvent.click(within(reportDialog).getByRole("button", { name: /گزارش ایراد/ }));
    await userEvent.selectOptions(within(reportDialog).getByLabelText("دلیل گزارش"), "not_from_book");
    await userEvent.type(screen.getByLabelText(/توضیح \(اختیاری\)/), "این پاسخ از کتاب نیست");
    await userEvent.click(screen.getByRole("button", { name: /ثبت گزارش/ }));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/v1/flashcards/cards/101/report")).toBe(true),
    );
    const report = calls.find((call) => call.url === "/api/v1/flashcards/cards/101/report");
    expect(report?.body).toMatchObject({ reason: "not_from_book", note: "این پاسخ از کتاب نیست" });
    expect(await screen.findByText(/گزارش شما ثبت شد/)).toBeInTheDocument();
    // The report button disappears after a successful report (no duplicate submissions).
    expect(screen.queryByRole("button", { name: /گزارش ایراد/ })).not.toBeInTheDocument();
  });

  it("surfaces the 409 duplicate-report message from the server", async () => {
    installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(1) }),
      "POST /api/v1/flashcards/cards/101/report": () => jsonResponse({ detail: "گزارش بازی از این کارت دارید؛ در انتظار بررسی است." }, 409),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مشاهده/ }));
    await userEvent.click(await screen.findByRole("button", { name: "جزئیات کارت" }));
    const reportDialog = screen.getByRole("dialog");
    await userEvent.click(within(reportDialog).getByRole("button", { name: /گزارش ایراد/ }));
    await userEvent.click(within(reportDialog).getByRole("button", { name: /ثبت گزارش/ }));
    expect(await screen.findByText(/در انتظار بررسی است/)).toBeInTheDocument();
  });

  it("deletes the card from the details dialog after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const calls = installAuth({
      ...baseHandlers(),
      "GET /api/v1/flashcards/decks/7": () => ({ ...deck(), cards: cards(1) }),
      "DELETE /api/v1/flashcards/cards/101": () => new Response(null, { status: 204 }),
    });
    render(<FlashcardsWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /مشاهده/ }));
    await userEvent.click(await screen.findByRole("button", { name: "جزئیات کارت" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /حذف کارت/ }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        calls.some((call) => call.method === "DELETE" && call.url === "/api/v1/flashcards/cards/101"),
      ).toBe(true),
    );
    confirmSpy.mockRestore();
  });
});
