"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";
import BookGradePicker from "@/components/BookGradePicker";
import {
  MASTERY_STATUS_LABEL,
  OBJECTIVE_MASTERY_STATUS_LABEL,
  nextChapterStep,
  phase5ErrorMessage,
  toPersianDigits,
  type MasteryTree,
  type ObjectiveMasteryItem,
  type ObjectiveMasteryTree,
} from "@/lib/phase5";

const QUALITATIVE_LEVELS = [
  { value: "needs_support", label: "نیازمند پشتیبانی" },
  { value: "developing", label: "در حال پیشرفت" },
  { value: "proficient", label: "مسلط" },
  { value: "advanced", label: "پیشرفته" },
  { value: "not_observed", label: "هنوز مشاهده نشده" },
] as const;

export default function MasteryWorkspace() {
  const { authFetch } = useAppContext();
  const [bookId, setBookId] = useState<number | null>(null);
  const [tree, setTree] = useState<MasteryTree | null>(null);
  const [objectiveTree, setObjectiveTree] = useState<ObjectiveMasteryTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedObjective, setSelectedObjective] = useState<number | null>(null);
  const [score, setScore] = useState("");
  const [qualitativeLevel, setQualitativeLevel] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshObjectives = useCallback(async (activeBookId: number) => {
    const res = await authFetch(`/api/v1/mastery/books/${activeBookId}/objectives`);
    const payload = await res.json().catch(() => null);
    if (!res.ok) throw new Error(phase5ErrorMessage(payload, "اهداف یادگیری در دسترس نیستند."));
    setObjectiveTree(payload as ObjectiveMasteryTree);
  }, [authFetch]);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    void (async () => {
      const [chapterResult, objectiveResult] = await Promise.allSettled([
        authFetch(`/api/v1/mastery/books/${bookId}`),
        authFetch(`/api/v1/mastery/books/${bookId}/objectives`),
      ]);
      if (cancelled) return;
      const errors: string[] = [];
      if (chapterResult.status === "fulfilled") {
        const payload = await chapterResult.value.json().catch(() => null);
        if (cancelled) return;
        if (chapterResult.value.ok) setTree(payload as MasteryTree);
        else errors.push(phase5ErrorMessage(payload, "مسیر تسلط فصل‌ها در دسترس نیست."));
      } else errors.push("دریافت مسیر تسلط فصل‌ها ناموفق بود.");
      if (objectiveResult.status === "fulfilled") {
        const payload = await objectiveResult.value.json().catch(() => null);
        if (cancelled) return;
        if (objectiveResult.value.ok) setObjectiveTree(payload as ObjectiveMasteryTree);
        else errors.push(phase5ErrorMessage(payload, "اهداف یادگیری در دسترس نیستند."));
      } else errors.push("دریافت اهداف یادگیری ناموفق بود.");
      if (!cancelled && errors.length) setError(errors.join(" "));
    })();
    return () => { cancelled = true; };
  }, [authFetch, bookId]);

  const submitEvidence = async (objective: ObjectiveMasteryItem) => {
    if (!bookId) return;
    const hasScore = score.trim() !== "";
    const hasLevel = qualitativeLevel !== "";
    if (objective.assessment_profile === "written" && !hasScore) {
      setNotice("برای این هدف، ثبت امتیاز از ۰ تا ۱۰۰ الزامی است.");
      return;
    }
    if ((objective.assessment_profile === "qualitative_descriptive" ||
      objective.assessment_profile === "performance") && !hasLevel) {
      setNotice("برای این هدف، انتخاب سطح توصیفی یا عملکردی الزامی است.");
      return;
    }
    if (objective.assessment_profile === "mixed" && !hasScore && !hasLevel) {
      setNotice("حداقل امتیاز یا سطح ارزیابی را وارد کنید.");
      return;
    }
    if (hasScore && (!Number.isFinite(Number(score)) || Number(score) < 0 || Number(score) > 100)) {
      setNotice("امتیاز باید عددی بین ۰ تا ۱۰۰ باشد.");
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const res = await authFetch("/api/v1/mastery/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          objective_id: objective.id,
          book_id: bookId,
          source_type: "self_assessment",
          source_ref: null,
          score: hasScore ? Number(score) : null,
          qualitative_level: hasLevel ? qualitativeLevel : null,
          rubric: {},
          feedback: feedback.trim() || null,
        }),
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setNotice(phase5ErrorMessage(payload, "ثبت خودارزیابی انجام نشد."));
        return;
      }
      setNotice("خودارزیابی ثبت شد؛ تا زمان بازبینی مدیر سامانه، تسلط قطعی محسوب نمی‌شود.");
      setSelectedObjective(null);
      setScore("");
      setQualitativeLevel("");
      setFeedback("");
      await refreshObjectives(bookId);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  };

  const shownTree = bookId && tree?.book.id === bookId ? tree : null;
  const shownObjectives =
    bookId && objectiveTree?.book.id === bookId ? objectiveTree : null;

  return (
    <div dir="rtl" style={{ display: "grid", gap: 16 }}>
      <BookGradePicker
        value={bookId}
        onChange={(nextBookId) => {
          setBookId(nextBookId);
          setTree(null);
          setObjectiveTree(null);
          setError(null);
          setNotice(null);
          setSelectedObjective(null);
          setScore("");
          setQualitativeLevel("");
          setFeedback("");
        }}
      />
      {!bookId ? <div className="glass-panel" style={{ padding: 20 }}>برای مشاهدهٔ مسیر یادگیری، یک کتاب رسمی را انتخاب کنید.</div> : null}
      {error ? <div className="glass-panel" role="alert" style={{ padding: 14 }}>{error}</div> : null}
      {notice ? <div className="glass-panel" role="status" style={{ padding: 14 }}>{notice}</div> : null}

      {shownTree ? (
        <>
          <div className="glass-panel" style={{ padding: 16, display: "flex", gap: 12, flexWrap: "wrap", justifyContent: "space-between" }}>
            <span>{shownTree.book.title} · {toPersianDigits(shownTree.mastered_count)} از {toPersianDigits(shownTree.chapters.length)} فصل تسلط‌یافته</span>
            <span>آستانهٔ تسلط: {toPersianDigits(Math.round(shownTree.threshold * 100))}٪ · حالت: {shownTree.unlock_mode === "sequential" ? "ترتیبی" : "باز"}</span>
            <Link href={`/study/${shownTree.book.id}`}>مطالعهٔ کتاب</Link>
          </div>
          <ol className="mastery-timeline" aria-label="مسیر فصل‌های تسلط">
            {shownTree.chapters.map((chapter) => {
              const percent = chapter.score === null ? null : Math.round(chapter.score * 100);
              return (
                <li key={chapter.chapter_number} className="glass-panel mastery-node" data-status={chapter.status} style={{ padding: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <strong>فصل {toPersianDigits(chapter.chapter_number)}: {chapter.chapter_title}</strong>
                    <span>{MASTERY_STATUS_LABEL[chapter.status]}</span>
                  </div>
                  <div role="progressbar" aria-valuenow={percent ?? 0} aria-valuemin={0} aria-valuemax={100}
                    aria-label={`پیشرفت فصل ${chapter.chapter_number}`}
                    style={{ height: 8, borderRadius: 6, background: "rgba(0,0,0,0.08)", marginTop: 8, overflow: "hidden" }}>
                    <div style={{ width: `${percent ?? 0}%`, height: "100%", background: "#16a34a" }} />
                  </div>
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    {percent === null ? "هنوز داده‌ای ثبت نشده" : `تسلط: ${toPersianDigits(percent)}٪`}
                    {chapter.locked_reason === "previous_chapter_not_mastered" ? " · قفل تا تسلط فصل قبل" : ""}
                    {chapter.locked_reason === "admin_locked" ? " · قفل توسط مدیر" : ""}
                  </div>
                  {(() => {
                    const next = nextChapterStep(chapter);
                    if (!next) return null;
                    return (
                      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginTop: 8, fontSize: 13 }}>
                        <span style={{ opacity: 0.8 }} role="note">گام بعدی: {next.reason}.</span>
                        <Link href={next.href} className="btn-ghost" style={{ textDecoration: "none" }}>{next.label}</Link>
                      </div>
                    );
                  })()}
                </li>
              );
            })}
          </ol>
        </>
      ) : null}

      {shownObjectives ? (
        <section style={{ display: "grid", gap: 10 }}>
          <div className="glass-panel" style={{ padding: 16 }}>
            <strong>تسلط بر اهداف یادگیری</strong>
            <p style={{ margin: "6px 0 0", fontSize: 13, opacity: 0.8 }}>
              وضعیت هر هدف از شواهد همین نسخهٔ کتاب محاسبه می‌شود. خودارزیابی شما به‌تنهایی تسلط را تأیید نمی‌کند.
            </p>
            {shownObjectives.academic_year_code ? <div style={{ fontSize: 12, marginTop: 6 }}>سال تحصیلی: {shownObjectives.academic_year_code}</div> : null}
          </div>
          {shownObjectives.message ? <div className="glass-panel" style={{ padding: 14 }}>{shownObjectives.message}</div> : null}
          {shownObjectives.objectives.map((objective) => (
            <article key={objective.id} className="glass-panel" style={{ padding: 14, display: "grid", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <strong>{objective.title}</strong>
                <span>{OBJECTIVE_MASTERY_STATUS_LABEL[objective.status]}</span>
              </div>
              <div style={{ fontSize: 12, opacity: 0.75 }}>{objective.subject.title} · {objective.unit.title} · کد {objective.code}</div>
              {objective.description ? <div style={{ fontSize: 13 }}>{objective.description}</div> : null}
              {objective.score !== null ? <div style={{ fontSize: 13 }}>امتیاز تأییدشده: {toPersianDigits(objective.score)}٪</div> : null}
              {objective.qualitative_level ? <div style={{ fontSize: 13 }}>سطح تأییدشده: {objective.qualitative_level}</div> : null}
              {objective.prerequisites.length ? <div style={{ fontSize: 12, opacity: 0.75 }}>پیش‌نیازها: {objective.prerequisites.map((item) => item.title).join("، ")}</div> : null}
              {objective.latest_evidence ? (
                <div style={{ fontSize: 12, opacity: 0.8 }}>
                  آخرین شاهد: {objective.latest_evidence.source_type}
                  {objective.latest_evidence.verification_status === "unverified"
                    ? " · در انتظار بازبینی"
                    : objective.latest_evidence.verification_status === "rejected"
                      ? " · ردشده"
                      : " · بازبینی‌شده"}
                  {objective.latest_evidence.review_note ? ` · یادداشت بازبین: ${objective.latest_evidence.review_note}` : ""}
                </div>
              ) : null}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span style={{ fontSize: 12 }}>تعداد شواهد: {toPersianDigits(objective.evidence_count)}</span>
                <button type="button" className="btn-ghost" disabled={busy || objective.status === "locked"}
                  onClick={() => {
                    setSelectedObjective(selectedObjective === objective.id ? null : objective.id);
                    setScore("");
                    setQualitativeLevel("");
                    setFeedback("");
                    setNotice(null);
                  }}>
                  {selectedObjective === objective.id ? "بستن خودارزیابی" : "ثبت خودارزیابی"}
                </button>
              </div>
              {selectedObjective === objective.id ? (
                <div style={{ display: "grid", gap: 8, borderTop: "1px solid rgba(0,0,0,0.1)", paddingTop: 12 }}>
                  {objective.assessment_profile === "written" || objective.assessment_profile === "mixed" ? (
                    <label style={{ display: "grid", gap: 4 }}>امتیاز خودارزیابی (۰ تا ۱۰۰)
                      <input type="number" min={0} max={100} value={score} onChange={(event) => setScore(event.target.value)} placeholder="مثلاً ۸۰" />
                    </label>
                  ) : null}
                  {objective.assessment_profile !== "written" ? (
                    <label style={{ display: "grid", gap: 4 }}>سطح عملکرد
                      <select value={qualitativeLevel} onChange={(event) => setQualitativeLevel(event.target.value)}>
                        <option value="">انتخاب سطح</option>
                        {QUALITATIVE_LEVELS.map((level) => <option key={level.value} value={level.value}>{level.label}</option>)}
                      </select>
                    </label>
                  ) : null}
                  <label style={{ display: "grid", gap: 4 }}>توضیح یا دلیل خودارزیابی
                    <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} maxLength={4000}
                      placeholder="چه چیزی را یاد گرفته‌اید؟ کدام بخش هنوز دشوار است؟" />
                  </label>
                  <button type="button" className="btn-primary" disabled={busy} onClick={() => void submitEvidence(objective)}>
                    {busy ? "در حال ثبت…" : "ارسال برای بازبینی"}
                  </button>
                </div>
              ) : null}
            </article>
          ))}
        </section>
      ) : null}
    </div>
  );
}
