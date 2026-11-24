"use client";

import { useEffect, useRef, type RefObject } from "react";

type NavDrawerOptions = {
  open: boolean;
  onClose: () => void;
  /** Element to focus once the drawer is mounted (usually its close button). */
  focusRef?: RefObject<HTMLElement | null>;
  /**
   * Body scroll is locked only while this media query matches, so a drawer that is
   * static (always visible) on desktop never freezes the page scroll.
   */
  scrollLockQuery?: string;
};

/**
 * Shared behaviour for off-canvas navigation drawers (student sidebar, admin sidenav):
 * Escape closes, focus moves to the drawer on open and returns to the trigger on
 * close, and the body scroll is locked only on the viewport widths where the drawer
 * actually overlays the page.
 */
export function useNavDrawer({ open, onClose, focusRef, scrollLockQuery = "(max-width: 767px)" }: NavDrawerOptions) {
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    document.body.classList.add("nav-drawer-open");
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);

    const lockQuery = window.matchMedia(scrollLockQuery);
    const scrollWasLocked = lockQuery.matches;
    if (!scrollWasLocked) document.body.classList.remove("nav-drawer-open");

    const focusTarget = focusRef?.current ?? null;
    // Effects run after the DOM commit, so the drawer (and its ref) is mounted here.
    focusTarget?.focus();

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("nav-drawer-open");
      const restore = restoreFocusRef.current;
      if (restore && restore.isConnected) restore.focus();
    };
  }, [open, onClose, focusRef, scrollLockQuery]);
}
