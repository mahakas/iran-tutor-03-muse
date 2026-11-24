import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import FigureThumb from "@/components/FigureThumb";
import type { SourceFigure } from "@/lib/phase5";

const authFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({ authFetch: (input: string, init?: RequestInit) => authFetchMock(input, init) }),
}));

const FIGURE: SourceFigure = {
  id: 7,
  pdf_page_index: 1,
  printed_page_number: 3,
  chapter_number: 1,
  figure_label: "شکل ۱",
  caption: "نمونه",
};

beforeEach(() => {
  window.URL.createObjectURL = vi.fn(() => "blob:mock-figure");
  window.URL.revokeObjectURL = vi.fn();
  authFetchMock.mockImplementation(async () =>
    new Response(new Blob(["fake-png"], { type: "image/png" }), { status: 200 })
  );
});

describe("FigureThumb", () => {
  it("loads the figure image through the student figure endpoint and renders an img", async () => {
    render(<FigureThumb bookId={5} figure={FIGURE} />);
    const img = await screen.findByRole("img", { name: "شکل ۱: نمونه" });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "blob:mock-figure");
    expect(authFetchMock).toHaveBeenCalledWith(
      "/api/v1/curriculum/books/5/figures/7/image",
      undefined
    );
    expect(screen.getByText("شکل ۱ — نمونه")).toBeInTheDocument();
  });

  it("shows an honest fallback when the figure image is unavailable", async () => {
    authFetchMock.mockImplementation(async () => new Response("not found", { status: 404 }));
    render(<FigureThumb bookId={5} figure={FIGURE} />);
    expect(await screen.findByText("تصویر این شکل در دسترس نیست.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
