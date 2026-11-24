import { render, act } from "@testing-library/react";
import { createElement, useRef } from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { useNavDrawer } from "@/lib/useNavDrawer";

afterEach(() => {
  document.body.classList.remove("nav-drawer-open");
});

/** Override jsdom's matchMedia polyfill so `scrollLockQuery` matches (overlay viewport). */
function withOverlayViewport(run: () => void) {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: query === "(max-width: 767px)",
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  try {
    run();
  } finally {
    window.matchMedia = original;
  }
}

function renderDrawer(open: boolean, opts: { scrollLockQuery?: string } = {}) {
  const onClose = vi.fn();
  const Harness = () => {
    const closeBtn = useRef<HTMLButtonElement | null>(null);
    useNavDrawer({ open, onClose, focusRef: closeBtn, scrollLockQuery: opts.scrollLockQuery });
    return createElement("button", {
      ref: closeBtn,
      "data-testid": "drawer-close",
      type: "button",
    });
  };
  const view = render(createElement(Harness));
  const closeBtn = document.querySelector<HTMLElement>("[data-testid=drawer-close]")!;
  return { onClose, closeBtn, view };
}

describe("useNavDrawer", () => {
  it("does nothing while closed", () => {
    renderDrawer(false);
    expect(document.body.classList.contains("nav-drawer-open")).toBe(false);
  });

  it("focuses the drawer close button while open", () => {
    const { closeBtn } = renderDrawer(true);
    expect(document.activeElement).toBe(closeBtn);
  });

  it("closes on Escape while open", () => {
    const { onClose } = renderDrawer(true);
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("removes the scroll lock and restores focus on close/unmount", () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    let view!: ReturnType<typeof renderDrawer>["view"];
    withOverlayViewport(() => {
      view = renderDrawer(true).view;
      expect(document.body.classList.contains("nav-drawer-open")).toBe(true);
    });
    view.unmount();
    expect(document.body.classList.contains("nav-drawer-open")).toBe(false);
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("does not lock body scroll on viewports where the drawer is static", () => {
    // setup.ts matchMedia polyfill returns matches:false -> the hook must not lock.
    renderDrawer(true, { scrollLockQuery: "(max-width: 1023px)" });
    expect(document.body.classList.contains("nav-drawer-open")).toBe(false);
  });

  it("locks body scroll when the media query matches (overlay viewport)", () => {
    withOverlayViewport(() => {
      renderDrawer(true, { scrollLockQuery: "(max-width: 767px)" });
      expect(document.body.classList.contains("nav-drawer-open")).toBe(true);
    });
  });
});
