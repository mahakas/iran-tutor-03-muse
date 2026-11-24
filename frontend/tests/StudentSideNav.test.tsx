import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import StudentSideNav from "@/components/StudentSideNav";

const mocks = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
}));

const ALL_ENABLED = {
  chat: true,
  quiz: true,
  flashcards: true,
  mistake_bank: true,
  mastery_path: true,
  deep_solve: true,
  learning_notebook: true,
  living_book: true,
  audio_podcast: true,
};

type RenderOpts = {
  pathname?: string;
  lang?: "fa" | "en";
  enabled?: Partial<typeof ALL_ENABLED>;
  isAuthenticated?: boolean;
  examHistoryCount?: number;
};

function linkFor(href: string): HTMLAnchorElement {
  const el = document.querySelector<HTMLAnchorElement>(`a[href="${href}"]`);
  expect(el, `expected a nav link to ${href}`).not.toBeNull();
  return el as HTMLAnchorElement;
}

function renderNav(opts: RenderOpts = {}) {
  mocks.pathname = opts.pathname ?? "/";
  const onAfterNavigate = vi.fn();
  const onOpenTutor = vi.fn();
  const onOpenExams = vi.fn();
  const onOpenChatSearch = vi.fn();
  const onOpenChatBin = vi.fn();
  render(
    <StudentSideNav
      lang={opts.lang ?? "fa"}
      enabled={{ ...ALL_ENABLED, ...(opts.enabled ?? {}) }}
      isAuthenticated={opts.isAuthenticated ?? true}
      examHistoryCount={opts.examHistoryCount ?? 0}
      onAfterNavigate={onAfterNavigate}
      onOpenTutor={onOpenTutor}
      onOpenExams={onOpenExams}
      onOpenChatSearch={onOpenChatSearch}
      onOpenChatBin={onOpenChatBin}
    />
  );
  return { onAfterNavigate, onOpenTutor, onOpenExams, onOpenChatSearch, onOpenChatBin };
}

beforeEach(() => {
  mocks.pathname = "/";
});

describe("StudentSideNav", () => {
  it("renders the six areas with the real destinations", () => {
    renderNav();
    for (const area of ["خانه", "معلم من", "یادگیری", "تمرین", "پیشرفت", "کتابخانه"]) {
      expect(screen.getByText(area)).toBeInTheDocument();
    }
    for (const href of [
      "/",
      "/living-book",
      "/notebook",
      "/podcast",
      "/flashcards",
      "/mistakes",
      "/deep-solve",
      "/mastery",
      "/#today-class",
    ]) {
      expect(linkFor(href)).toBeInTheDocument();
    }
  });

  it("derives the active item from the URL, not from internal state", () => {
    renderNav({ pathname: "/flashcards" });
    const flashcards = linkFor("/flashcards");
    expect(flashcards).toHaveClass("active");
    expect(flashcards).toHaveAttribute("aria-current", "page");
    // classroom is not active while the student is on /flashcards
    expect(linkFor("/")).not.toHaveClass("active");
  });

  it("marks the classroom active on /", () => {
    renderNav({ pathname: "/" });
    expect(linkFor("/")).toHaveClass("active");
    expect(linkFor("/flashcards")).not.toHaveClass("active");
  });

  it("hides capability-gated items and drops empty areas entirely", () => {
    renderNav({
      enabled: {
        mistake_bank: false,
        living_book: false,
        learning_notebook: false,
        audio_podcast: false,
      },
    });
    expect(document.querySelector('a[href="/mistakes"]')).toBeNull();
    expect(document.querySelector('a[href="/living-book"]')).toBeNull();
    // the whole "یادگیری" area disappears when all of its items are gated off
    expect(screen.queryByText("یادگیری")).not.toBeInTheDocument();
    // other areas remain
    expect(screen.getByText("تمرین")).toBeInTheDocument();
  });

  it("hides chat-management actions for anonymous visitors", () => {
    renderNav({ isAuthenticated: false });
    expect(screen.queryByText("جستجوی گفت‌وگوها")).not.toBeInTheDocument();
    expect(screen.queryByText("سطل بازیافت")).not.toBeInTheDocument();
    // the tutor action stays (capability chat is on)
    expect(screen.getByText("معلم خصوصی")).toBeInTheDocument();
  });

  it("shows the exam history badge with a Persian-formatted count", () => {
    renderNav({ examHistoryCount: 12 });
    expect(screen.getByText("۱۲")).toBeInTheDocument();
  });

  it("routes clicks through the callbacks and closes the drawer on navigation", async () => {
    const user = userEvent.setup();
    const handlers = renderNav();
    await user.click(screen.getByText("معلم خصوصی"));
    expect(handlers.onOpenTutor).toHaveBeenCalledTimes(1);
    await user.click(screen.getByText("آزمون‌های من"));
    expect(handlers.onOpenExams).toHaveBeenCalledTimes(1);
    await user.click(screen.getByText("جستجوی گفت‌وگوها"));
    expect(handlers.onOpenChatSearch).toHaveBeenCalledTimes(1);
    await user.click(screen.getByText("سطل بازیافت"));
    expect(handlers.onOpenChatBin).toHaveBeenCalledTimes(1);
    // in-app actions do not need onAfterNavigate; route links do
    expect(handlers.onAfterNavigate).toHaveBeenCalledTimes(0);
    await user.click(linkFor("/flashcards"));
    expect(handlers.onAfterNavigate).toHaveBeenCalledTimes(1);
  });

  it("renders English labels when lang=en", () => {
    renderNav({ lang: "en" });
    for (const area of ["Home", "My Teacher", "Learning", "Practice", "Progress", "Library"]) {
      expect(screen.getByText(area)).toBeInTheDocument();
    }
  });
});
