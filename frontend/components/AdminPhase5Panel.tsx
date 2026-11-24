"use client";

import { useState } from "react";
import { toPersianDigits, type MasteryTree } from "@/lib/phase5";

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

type Section = "mistakes" | "mastery" | "deep" | "validator" | "evidence" | "settings" | "logs";

type Json = Record<string, unknown>;

const SECTIONS: Array<{ key: Section; label: string }> = [
  { key: "mistakes", label: "بانک اشتباهات دانش‌آموز" },
  { key: "mastery", label: "پیشرفت تسلط" },
  { key: "deep", label: "جلسه‌های حل گام‌به‌گام" },
  { key: "validator", label: "سؤال‌های ردشده/اصلاح‌شده" },
  { key: "evidence", label: "بازبینی شواهد یادگیری" },
  { key: "settings", label: "آستانه و قفل فصل‌ها" },
  { key: "logs", label: "گزارش اقدامات مدیر" },
];

export default function AdminPhase5Panel({ authHeaders, onUnauthorized }: Props) {
  const [section, setSection] = useState<Section>("mistakes");
  const [userId, setUserId] = useState("");
  const [bookId, setBookId] = useState("");
  const [verdict, setVerdict] = useState("");
  const [evidenceStatus, setEvidenceStatus] = useState("unverified");
  const [reviewNote, setReviewNote] = useState("");
  const [data, setData] = useState<Json | null>(null);
  const [tree, setTree] = useState<MasteryTree | null>(null);
  const [threshold, setThreshold] = useState("0.8");
  const [unlockMode, setUnlockMode] = useState("sequential");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const call = async (url: string, init?: RequestInit): Promise<Json | null> => {
    const res = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      ...init,
      headers: { ...authHeaders, ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    });
    if (res.status === 401 || res.status === 403) {
      onUnauthorized();
      return null;
    }
    const payload = (await res.json().catch(() => null)) as Json | null;
    if (!res.ok) {
      setMessage(typeof payload?.detail === "string" ? payload.detail : "خطا در دریافت اطلاعات.");
      return null;
    }
    return payload;
  };

  const load = async () => {
    setBusy(true);
    setMessage(null);
    try {
      if (section === "settings") {
        if (!bookId) return setMessage("شناسهٔ کتاب را وارد کنید.");
        const payload = await call(`/api/v1/admin/mastery/books/${bookId}/settings`);
        if (payload) {
          setThreshold(String(payload.threshold ?? 0.8));
          setUnlockMode(String(payload.unlock_mode ?? "sequential"));
          setTree(null);
          setData(payload);
        }
        if (userId.trim()) {
          const treeRes = await call(
            `/api/v1/admin/users/${encodeURIComponent(userId.trim())}/mastery?book_id=${bookId}`,
          );
          if (treeRes && treeRes.chapters) setTree(treeRes as unknown as MasteryTree);
        }
        return;
      }
      if (section === "logs") {
        setData(await call(`/api/v1/admin/action-logs?target=${encodeURIComponent(userId || "")}`));
        return;
      }
      if (section === "evidence") {
        const params = new URLSearchParams({ verification_status: evidenceStatus, limit: "100" });
        if (userId.trim()) params.set("user_id", userId.trim());
        if (bookId.trim()) params.set("book_id", bookId.trim());
        setData(await call(`/api/v1/admin/mastery/evidence?${params.toString()}`));
        return;
      }
      if (!userId.trim()) return setMessage("شناسهٔ کاربر را وارد کنید.");
      const base = `/api/v1/admin/users/${encodeURIComponent(userId.trim())}`;
      if (section === "mistakes") setData(await call(`${base}/mistakes?limit=100`));
      if (section === "mastery") {
        const payload = await call(`${base}/mastery${bookId ? `?book_id=${bookId}` : ""}`);
        setData(payload);
        setTree(payload && payload.chapters ? (payload as unknown as MasteryTree) : null);
      }
      if (section === "deep") setData(await call(`${base}/deep-solve-sessions`));
      if (section === "validator") {
        setData(await call(`${base}/quiz-validation${verdict ? `?verdict=${verdict}` : ""}`));
      }
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async () => {
    if (!bookId) return setMessage("شناسهٔ کتاب را وارد کنید.");
    const payload = await call(`/api/v1/admin/mastery/books/${bookId}/settings`, {
      method: "PUT",
      body: JSON.stringify({ threshold: Number(threshold), unlock_mode: unlockMode }),
    });
    if (payload) setMessage("تنظیمات ذخیره شد.");
  };

  const setOverride = async (chapter: number, override: "locked" | "open" | null) => {
    const payload = await call(`/api/v1/admin/mastery/books/${bookId}/chapters/${chapter}/override`, {
      method: "PUT",
      body: JSON.stringify({ override }),
    });
    if (payload) setMessage(`وضعیت فصل ${toPersianDigits(chapter)} ذخیره شد.`);
  };

  const rows = (data?.items as Json[] | undefined) ?? [];

  const reviewEvidence = async (evidenceId: number, verificationStatus: "verified" | "rejected") => {
    if (verificationStatus === "rejected" && !reviewNote.trim()) {
      setMessage("برای رد شاهد یادگیری، دلیل بازبینی را وارد کنید.");
      return;
    }
    const payload = await call(`/api/v1/admin/mastery/evidence/${evidenceId}/review`, {
      method: "PATCH",
      body: JSON.stringify({
        verification_status: verificationStatus,
        review_note: reviewNote.trim() || null,
      }),
    });
    if (payload) {
      await load();
      setMessage(verificationStatus === "verified" ? "شاهد یادگیری تأیید شد." : "شاهد یادگیری رد شد.");
      setReviewNote("");
    }
  };

  return (
    <section dir="rtl" style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {SECTIONS.map((item) => (
          <button key={item.key} type="button" className={section === item.key ? "btn-primary" : "btn-ghost"} onClick={() => { setSection(item.key); setData(null); setTree(null); }}>
            {item.label}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {section !== "settings" ? (
          <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="شناسهٔ کاربر (user id)" aria-label="شناسهٔ کاربر" />
        ) : null}
        {section === "mastery" || section === "settings" || section === "evidence" ? (
          <input value={bookId} onChange={(e) => setBookId(e.target.value.replace(/\D/g, ""))} placeholder="شناسهٔ کتاب (اختیاری)" aria-label="شناسهٔ کتاب" />
        ) : null}
        {section === "validator" ? (
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)} aria-label="وضعیت داوری">
            <option value="">همه</option>
            <option value="approved">تأیید</option>
            <option value="fixed">اصلاح‌شده</option>
            <option value="rejected">ردشده</option>
          </select>
        ) : null}
        {section === "evidence" ? (
          <select value={evidenceStatus} onChange={(e) => setEvidenceStatus(e.target.value)} aria-label="وضعیت شواهد یادگیری">
            <option value="unverified">در انتظار بازبینی</option>
            <option value="verified">تأییدشده</option>
            <option value="rejected">ردشده</option>
            <option value="all">همهٔ وضعیت‌ها</option>
          </select>
        ) : null}
        {section === "evidence" ? (
          <input value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="یادداشت بازبینی؛ برای رد شاهد الزامی است" aria-label="یادداشت بازبینی؛ برای رد شاهد الزامی است" />
        ) : null}
        <button type="button" className="btn-primary" disabled={busy} onClick={() => void load()}>
          نمایش
        </button>
        {message ? <span role="status">{message}</span> : null}
      </div>


      {section === "evidence" ? (
        <div style={{ display: "grid", gap: 10 }}>
          {rows.length === 0 ? (
            <div className="glass-panel" style={{ padding: 14 }}>شاهدی با این فیلترها پیدا نشد.</div>
          ) : rows.map((row, index) => (
            <article key={String(row.id ?? index)} className="glass-panel" style={{ padding: 14, display: "grid", gap: 7 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <strong>{String(row.objective_title ?? "هدف یادگیری")}</strong>
                <span>{String(row.verification_status ?? "نامشخص")}</span>
              </div>
              <div style={{ fontSize: 13 }}>دانش‌آموز: {String(row.student_name ?? row.user_id ?? "—")} · پایه: {String(row.student_grade ?? "—")}</div>
              <div style={{ fontSize: 13 }}>کتاب: {String(row.book_title ?? "کتاب نامشخص")} · درس: {String(row.subject_title ?? "—")}</div>
              <div style={{ fontSize: 13 }}>هدف: {String(row.objective_code ?? "—")} · واحد: {String(row.unit_title ?? "—")}</div>
              <div style={{ fontSize: 13 }}>
                نوع شاهد: {String(row.source_type ?? "—")} · امتیاز: {String(row.score ?? "—")}
                {row.qualitative_level ? ` · سطح: ${String(row.qualitative_level)}` : ""}
              </div>
              {row.pdf_page_index !== null && row.pdf_page_index !== undefined ? (
                <div style={{ fontSize: 12, opacity: 0.75 }}>صفحه PDF: {String(row.pdf_page_index)} · صفحه چاپی: {String(row.printed_page_number ?? "—")}</div>
              ) : null}
              {row.feedback ? <div style={{ fontSize: 13 }}>توضیح دانش‌آموز: {String(row.feedback)}</div> : null}
              {row.review_note ? <div style={{ fontSize: 13 }}>یادداشت بازبین: {String(row.review_note)}</div> : null}
              {row.reviewed_by ? <div style={{ fontSize: 11, opacity: 0.65 }}>بازبین: {String(row.reviewed_by)}</div> : null}
              {row.observed_at ? <div style={{ fontSize: 11, opacity: 0.65 }}>تاریخ ثبت: {String(row.observed_at)}</div> : null}
              {row.verification_status === "unverified" ? (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button type="button" className="btn-primary" onClick={() => void reviewEvidence(Number(row.id), "verified")}>تأیید شاهد</button>
                  <button type="button" className="btn-ghost" onClick={() => void reviewEvidence(Number(row.id), "rejected")}>رد شاهد</button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}

      {section === "settings" ? (
        <div className="glass-panel" style={{ padding: 14, display: "grid", gap: 10 }}>
          <label>
            آستانهٔ تسلط (۰٫۳ تا ۱)
            <input type="number" step="0.05" min={0.3} max={1} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </label>
          <label>
            حالت باز شدن فصل‌ها{" "}
            <select value={unlockMode} onChange={(e) => setUnlockMode(e.target.value)}>
              <option value="sequential">ترتیبی</option>
              <option value="open">باز</option>
            </select>
          </label>
          <button type="button" className="btn-primary" onClick={() => void saveSettings()}>
            ذخیرهٔ تنظیمات
          </button>
          {tree ? (
            <ul style={{ display: "grid", gap: 6, listStyle: "none", padding: 0 }}>
              {tree.chapters.map((chapter) => (
                <li key={chapter.chapter_number} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span>فصل {toPersianDigits(chapter.chapter_number)}: {chapter.chapter_title} — {chapter.status}</span>
                  <button type="button" className="btn-ghost" onClick={() => void setOverride(chapter.chapter_number, "locked")}>قفل</button>
                  <button type="button" className="btn-ghost" onClick={() => void setOverride(chapter.chapter_number, "open")}>باز</button>
                  <button type="button" className="btn-ghost" onClick={() => void setOverride(chapter.chapter_number, null)}>پیش‌فرض</button>
                </li>
              ))}
            </ul>
          ) : (
            <div style={{ fontSize: 13 }}>برای مدیریت قفل فصل‌ها، شناسهٔ یک کاربر و کتاب را وارد و «نمایش» را بزنید.</div>
          )}
        </div>
      ) : null}

      {section === "mastery" && tree ? (
        <ul style={{ display: "grid", gap: 6, listStyle: "none", padding: 0 }}>
          {tree.chapters.map((chapter) => (
            <li key={chapter.chapter_number} className="glass-panel" style={{ padding: 10 }}>
              فصل {toPersianDigits(chapter.chapter_number)}: {chapter.chapter_title} — {chapter.status} — امتیاز:{" "}
              {chapter.score === null ? "—" : `${toPersianDigits(Math.round(chapter.score * 100))}٪`}
            </li>
          ))}
        </ul>
      ) : null}

      {section !== "settings" && section !== "mastery" && section !== "logs" && section !== "evidence" && rows.length > 0 ? (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", fontSize: 13 }}>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id ?? index)} style={{ borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
                  {Object.entries(row)
                    .filter(([key]) => !["choices", "steps", "evidence", "correct_option", "explanation"].includes(key))
                    .slice(0, 8)
                    .map(([key, value]) => (
                      <td key={key} style={{ padding: 6, verticalAlign: "top" }}>
                        <div style={{ opacity: 0.6, fontSize: 11 }}>{key}</div>
                        <div>{typeof value === "object" ? JSON.stringify(value) : String(value ?? "—")}</div>
                      </td>
                    ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {section === "logs" && data ? (
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(data, null, 2)}</pre>
      ) : null}
    </section>
  );
}
