"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

export type ThemedSelectOption = {
  value: string;
  label: string;
};

type ThemedSelectProps = {
  label: string;
  value: string;
  placeholder: string;
  emptyOptionLabel?: string;
  options: ThemedSelectOption[];
  disabled?: boolean;
  className?: string;
  onChange: (value: string) => void;
};

export default function ThemedSelect({
  label,
  value,
  placeholder,
  emptyOptionLabel,
  options,
  disabled = false,
  className = "",
  onChange,
}: ThemedSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listboxId = useId();

  const selected = options.find((opt) => opt.value === value);
  const displayLabel = selected ? selected.label : placeholder;
  const isOpen = open && !disabled;

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  const allItems: Array<{ value: string; label: string }> = emptyOptionLabel
    ? [{ value: "", label: emptyOptionLabel }, ...options]
    : options;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) {
        setOpen(true);
        return;
      }
      if (!allItems.length) return;
      const idx = allItems.findIndex((item) => item.value === value);
      const nextIdx =
        event.key === "ArrowDown"
          ? (idx + 1) % allItems.length
          : (idx - 1 + allItems.length) % allItems.length;
      onChange(allItems[nextIdx].value);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen((prev) => !prev);
    }
  };

  return (
    <div
      ref={rootRef}
      className={`select-wrap ${className} ${isOpen ? "open" : ""} ${
        disabled ? "disabled" : ""
      }`.trim()}
    >
      <button
        ref={triggerRef}
        type="button"
        className={`themed-select-trigger ${!selected ? "placeholder" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? listboxId : undefined}
        aria-label={`${label}: ${displayLabel}`}
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={handleKeyDown}
      >
        <span className="themed-select-label">{label}</span>
        <span className="themed-select-value">{displayLabel}</span>
        <ChevronDown size={15} className={isOpen ? "rotated" : ""} />
      </button>

      {isOpen && (
        <div
          id={listboxId}
          role="listbox"
          aria-label={label}
          className="themed-select-menu"
        >
          {allItems.map((item) => {
            const isSelected = item.value === value;
            return (
              <button
                key={item.value || "__empty__"}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={`themed-select-option ${isSelected ? "selected" : ""}`}
                onClick={() => {
                  onChange(item.value);
                  setOpen(false);
                  triggerRef.current?.focus();
                }}
              >
                <span>{item.label}</span>
                {isSelected && <Check size={14} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
