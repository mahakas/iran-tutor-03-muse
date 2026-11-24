"use client";

import Link from "next/link";
import {
  BookOpen,
  ClipboardList,
  Layers,
  NotebookPen,
  PlayCircle,
  RotateCcw,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useMemo } from "react";
import { pickContinueTarget } from "@/lib/handoffs";
import { formatDateTime, formatNumber } from "@/lib/i18n";
import type { ChatSessionSummary, ExamSummary } from "@/lib/types";
import { useStudentHomeData } from "@/lib/useStudentHomeData";

export type StudentHomeDashboardProps = {
  lang: "fa" | "en";
  isAuthenticated: boolean;
  context: {
    gradeTitle?: string;
    branchTitle?: string;
    majorTitle?: string;
    bookTitle?: string | null;
    bookId?: number | null;
  };
  /** Capability flags (same registry StudentSideNav uses). */
  capabilities: {
    quiz: boolean;
    flashcards: boolean;
    mistake_bank: boolean;
    learning_notebook: boolean;
    immersive_reader?: boolean;
  };
  chatSessions: ChatSessionSummary[];
  exams: ExamSummary[];
  onContinueChat: (chatId: string) => void;
  onContinueExam: (examId: string) => void;
  /** Scrolls to the real curriculum picker (#today-class) — the honest start. */
  onStart: () => void;
  onRequireLogin: () => void;
};

type CardProps = { title: string; icon: React.ReactNode; children: React.ReactNode; className?: string };

function DashboardCard({ title, icon, children, className }: CardProps) {
  return (
    <section className={`home-card ${className ?? ""}`} aria-label={title}>
      <div className="home-card-head">
        {icon}
        <b>{title}</b>
      </div>
      {children}
    </section>
  );
}

export default function StudentHomeDashboard({
  lang,
  isAuthenticated,
  context,
  capabilities,
  chatSessions,
  exams,
  onContinueChat,
  onContinueExam,
  onStart,
  onRequireLogin,
}: StudentHomeDashboardProps) {
  const en = lang === "en";
  const homeData = useStudentHomeData({
    flashcardsEnabled: isAuthenticated && capabilities.flashcards,
    mistakeBankEnabled: isAuthenticated && capabilities.mistake_bank,
    notebookEnabled: isAuthenticated && capabilities.learning_notebook,
  });

  const activeExams = useMemo(() => exams.filter((exam) => exam.status === "active"), [exams]);
  const submittedExams = useMemo(
    () => exams.filter((exam) => exam.status !== "active"),
    [exams]
  );
  const recentChats = useMemo(
    () =>
      [...chatSessions]
        .sort((a, b) => (Date.parse(b.updated_at ?? "") || 0) - (Date.parse(a.updated_at ?? "") || 0))
        .slice(0, 3),
    [chatSessions]
  );
  const recentExams = useMemo(
    () =>
      [...exams]
        .sort(
          (a, b) =>
            (Date.parse(b.created_at ?? "") || 0) - (Date.parse(a.created_at ?? "") || 0)
        )
        .slice(0, 3),
    [exams]
  );

  const continueTarget = isAuthenticated
    ? pickContinueTarget({
        activeExams,
        chatSessions,
        dueFlashcards: capabilities.flashcards ? homeData.dueFlashcards : null,
        openMistakes: capabilities.mistake_bank ? homeData.openMistakes : null,
        submittedExams,
      })
    : null;

  const continueCard = (() => {
    if (!isAuthenticated) {
      return (
        <div className="home-empty">
          <p>
            {en
              ? "Sign in to save your progress and pick up where you left off."
              : "برای ذخیرهٔ پیشرفت و ادامهٔ کار از همان‌جا که رها کردی، وارد شو."}
          </p>
          <button type="button" className="home-cta" onClick={onRequireLogin}>
            <PlayCircle size={16} /> {en ? "Sign in" : "ورود به درسیار"}
          </button>
        </div>
      );
    }
    if (!continueTarget) {
      const studyBookId = context.bookId ?? null;
      const canStudyBook = studyBookId !== null && capabilities.immersive_reader === true;
      return (
        <div className="home-empty">
          <p>
            {en
              ? "Nothing to continue yet. Pick your textbook and start your first lesson."
              : "هنوز فعالیت ثبت‌شده‌ای نداری. کتابت را انتخاب کن و اولین درس را شروع کن."}
          </p>
          <button type="button" className="home-cta" onClick={onStart}>
            <BookOpen size={16} /> {en ? "Pick a textbook" : "انتخاب کتاب"}
          </button>
          {canStudyBook && (
            <Link href={`/study/${studyBookId}`} className="home-cta">
              <BookOpen size={16} /> {en ? "Study book" : "مطالعهٔ کتاب"}
            </Link>
          )}
        </div>
      );
    }
    if (continueTarget.kind === "exam") {
      const resuming = continueTarget.status === "active";
      return (
        <div className="home-empty">
          <p>
            {resuming
              ? en
                ? `Unfinished exam: “${continueTarget.title}”.`
                : `آزمون نیمه‌تمام: «${continueTarget.title}»`
              : en
                ? `Last exam: “${continueTarget.title}”.`
                : `آخرین آزمون: «${continueTarget.title}»`}
          </p>
          <button
            type="button"
            className="home-cta"
            onClick={() => onContinueExam(continueTarget.id)}
          >
            <PlayCircle size={16} />
            {resuming
              ? en
                ? "Resume exam"
                : "ادامهٔ آزمون"
              : en
                ? "View report card"
                : "مشاهدهٔ کارنامه"}
          </button>
        </div>
      );
    }
    if (continueTarget.kind === "chat") {
      return (
        <div className="home-empty">
          <p>
            {en ? `Last conversation: “${continueTarget.title}”.` : `آخرین گفت‌وگو: «${continueTarget.title}»`}
          </p>
          <button
            type="button"
            className="home-cta"
            onClick={() => onContinueChat(continueTarget.id)}
          >
            <PlayCircle size={16} /> {en ? "Continue conversation" : "ادامهٔ گفت‌وگو"}
          </button>
        </div>
      );
    }
    if (continueTarget.kind === "flashcards") {
      return (
        <div className="home-empty">
          <p>
            {en
              ? `${formatNumber(continueTarget.dueCount, lang)} flashcards are due for review.`
              : `${formatNumber(continueTarget.dueCount, lang)} فلش‌کارت برای مرور سررسیده است.`}
          </p>
          <Link href="/flashcards" className="home-cta">
            <RotateCcw size={16} /> {en ? "Review now" : "شروع مرور"}
          </Link>
        </div>
      );
    }
    return (
      <div className="home-empty">
        <p>
          {en
            ? `${formatNumber(continueTarget.openCount, lang)} unresolved mistakes are waiting for practice.`
            : `${formatNumber(continueTarget.openCount, lang)} اشتباه حل‌نشده برای تمرین داری.`}
        </p>
        <Link href="/mistakes" className="home-cta">
          <XCircle size={16} /> {en ? "Practice mistakes" : "تمرین اشتباهات"}
        </Link>
      </div>
    );
  })();

  const todayPlanItems: React.ReactNode[] = [];
  if (isAuthenticated) {
    if (context.bookId && capabilities.immersive_reader) {
      todayPlanItems.push(
        <Link key="plan-study" href={`/study/${context.bookId}`} className="home-plan-chip">
          <BookOpen size={14} />
          {en ? "Study book" : "مطالعهٔ کتاب"}
        </Link>
      );
    }
    if (capabilities.flashcards && homeData.dueFlashcards !== null && homeData.dueFlashcards > 0) {
      todayPlanItems.push(
        <Link key="plan-due" href="/flashcards" className="home-plan-chip">
          <RotateCcw size={14} />
          {en
            ? `${formatNumber(homeData.dueFlashcards, lang)} due flashcards`
            : `${formatNumber(homeData.dueFlashcards, lang)} مرور فلش‌کارت سررسید`}
        </Link>
      );
    }
    if (capabilities.mistake_bank && homeData.openMistakes !== null && homeData.openMistakes > 0) {
      todayPlanItems.push(
        <Link key="plan-mistakes" href="/mistakes" className="home-plan-chip">
          <XCircle size={14} />
          {en
            ? `${formatNumber(homeData.openMistakes, lang)} unresolved mistakes`
            : `${formatNumber(homeData.openMistakes, lang)} اشتباه حل‌نشده`}
        </Link>
      );
    }
    if (activeExams.length > 0) {
      todayPlanItems.push(
        <button
          key="plan-exam"
          type="button"
          className="home-plan-chip"
          onClick={() => onContinueExam(activeExams[0].id)}
        >
          <ClipboardList size={14} />
          {en ? "1 exam in progress" : "۱ آزمون در جریان"}
        </button>
      );
    }
  }

  const contextLine = [
    context.gradeTitle,
    context.branchTitle,
    context.majorTitle,
    context.bookTitle,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="home-dashboard" aria-label={en ? "Continue learning" : "ادامهٔ یادگیری"}>
      <div className="home-dashboard-head">
        <div>
          <b>{en ? "Continue learning" : "ادامهٔ یادگیری"}</b>
          {contextLine && <span>{contextLine}</span>}
        </div>
      </div>
      <div className="home-grid">
        <DashboardCard
          title={en ? "Pick up where you left off" : "ادامه بده"}
          icon={<PlayCircle size={15} />}
        >
          {continueCard}
        </DashboardCard>

        <DashboardCard title={en ? "Today" : "برنامهٔ امروز"} icon={<Sparkles size={15} />}>
          {!isAuthenticated ? (
            <p className="home-note">
              {en ? "Sign in to see your plan." : "برای دیدن برنامهٔ امروز وارد شو."}
            </p>
          ) : todayPlanItems.length > 0 ? (
            <div className="home-plan-list">{todayPlanItems}</div>
          ) : homeData.loading ? (
            <div className="home-loading" role="status">
              <span className="skeleton skeleton-line" aria-hidden="true" />
              <span className="skeleton skeleton-line short" aria-hidden="true" />
              <span className="sr-only">{en ? "Checking your plan…" : "در حال بررسی…"}</span>
            </div>
          ) : (
            <p className="home-note">
              {en
                ? "No reviews are due and no exam is open today."
                : "امروز مرور سررسیدی و آزمون بازی نداری."}
            </p>
          )}
          {homeData.errors.due && (
            <p className="home-error" role="alert">{en ? "Review data is unavailable." : "دادهٔ مرورها در دسترس نیست."}</p>
          )}
          {homeData.errors.mistakes && (
            <p className="home-error" role="alert">
              {en ? "Mistake data is unavailable." : "دادهٔ اشتباهات در دسترس نیست."}
            </p>
          )}
        </DashboardCard>

        {isAuthenticated && (recentChats.length > 0 || recentExams.length > 0) && (
          <DashboardCard title={en ? "Recent activity" : "فعالیت اخیر"} icon={<BookOpen size={15} />}>
            <ul className="home-recent-list">
              {recentChats.map((chat) => (
                <li key={`chat-${chat.id}`}>
                  <button type="button" onClick={() => onContinueChat(chat.id)}>
                    <span className="home-recent-title">{chat.title || (en ? "Conversation" : "گفت‌وگو")}</span>
                    <span className="home-recent-meta">
                      {formatDateTime(chat.updated_at, lang)}
                    </span>
                  </button>
                </li>
              ))}
              {recentExams.map((exam) => (
                <li key={`exam-${exam.id}`}>
                  <button type="button" onClick={() => onContinueExam(exam.id)}>
                    <span className="home-recent-title">{exam.title}</span>
                    <span className="home-recent-meta">
                      {exam.status === "active"
                        ? en
                          ? "In progress"
                          : "در جریان"
                        : formatDateTime(exam.submitted_at ?? exam.created_at, lang)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </DashboardCard>
        )}

        {isAuthenticated &&
          ((homeData.decks !== null && homeData.decks.length > 0) ||
            (homeData.notebooks !== null && homeData.notebooks.length > 0)) && (
            <DashboardCard title={en ? "Saved items" : "ذخیره‌شده‌ها"} icon={<Layers size={15} />}>
              <ul className="home-saved-list">
                {(homeData.decks ?? []).map((deck) => (
                  <li key={`deck-${deck.id}`}>
                    <Link href="/flashcards">
                      <Layers size={14} />
                      <span className="home-recent-title">{deck.title}</span>
                      <span className="home-recent-meta">
                        {deck.due > 0
                          ? `${formatNumber(deck.due, lang)} ${en ? "due" : "سررسید"}`
                          : `${formatNumber(deck.total, lang)} ${en ? "cards" : "کارت"}`}
                      </span>
                    </Link>
                  </li>
                ))}
                {(homeData.notebooks ?? []).map((notebook) => (
                  <li key={`nb-${notebook.id}`}>
                    <Link href="/notebook">
                      <NotebookPen size={14} />
                      <span className="home-recent-title">{notebook.title}</span>
                      <span className="home-recent-meta">
                        {`${formatNumber(notebook.block_count, lang)} ${en ? "blocks" : "بلوک"}`}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
              {homeData.errors.decks && (
                <p className="home-error" role="alert">{en ? "Deck list is unavailable." : "فهرست دسته‌ها در دسترس نیست."}</p>
              )}
              {homeData.errors.notebooks && (
                <p className="home-error" role="alert">{en ? "Notebook list is unavailable." : "فهرست دفترچه‌ها در دسترس نیست."}</p>
              )}
            </DashboardCard>
          )}
      </div>
    </section>
  );
}
