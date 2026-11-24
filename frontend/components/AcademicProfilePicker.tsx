"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, GraduationCap, LoaderCircle, Save, TriangleAlert } from "lucide-react";
import { useAppContext } from "@/components/AppProvider";
import {
  academicProfileErrorMessage,
  type AcademicProfileInfo,
  type AcademicProfileSavePayload,
  type AcademicProfileResponse,
  type PickerOptions,
} from "@/lib/academicProfile";

export type AcademicProfilePickerProps = {
  /** Called after a successful save so parents can refresh dependent state without a reload. */
  onSaved?: (payload: {
    gradeNumber: number;
    branchCode: string | null;
    groundCode: string | null;
    fieldCode: string | null;
  }) => void;
  compact?: boolean;
};

/**
 * Staged, self-service academic picker: پایه → شاخه → زمینه (هنرستانی) → رشته.
 * The student owns every choice; there is no approval step anywhere. Options are
 * filtered by the previous stage so an invalid combination cannot even be built,
 * and the server validates the combination again before saving.
 */
export default function AcademicProfilePicker({ onSaved, compact }: AcademicProfilePickerProps) {
  const { authFetch, preferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const en = lang === "en";

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [options, setOptions] = useState<PickerOptions | null>(null);
  const [current, setCurrent] = useState<AcademicProfileInfo | null>(null);

  const [gradeNumber, setGradeNumber] = useState<number | null>(null);
  const [branchCode, setBranchCode] = useState<string>("");
  const [groundCode, setGroundCode] = useState<string>("");
  const [fieldCode, setFieldCode] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await authFetch("/api/v1/account/academic-profile");
      const payload = (await res.json().catch(() => null)) as AcademicProfileResponse | null;
      if (!res.ok || !payload) {
        setLoadError(
          academicProfileErrorMessage(payload, en ? "Could not load the academic profile." : "بارگذاری اطلاعات تحصیلی ناموفق بود.")
        );
        return;
      }
      setOptions(payload.options ?? null);
      setCurrent(payload.profile);
      if (payload.profile.exists) {
        setGradeNumber(payload.profile.grade_number);
        setBranchCode(payload.profile.branch_code ?? "");
        setGroundCode(payload.profile.ground_code ?? "");
        setFieldCode(payload.profile.field_code ?? "");
      }
    } catch {
      setLoadError(en ? "Could not reach the server." : "ارتباط با سرور برقرار نشد");
    } finally {
      setLoading(false);
    }
  }, [authFetch, en]);

  useEffect(() => {
    // deferred: setState must not run synchronously inside the effect body
    queueMicrotask(() => void load());
  }, [load]);

  const selectedGrade = useMemo(
    () => options?.grades.find((g) => g.number === gradeNumber) ?? null,
    [options, gradeNumber]
  );
  const needsTrack = (selectedGrade?.requires_track ?? false) && gradeNumber !== null;
  const selectedBranch = options?.branches.find((b) => b.code === branchCode) ?? null;
  const branchGrounds = useMemo(
    () =>
      (options?.grounds ?? []).filter(
        (g) => selectedBranch?.uses_grounds && g.branch_code === branchCode
      ),
    [options, selectedBranch, branchCode]
  );
  const branchFields = useMemo(
    () =>
      (options?.programs ?? []).filter((p) =>
        selectedBranch?.uses_grounds
          ? p.branch_code === branchCode && p.ground_code === groundCode
          : p.branch_code === branchCode && p.is_theoretical
      ),
    [options, selectedBranch, groundCode, branchCode]
  );

  const resetStages = (nextGrade: number | null) => {
    setGradeNumber(nextGrade);
    setBranchCode("");
    setGroundCode("");
    setFieldCode("");
    setFeedback(null);
    setError(null);
  };

  const save = async () => {
    if (gradeNumber === null || saving) return;
    setSaving(true);
    setError(null);
    setFeedback(null);
    const payload: AcademicProfileSavePayload = {
      grade_number: gradeNumber,
      branch_code: needsTrack ? branchCode || null : null,
      ground_code: needsTrack && selectedBranch?.uses_grounds ? groundCode || null : null,
      field_code: needsTrack ? fieldCode || null : null,
    };
    try {
      const res = await authFetch("/api/v1/account/academic-profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await res.json().catch(() => null)) as AcademicProfileResponse | null;
      if (!res.ok || !body) {
        setError(
          academicProfileErrorMessage(body, en ? "Could not save the academic profile." : "ذخیرهٔ اطلاعات تحصیلی ناموفق بود.")
        );
        return;
      }
      setCurrent(body.profile);
      setFeedback(
        en
          ? "Academic placement saved. The tutor uses it from your next question."
          : "اطلاعات تحصیلی ذخیره شد؛ معلم خصوصی از سؤال بعدی همین پایه را به کار می‌برد."
      );
      onSaved?.({
        gradeNumber: body.profile.grade_number ?? gradeNumber,
        branchCode: body.profile.branch_code ?? null,
        groundCode: body.profile.ground_code ?? null,
        fieldCode: body.profile.field_code ?? null,
      });
    } catch {
      setError(en ? "Could not reach the server." : "ارتباط با سرور برقرار نشد");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="academic-picker academic-picker-loading" role="status">
        <LoaderCircle className="spin" size={16} />
        <span>{en ? "Loading…" : "در حال بارگذاری…"}</span>
      </div>
    );
  }
  if (loadError || !options) {
    return (
      <div className="academic-picker academic-picker-error" role="alert">
        <TriangleAlert size={15} />
        <span>{loadError ?? (en ? "Academic data is unavailable." : "اطلاعات تحصیلی در دسترس نیست.")}</span>
        <button type="button" className="outline-button" onClick={() => void load()}>
          {en ? "Retry" : "تلاش دوباره"}
        </button>
      </div>
    );
  }

  const stageReady =
    gradeNumber !== null &&
    (!needsTrack ||
      (selectedBranch?.uses_grounds
        ? Boolean(branchCode) && Boolean(groundCode) && Boolean(fieldCode)
        : Boolean(branchCode) && Boolean(fieldCode)));

  return (
    <div className={`academic-picker ${compact ? "academic-picker-compact" : ""}`} dir="rtl">
      <div className="academic-picker-head">
        <GraduationCap size={16} />
        <b>{en ? "Academic placement" : "پایه و رشتهٔ تحصیلی"}</b>
        {current?.exists && (
          <span className="academic-picker-current">
            {[
              current.grade_title,
              current.branch_title,
              current.ground_title,
              current.field_title,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
      </div>

      <div className="academic-picker-grid">
        <label className="form-field">
          <span>{en ? "Grade (required)" : "پایهٔ تحصیلی (الزامی)"}</span>
          <select
            value={gradeNumber ?? ""}
            onChange={(e) => resetStages(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{en ? "Select grade" : "انتخاب پایه"}</option>
            {options.grades.map((grade) => (
              <option key={grade.number} value={grade.number}>
                {grade.title}
              </option>
            ))}
          </select>
        </label>

        {needsTrack && (
          <label className="form-field">
            <span>{en ? "Track" : "شاخه"}</span>
            <select value={branchCode} onChange={(e) => { setBranchCode(e.target.value); setGroundCode(""); setFieldCode(""); }}>
              <option value="">{en ? "Select track" : "انتخاب شاخه"}</option>
              {options.branches
                .filter((b) => gradeNumber !== null && b.min_grade <= gradeNumber && gradeNumber <= b.max_grade)
                .map((branch) => (
                  <option key={branch.code} value={branch.code}>
                    {branch.title}
                  </option>
                ))}
            </select>
          </label>
        )}

        {needsTrack && selectedBranch?.uses_grounds && (
          <label className="form-field">
            <span>{en ? "Ground" : "زمینه"}</span>
            <select value={groundCode} onChange={(e) => { setGroundCode(e.target.value); setFieldCode(""); }} disabled={!branchCode}>
              <option value="">{en ? "Select ground" : "انتخاب زمینه"}</option>
              {branchGrounds.map((ground) => (
                <option key={ground.code} value={ground.code}>
                  {ground.title}
                </option>
              ))}
            </select>
          </label>
        )}

        {needsTrack && (
          <label className="form-field">
            <span>{en ? "Program" : "رشته"}</span>
            <select
              value={fieldCode}
              onChange={(e) => setFieldCode(e.target.value)}
              disabled={!branchCode || (selectedBranch?.uses_grounds && !groundCode)}
            >
              <option value="">{en ? "Select program" : "انتخاب رشته"}</option>
              {branchFields.map((program) => (
                <option key={program.code} value={program.code}>
                  {program.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {needsTrack && fieldCode &&
        (() => {
          const selected = branchFields.find((program) => program.code === fieldCode);
          const validity = selected?.validity_status;
          if (!validity || validity === "active") return null;
          const label =
            validity === "needs_verification"
              ? "نیازمند راستی‌آزمایی (فهرست کاری مالک)"
              : validity === "unknown"
                ? "نامشخص"
                : validity;
          return (
            <p className="academic-picker-note">
              وضعیت اعتبار رسمی این رشته: {label} — انتخاب شما بلافاصله ذخیره می‌شود و هیچ تأیید
              مدیریتی لازم ندارد.
            </p>
          );
        })()}

      {gradeNumber !== null && gradeNumber < 10 && (
        <p className="academic-picker-note">
          {en
            ? "Grades 1–9 have no track or program."
            : "پایه‌های ۱ تا ۹ شاخه و رشته ندارند؛ انتخاب پایه کافی است."}
        </p>
      )}

      {feedback && (
        <div className="success-note" role="status">
          <Check size={15} />
          <span>{feedback}</span>
        </div>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}

      <div className="academic-picker-actions">
        <button
          type="button"
          className="primary-button"
          onClick={() => void save()}
          disabled={!stageReady || saving}
        >
          {saving ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}
          <span>{en ? "Save placement" : "ذخیره"}</span>
        </button>
        {current?.exists && (
          <span className="academic-picker-updated">
            {en ? "You can change it anytime." : "هر زمان می‌توانی تغییرش بدهی."}
          </span>
        )}
      </div>
    </div>
  );
}
