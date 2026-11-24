"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ChevronUp,
  CircleHelp,
  Crown,
  LogIn,
  LogOut,
  Phone,
  Settings,
  User as UserIcon,
} from "lucide-react";
import AccountAvatar from "@/components/AccountAvatar";
import { useAppContext } from "@/components/AppProvider";
import { COPY, formatNumber } from "@/lib/i18n";

type AccountMenuProps = {
  onNavigate?: () => void;
};

export default function AccountMenu({ onNavigate }: AccountMenuProps) {
  const { user, preferences, openLoginModal, requestLogout } = useAppContext();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];

  useEffect(() => {
    if (!open) return;
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
  }, [open]);

  if (!user) {
    return (
      <div className="account-menu-anchor">
        <button
          type="button"
          className="login-sidebar-cta"
          onClick={() => {
            onNavigate?.();
            openLoginModal();
          }}
        >
          <div className="avatar">
            <Phone size={15} />
          </div>
          <div>
            <b>{copy.auth.loginCta}</b>
            <span>
              {lang === "en"
                ? "Start with free starter tokens"
                : "شروع با اعتبار هدیهٔ رایگان"}
            </span>
          </div>
          <LogIn size={15} />
        </button>
        <Link
          href="/account/help"
          className="sidebar-help-mini"
          onClick={() => onNavigate?.()}
        >
          <CircleHelp size={14} />
          <span>{copy.menu.help}</span>
        </Link>
      </div>
    );
  }

  const displayName =
    [user.first_name, user.last_name].filter(Boolean).join(" ").trim() ||
    user.full_name ||
    (preferences.privacy.show_phone_masked ? user.masked_phone : user.phone_number);

  const tokenProgressPct =
    user.tokens_total > 0
      ? Math.min(100, Math.max(0, Math.round((user.tokens_remaining / user.tokens_total) * 100)))
      : 0;

  return (
    <div className="account-menu-anchor" ref={rootRef}>
      {open && (
        <div
          className="account-popover"
          role="menu"
          aria-label={copy.menu.accountMenuAria}
        >
          <div className="account-popover-header">
            <AccountAvatar size={36} />
            <div className="account-popover-identity">
              <b>{displayName}</b>
              <span dir="ltr">
                {user.email ||
                  (preferences.privacy.show_phone_masked
                    ? user.masked_phone
                    : user.phone_number)}
              </span>
            </div>
            <span className={`plan-pill ${user.plan_code}`}>{user.plan_title}</span>
          </div>

          <div className="account-popover-quota">
            <div className="account-quota-row">
              <span>{copy.menu.remainingTokens}</span>
              <b>{formatNumber(user.tokens_remaining, lang)}</b>
            </div>
            <div className="account-quota-bar">
              <span style={{ width: `${tokenProgressPct}%` }} />
            </div>
            <div className="account-quota-foot">
              <small>
                {user.is_expired
                  ? copy.menu.expired
                  : `${formatNumber(user.days_remaining, lang)} ${copy.menu.daysLeft}`}
              </small>
              <Link
                href="/account/upgrade"
                className="account-mini-link"
                onClick={() => {
                  setOpen(false);
                  onNavigate?.();
                }}
              >
                {copy.menu.upgradePlan}
              </Link>
            </div>
          </div>

          <div className="account-popover-list">
            <Link
              href="/account/upgrade"
              role="menuitem"
              className="account-menu-item upgrade"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
            >
              <Crown size={16} />
              <span>{copy.menu.upgradePlan}</span>
              <small className="account-menu-pill">{user.plan_title}</small>
            </Link>

            <Link
              href="/account/profile"
              role="menuitem"
              className="account-menu-item"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
            >
              <UserIcon size={16} />
              <span>{copy.menu.profile}</span>
            </Link>

            <Link
              href="/account/settings/general"
              role="menuitem"
              className="account-menu-item"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
            >
              <Settings size={16} />
              <span>{copy.menu.settings}</span>
            </Link>

            <Link
              href="/account/help"
              role="menuitem"
              className="account-menu-item"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}
            >
              <CircleHelp size={16} />
              <span>{copy.menu.help}</span>
            </Link>
          </div>

          <div className="account-popover-divider" />

          <button
            type="button"
            role="menuitem"
            className="account-menu-item danger"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
              requestLogout();
            }}
          >
            <LogOut size={16} />
            <span>{copy.menu.logOut}</span>
          </button>
        </div>
      )}

      <button
        ref={triggerRef}
        type="button"
        className={`account-trigger ${open ? "open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={copy.menu.accountMenuAria}
        onClick={() => setOpen((prev) => !prev)}
      >
        <AccountAvatar size={34} />
        <div className="account-trigger-meta">
          <b>{displayName}</b>
          <span>
            {user.plan_title} · {formatNumber(user.tokens_remaining, lang)}{" "}
            {lang === "en" ? "tokens" : "توکن"}
          </span>
        </div>
        <ChevronUp size={16} className={`account-trigger-chevron ${open ? "open" : ""}`} />
      </button>
    </div>
  );
}
