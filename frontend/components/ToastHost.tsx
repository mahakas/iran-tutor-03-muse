"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { TOAST_EVENT, type ToastPayload, type ToastTone } from "@/lib/toast";

type Item = ToastPayload & { id: number };

const MAX_VISIBLE = 4;
const DURATION_MS: Record<ToastTone, number> = { success: 4000, info: 4500, error: 7000 };

export default function ToastHost() {
  const [items, setItems] = useState<Item[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  useEffect(() => {
    const onToast = (event: Event) => {
      const detail = (event as CustomEvent<ToastPayload>).detail;
      if (!detail?.message) return;
      const id = nextId.current++;
      setItems((current) => [...current, { ...detail, id }].slice(-MAX_VISIBLE));
      window.setTimeout(() => dismiss(id), DURATION_MS[detail.tone]);
    };
    window.addEventListener(TOAST_EVENT, onToast);
    return () => window.removeEventListener(TOAST_EVENT, onToast);
  }, [dismiss]);

  if (items.length === 0) return null;

  return (
    <div className="toast-host" aria-live="polite">
      {items.map((item) => {
        const Icon = item.tone === "success" ? CheckCircle2 : item.tone === "error" ? XCircle : Info;
        return (
          <div
            key={item.id}
            className={`toast toast-${item.tone}`}
            role={item.tone === "error" ? "alert" : "status"}
          >
            <Icon size={18} aria-hidden="true" />
            <span className="toast-text">{item.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="بستن پیام"
              onClick={() => dismiss(item.id)}
            >
              <X size={16} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
