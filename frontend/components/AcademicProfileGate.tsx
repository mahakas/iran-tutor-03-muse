"use client";

import { useCallback, useEffect, useState } from "react";
import { GraduationCap } from "lucide-react";
import AcademicProfilePicker from "@/components/AcademicProfilePicker";
import { useAppContext } from "@/components/AppProvider";
import { academicProfileErrorMessage, type AcademicProfileResponse } from "@/lib/academicProfile";

export type AcademicProfileGateProps = {
  onSaved?: (payload: {
    gradeNumber: number;
    branchCode: string | null;
    groundCode: string | null;
    fieldCode: string | null;
  }) => void;
};

/**
 * Shows the academic picker only while the signed-in student has no grade on
 * their profile ("first entry into grade-dependent features"). Once a placement
 * exists the gate renders nothing — full editing stays on the profile page and
 * the picker can be reopened there at any time.
 */
export default function AcademicProfileGate({ onSaved }: AcademicProfileGateProps) {
  const { authFetch, preferences } = useAppContext();
  const en = preferences.general.language === "en";
  const [state, setState] = useState<"loading" | "incomplete" | "complete" | "error">("loading");

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/account/academic-profile");
      const payload = (await res.json().catch(() => null)) as AcademicProfileResponse | null;
      if (!res.ok || !payload) {
        setState("error");
        return;
      }
      setState(payload.profile.exists && payload.profile.grade_number !== null ? "complete" : "incomplete");
    } catch {
      setState("error");
    }
  }, [authFetch]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  if (state === "complete" || state === "error") {
    return state === "error" ? null : null;
  }
  return (
    <section className="account-card academic-profile-card home-dashboard" aria-live="polite">
      <div className="academic-picker-head">
        <GraduationCap size={16} />
        <b>{en ? "One first step before studying" : "یک قدم اول پیش از شروع"}</b>
      </div>
      <p className="academic-picker-note">
        {en
          ? "Pick your grade (and track/program for grades 10–12) to unlock your textbooks, tutor, and exams. No approval is needed — it saves instantly and you can change it anytime."
          : "برای باز شدن کتاب‌ها، معلم خصوصی و آزمون‌ها، پایهٔ خود را انتخاب کن (پایه‌های ۱۰ تا ۱۲: شاخه، زمینه و رشته). هیچ تأییدی لازم نیست؛ بلافاصله ذخیره می‌شود و هر زمان می‌توانی تغییرش بدهی."}
      </p>
      <AcademicProfilePicker
        compact
        onSaved={(payload) => {
          setState("complete");
          onSaved?.(payload);
        }}
      />
    </section>
  );
}
