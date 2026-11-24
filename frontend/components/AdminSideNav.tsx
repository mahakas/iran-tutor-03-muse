"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  Activity,
  GraduationCap,
  BookOpen,
  Cpu,
  Crown,
  Database,
  Eye,
  KeyRound,
  Layers,
  Menu,
  Mic,
  Palette,
  ShieldCheck,
  Sparkles,
  ToggleRight,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useNavDrawer } from "@/lib/useNavDrawer";

export type AdminNavKey =
  | "overview"
  | "observability"
  | "appearance"
  | "integrations"
  | "providers"
  | "capabilities"
  | "skills"
  | "flashcards"
  | "deep_learning"
  | "rich_study"
  | "books"
  | "kb"
  | "podcasts"
  | "users"
  | "plans"
  | "roles";

type NavItem = { key: AdminNavKey; label: string; icon: LucideIcon };
type NavCategory = { title: string; items: NavItem[] };

// Every tab that exists in /admin. The active tab is carried in the `?tab=`
// query parameter so admin sections are deep-linkable and survive refresh /
// back / forward. `podcasts` is the Phase 06 addition: a read-only view over
// the existing admin podcast endpoints (stats + episodes), no new backend.
export const ADMIN_TAB_KEYS: AdminNavKey[] = [
  "overview",
  "observability",
  "appearance",
  "integrations",
  "providers",
  "capabilities",
  "skills",
  "flashcards",
  "deep_learning",
  "rich_study",
  "books",
  "kb",
  "podcasts",
  "users",
  "plans",
  "roles",
];

export const ADMIN_DEFAULT_TAB: AdminNavKey = "books";

export function parseAdminTabParam(value: string | null | undefined): AdminNavKey {
  return ADMIN_TAB_KEYS.includes(value as AdminNavKey) ? (value as AdminNavKey) : ADMIN_DEFAULT_TAB;
}

// Category taxonomy from the Phase 01 information-architecture spec. The spec's
// "jobs queue / health" area has no dedicated tab in the current product: service
// health lives in overview, the book-processing queue in kb, and the review queue
// in observability, so those tabs carry that concern under their categories
// instead of a duplicate destination.
export const ADMIN_NAV_CATEGORIES: NavCategory[] = [
  {
    title: "نمای کلی و سلامت",
    items: [{ key: "overview", label: "نمای کلی، سلامت و تراکنش‌ها", icon: Activity }],
  },
  {
    title: "برنامه درسی و کتاب",
    items: [{ key: "books", label: "کتاب‌ها و پردازش PDF", icon: BookOpen }],
  },
  {
    title: "پردازش دانش",
    items: [
      { key: "kb", label: "پایگاه دانش و مدل‌ها", icon: Database },
      { key: "flashcards", label: "فلش‌کارت‌ها", icon: Layers },
      { key: "podcasts", label: "پادکست‌های آموزشی", icon: Mic },
      { key: "deep_learning", label: "یادگیری عمیق", icon: Layers },
      { key: "rich_study", label: "مطالعهٔ غنی", icon: Layers },
    ],
  },
  {
    title: "کاربران و دسترسی",
    items: [
      { key: "users", label: "کاربران و سهمیه‌ها", icon: Users },
      { key: "roles", label: "نقش‌ها و دسترسی", icon: ShieldCheck },
    ],
  },
  {
    title: "هوش مصنوعی: مدل‌ها و کلیدها",
    items: [
      { key: "providers", label: "ارائه‌دهنده‌ها و مسیر مدل", icon: KeyRound },
      { key: "integrations", label: "API، پیامک و درگاه‌ها", icon: Cpu },
    ],
  },
  {
    title: "قابلیت‌ها و مهارت‌ها",
    items: [
      { key: "capabilities", label: "قابلیت‌ها و فلگ‌ها", icon: ToggleRight },
      { key: "skills", label: "مهارت‌ها و پرامپت‌ها", icon: Sparkles },
    ],
  },
  {
    title: "مصرف و مالی",
    items: [{ key: "plans", label: "پلن‌ها و قیمت توکن", icon: Crown }],
  },
  {
    title: "کیفیت و ممیزی",
    items: [{ key: "observability", label: "مرکز شفافیت (Observability)", icon: Eye }],
  },
  {
    title: "تنظیمات",
    items: [{ key: "appearance", label: "ظاهر و دسترس‌پذیری", icon: Palette }],
  },
];

type Props = {
  active: string;
  onSelect: (key: AdminNavKey) => void;
};

export default function AdminSideNav({ active, onSelect }: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerCloseRef = useRef<HTMLButtonElement | null>(null);
  useNavDrawer({
    open: drawerOpen,
    onClose: () => setDrawerOpen(false),
    focusRef: drawerCloseRef,
    // The sidebar becomes an off-canvas drawer below 1024px (see globals.css).
    scrollLockQuery: "(max-width: 1023px)",
  });
  const activeItem = ADMIN_NAV_CATEGORIES.flatMap((c) => c.items).find((i) => i.key === active);

  const choose = (key: AdminNavKey) => {
    onSelect(key);
    setDrawerOpen(false);
  };

  return (
    <>
      <button
        type="button"
        className="admin-nav-toggle"
        aria-expanded={drawerOpen}
        aria-controls="admin-side-nav"
        onClick={() => setDrawerOpen(true)}
      >
        <Menu size={18} /> <span>{activeItem?.label ?? "بخش‌های مدیریت"}</span>
      </button>
      {drawerOpen && (
        <button
          type="button"
          className="admin-nav-scrim"
          aria-label="بستن منوی مدیریت"
          onClick={() => setDrawerOpen(false)}
        />
      )}
      <nav
        id="admin-side-nav"
        className={`admin-side-nav ${drawerOpen ? "open" : ""}`}
        aria-label="بخش‌های پنل مدیریت"
      >
        <div className="admin-nav-drawer-head">
          <b>بخش‌های مدیریت</b>
          <button
            type="button"
            ref={drawerCloseRef}
            className="icon-button"
            aria-label="بستن منو"
            onClick={() => setDrawerOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        {/* Standalone admin route (its own pages under /admin/education/*). A real
            href so it is openable in a new tab and highlights nothing inside /admin. */}
        <Link
          href="/admin/education"
          className="admin-nav-item admin-nav-standalone-link"
          onClick={() => setDrawerOpen(false)}
        >
          <GraduationCap size={16} /> <span>مدیریت نظام آموزشی و کاتالوگ درسی</span>
        </Link>
        {ADMIN_NAV_CATEGORIES.map((category) => (
          <div className="admin-nav-group" key={category.title}>
            <span className="admin-nav-group-title">{category.title}</span>
            {category.items.map((item) => {
              const Icon = item.icon;
              const isActive = active === item.key;
              // Real anchors: every tab is a stable /admin?tab=… URL (refresh,
              // back/forward, open-in-new-tab and prefetch all work natively).
              // onClick keeps the drawer-close + per-tab side-effect fetches.
              return (
                <Link
                  key={item.key}
                  href={`/admin?tab=${item.key}`}
                  className={`admin-nav-item ${isActive ? "active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => choose(item.key)}
                >
                  <Icon size={16} /> <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </>
  );
}
