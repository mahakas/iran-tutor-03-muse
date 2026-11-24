"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, BookOpen, Check, ClipboardList, Clock3, Layers, LoaderCircle, RefreshCw, Send } from "lucide-react";
import MathContent from "@/components/MathContent";
import type { Exam, ExamReport } from "@/lib/types";

type Props = {
  exam: Exam;
  authHeaders?: Record<string, string>;
  onExit: () => void;
  /** Opens the new-exam setup in the classroom after the report; optional for reuse. */
  onStartNewExam?: () => void;
};

function formatTime(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function sourceLabel(source: ExamReport["by_question"][number]["source"]) {
  return source.citation ?? [source.book_title, source.chapter_title, source.printed_page_number && `صفحه ${source.printed_page_number}`]
    .filter(Boolean)
    .join(" · ");
}

function parseUtcMs(isoTimestamp: string): number {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(isoTimestamp);
  return Date.parse(hasTimezone ? isoTimestamp : `${isoTimestamp}Z`);
}

export default function ExamRunner({ exam, authHeaders, onExit, onStartNewExam }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const restored: Record<string, string> = {};
    for (const [key, value] of Object.entries(exam.submitted_answers ?? {})) {
      if (value) restored[key] = value;
    }
    return restored;
  });
  const [index, setIndex] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(() => Math.max(0, Math.ceil((parseUtcMs(exam.expires_at) - Date.now()) / 1000)));
  const [report, setReport] = useState<ExamReport | null>(() =>
    exam.status === "submitted" && exam.report_card ? exam.report_card : null
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sent = useRef(exam.status === "submitted" && Boolean(exam.report_card));
  const autoSubmitted = useRef(false);
  const question = exam.questions[index];
  const answeredCount = Object.keys(answers).length;
  const progress = useMemo(() => ((index + 1) / exam.questions.length) * 100, [index, exam.questions.length]);

  useEffect(() => {
    if (report) return;
    const timer = window.setInterval(() => {
      setSecondsLeft(Math.max(0, Math.ceil((parseUtcMs(exam.expires_at) - Date.now()) / 1000)));
    }, 500);
    return () => window.clearInterval(timer);
  }, [exam.expires_at, report]);

  const submit = useCallback(async () => {
    if (sent.current || report) return;
    sent.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/v1/exams/${exam.id}/submit`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          ...(authHeaders ?? {}),
        },
        body: JSON.stringify({ answers }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "ثبت پاسخ‌ها انجام نشد.");
      setReport(payload.report_card as ExamReport);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "خطا در ارتباط با سرور");
      sent.current = false;
    } finally {
      setBusy(false);
    }
  }, [answers, authHeaders, exam.id, report]);

  useEffect(() => {
    if (secondsLeft === 0 && !report && !sent.current && !autoSubmitted.current) {
      autoSubmitted.current = true;
      void submit();
    }
  }, [secondsLeft, report, submit]);

  const selectAnswer = (choice: string) => {
    if (!question || report || busy) return;
    setAnswers((previous) => ({ ...previous, [question.id]: choice }));
  };

  if (report) {
    return (
      <main className="exam-page" dir="rtl">
        <header className="exam-topbar">
          <div className="brand-mark small-mark">د</div>
          <div><b>کارنامهٔ آزمون</b><span>{exam.title}</span></div>
          <button className="quiet-button" onClick={onExit}>بازگشت به کلاس</button>
        </header>
        <section className="report-wrap">
          <div className="report-hero">
            <div className="report-score"><strong>{report.score}</strong><span>{report.scale === "percent" ? "درصد" : "از ۲۰"}</span></div>
            <div><span className="eyebrow">آزمون تمام شد</span><h1>{report.correct} پاسخ درست از {report.total_questions} سؤال</h1><p>هر پاسخ اشتباه را با منبع کتاب مرور کن و دوباره تلاش کن.</p></div>
          </div>
          <div className="report-stats">
            <div><b>{report.correct}</b><span>درست</span></div><div><b>{report.wrong}</b><span>غلط</span></div><div><b>{report.unanswered}</b><span>بی‌پاسخ</span></div>
          </div>
          <div className="report-actions" style={{ display: "flex", gap: 10, flexWrap: "wrap", marginInlineStart: 18 }}>
            {report.wrong > 0 || report.unanswered > 0 ? (
              <Link className="primary-button" href="/mistakes" style={{ display: "inline-flex", gap: 6, alignItems: "center", textDecoration: "none" }}>
                <ClipboardList size={16} /> مرور اشتباهات در بانک اشتباهات
              </Link>
            ) : null}
            {onStartNewExam ? (
              <button className="outline-button" onClick={onStartNewExam} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                <RefreshCw size={16} /> تمرین دوباره
              </button>
            ) : null}
            <Link className="outline-button" href={`/study/${exam.book_id}`} style={{ display: "inline-flex", gap: 6, alignItems: "center", textDecoration: "none" }}>
              <BookOpen size={16} /> منبع کتاب
            </Link>
            <Link className="text-button" href="/mastery" style={{ display: "inline-flex", gap: 6, alignItems: "center", textDecoration: "none" }}>
              <Layers size={16} /> شواهد تسلط
            </Link>
          </div>
          <div className="review-list">
            <h2>مرور پاسخ‌ها</h2>
            {report.by_question.map((item, itemIndex) => {
              const prompt = exam.questions.find((q) => q.id === item.id)?.prompt;
              return (
                <article className={`review-card ${item.correct ? "is-correct" : "is-wrong"}`} key={item.id}>
                  <div className="review-title"><span className="question-number">{itemIndex + 1}</span><b>{item.correct ? "پاسخ درست" : "نیاز به مرور"}</b><span>پاسخ شما: {item.answer ?? "بدون پاسخ"} · پاسخ درست: {item.correct_option}</span></div>
                  {prompt && <div className="review-prompt"><MathContent content={prompt} inline /></div>}
                  <MathContent content={item.explanation} />
                  {sourceLabel(item.source) && <small>منبع: {sourceLabel(item.source)}</small>}
                </article>
              );
            })}
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="exam-page" dir="rtl">
      <header className="exam-topbar">
        <div className="brand-mark small-mark">د</div>
        <div><b>{exam.title}</b><span>آزمون چهارگزینه‌ای · پاسخ‌ها تا پایان آزمون پنهان‌اند</span></div>
        <div className={`timer-pill ${secondsLeft < 60 ? "timer-warning" : ""}`}><Clock3 size={17} /><span>{formatTime(secondsLeft)}</span></div>
      </header>
      <section className="exam-layout">
        <aside className="exam-nav card-surface">
          <div className="exam-nav-head"><b>سؤال‌ها</b><span>{answeredCount} از {exam.questions.length} پاسخ داده‌شده</span></div>
          <div className="question-grid">
            {exam.questions.map((item, itemIndex) => (
              <button key={item.id} className={`question-jump ${index === itemIndex ? "current" : ""} ${answers[item.id] ? "answered" : ""}`} onClick={() => setIndex(itemIndex)}>{itemIndex + 1}</button>
            ))}
          </div>
          <div className="exam-instructions"><b>یادآوری</b><p>{exam.exam_type === "konkoor" ? "در حالت کنکور، پاسخ غلط نمرهٔ منفی دارد." : "نمرهٔ این آزمون در پایان از ۲۰ محاسبه می‌شود."}</p><p>زمان آزمون با سرور کنترل می‌شود.</p></div>
          <button className="text-button danger-text" onClick={() => { if (window.confirm("آزمون را همین حالا ثبت می‌کنی؟")) void submit(); }}>اتمام و ثبت آزمون</button>
        </aside>
        <section className="exam-question card-surface">
          <div className="exam-progress"><span style={{ width: `${progress}%` }} /></div>
          <div className="exam-question-meta"><span>سؤال {index + 1} از {exam.questions.length}</span><span>{question?.points ?? 1} نمره</span></div>
          <h1><MathContent content={question?.prompt ?? ""} inline /></h1>
          <div className="choices-list">
            {(["A", "B", "C", "D"] as const).map((choice) => (
              <button key={choice} className={`choice-card ${answers[question?.id] === choice ? "selected" : ""}`} onClick={() => selectAnswer(choice)}>
                <span className="choice-letter">{choice}</span><span className="choice-text"><MathContent content={question?.choices[choice] ?? ""} inline /></span>
                {answers[question?.id] === choice && <Check size={18} className="choice-check" />}
              </button>
            ))}
          </div>
          {error && <div className="inline-error"><AlertCircle size={17} />{error}</div>}
          <div className="exam-bottom-actions">
            <button className="outline-button" disabled={index === 0 || busy} onClick={() => setIndex((value) => Math.max(0, value - 1))}><ArrowRight size={17} /> قبلی</button>
            {index < exam.questions.length - 1 ? (
              <button className="primary-button" disabled={busy} onClick={() => setIndex((value) => Math.min(exam.questions.length - 1, value + 1))}>سؤال بعدی <ArrowLeft size={17} /></button>
            ) : (
              <button className="primary-button" disabled={busy} onClick={() => void submit()}>{busy ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />} ثبت و دریافت کارنامه</button>
            )}
          </div>
        </section>
      </section>
    </main>
  );
}
