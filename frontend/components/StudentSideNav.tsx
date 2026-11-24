"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  BookOpenCheck,
  Calculator,
  GraduationCap,
  Home,
  Layers,
  Library,
  Mic,
  NotebookPen,
  Route,
  Search,
  Trash2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Fragment } from "react";
import { formatNumber } from "@/lib/i18n";

type StudentSideNavProps = {
  lang: "fa" | "en";
  /** Capability gating, computed by the caller from /api/v1/capabilities/me. */
  enabled: {
    chat: boolean;
    quiz: boolean;
    flashcards: boolean;
    mistake_bank: boolean;
    mastery_path: boolean;
    deep_solve: boolean;
    learning_notebook: boolean;
    living_book: boolean;
    audio_podcast: boolean;
  };
  isAuthenticated: boolean;
  examHistoryCount: number;
  /** Close the mobile drawer after any navigation. */
  onAfterNavigate: () => void;
  onOpenTutor: () => void;
  onOpenExams: () => void;
  onOpenChatSearch: () => void;
  onOpenChatBin: () => void;
};

type RouteItem = { kind: "route"; href: string; icon: LucideIcon; label: string };
type ActionItem = {
  kind: "action";
  icon: LucideIcon;
  label: string;
  onAction: () => void;
  badge?: string;
};
type NavItem = RouteItem | ActionItem;

// The six student areas map onto routes that already exist — no new pages. Route
// items derive their active state from the URL (usePathname), so refresh,
// back/forward and deep links all stay consistent with the highlighted item.
export default function StudentSideNav({
  lang,
  enabled,
  isAuthenticated,
  examHistoryCount,
  onAfterNavigate,
  onOpenTutor,
  onOpenExams,
  onOpenChatSearch,
  onOpenChatBin,
}: StudentSideNavProps) {
  const pathname = usePathname();
  const en = lang === "en";

  const allAreas: Array<{ title: string; items: NavItem[] }> = [
    {
      title: en ? "Home" : "خانه",
      items: [
        { kind: "route", href: "/", icon: Home, label: en ? "Classroom" : "کلاس درس" },
      ],
    },
    {
      title: en ? "My Teacher" : "معلم من",
      items: [
        ...(enabled.chat
          ? [
              {
                kind: "action",
                icon: BookOpen,
                label: en ? "Personal Tutor" : "معلم خصوصی",
                onAction: onOpenTutor,
              } as ActionItem,
            ]
          : []),
        ...(isAuthenticated
          ? [
              {
                kind: "action",
                icon: Search,
                label: en ? "Search chats" : "جستجوی گفت‌وگوها",
                onAction: onOpenChatSearch,
              } as ActionItem,
              {
                kind: "action",
                icon: Trash2,
                label: en ? "Recycle Bin" : "سطل بازیافت",
                onAction: onOpenChatBin,
              } as ActionItem,
            ]
          : []),
      ],
    },
    {
      title: en ? "Learning" : "یادگیری",
      items: [
        ...(enabled.living_book
          ? [{ kind: "route", href: "/living-book", icon: BookOpenCheck, label: en ? "Living book" : "کتاب زنده فصل" } as RouteItem]
          : []),
        ...(enabled.learning_notebook
          ? [{ kind: "route", href: "/notebook", icon: NotebookPen, label: en ? "Notebook" : "دفترچهٔ یادداشت" } as RouteItem]
          : []),
        ...(enabled.audio_podcast
          ? [{ kind: "route", href: "/podcast", icon: Mic, label: en ? "Podcast" : "پادکست آموزشی" } as RouteItem]
          : []),
      ],
    },
    {
      title: en ? "Practice" : "تمرین",
      items: [
        ...(enabled.quiz
          ? [
              {
                kind: "action",
                icon: GraduationCap,
                label: en ? "My Exams" : "آزمون‌های من",
                onAction: onOpenExams,
                badge:
                  examHistoryCount > 0 ? formatNumber(examHistoryCount, lang) : undefined,
              } as ActionItem,
            ]
          : []),
        ...(enabled.flashcards
          ? [{ kind: "route", href: "/flashcards", icon: Layers, label: en ? "Flashcards" : "فلش‌کارت‌ها" } as RouteItem]
          : []),
        ...(enabled.mistake_bank
          ? [{ kind: "route", href: "/mistakes", icon: XCircle, label: en ? "Mistake bank" : "بانک اشتباهات" } as RouteItem]
          : []),
        ...(enabled.deep_solve
          ? [{ kind: "route", href: "/deep-solve", icon: Calculator, label: en ? "Deep solve" : "حل گام‌به‌گام" } as RouteItem]
          : []),
      ],
    },
    {
      title: en ? "Progress" : "پیشرفت",
      items: [
        ...(enabled.mastery_path
          ? [{ kind: "route", href: "/mastery", icon: Route, label: en ? "Mastery path" : "مسیر تسلط" } as RouteItem]
          : []),
      ],
    },
    {
      title: en ? "Library" : "کتابخانه",
      items: [
        // Anchors to the real curriculum picker on the classroom page — the
        // destination exists, no duplicate route is created.
        {
          kind: "route",
          href: "/#today-class",
          icon: Library,
          label: en ? "Textbooks" : "کتاب‌های درسی",
        },
      ],
    },
  ];

  const areas = allAreas.filter((area) => area.items.length > 0);

  return (
    <nav aria-label={en ? "Student navigation" : "ناوبری دانش‌آموز"}>
      {areas.map((area) => (
        <Fragment key={area.title}>
          <div className="sidebar-section-label">{area.title}</div>
          {area.items.map((item) => {
            const Icon = item.icon;
            const isActive = item.kind === "route" && pathname === item.href;
            const className = `sidebar-item${isActive ? " active" : ""}`;
            return item.kind === "route" ? (
              <Link
                key={item.href}
                href={item.href}
                className={className}
                onClick={onAfterNavigate}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </Link>
            ) : (
              <button
                key={item.label}
                type="button"
                className={className}
                onClick={item.onAction}
              >
                <Icon size={17} />
                <span>{item.label}</span>
                {item.badge && <span className="side-badge">{item.badge}</span>}
              </button>
            );
          })}
        </Fragment>
      ))}
    </nav>
  );
}
