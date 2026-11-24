/**
 * Lightweight, dependency-free toast bus. Any client component can call `toast.success(...)`
 * without prop drilling; `<ToastHost />` (mounted once in the root layout) renders them.
 */
export type ToastTone = "success" | "error" | "info";

export type ToastPayload = { tone: ToastTone; message: string };

export const TOAST_EVENT = "darsyar:toast";

function emit(tone: ToastTone, message: string) {
  if (typeof window === "undefined" || !message) return;
  window.dispatchEvent(new CustomEvent<ToastPayload>(TOAST_EVENT, { detail: { tone, message } }));
}

export const toast = {
  success: (message: string) => emit("success", message),
  error: (message: string) => emit("error", message),
  info: (message: string) => emit("info", message),
};
