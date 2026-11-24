// Academic profile (Iran Education Catalog 1405–1406) — typed client helpers.

export type AcademicProfileInfo = {
  exists: boolean;
  grade_number: number | null;
  grade_title: string | null;
  cycle_title: string | null;
  branch_code: string | null;
  branch_title: string | null;
  ground_code: string | null;
  ground_title: string | null;
  field_code: string | null;
  field_title: string | null;
  field_validity_status: string | null;
  academic_year_code: string | null;
  updated_at: string | null;
};

export type PickerGradeOption = { number: number; title: string; requires_track: boolean };
export type PickerBranchOption = {
  code: string;
  title: string;
  min_grade: number;
  max_grade: number;
  uses_grounds: boolean;
};
export type PickerGroundOption = { branch_code: string | null; code: string; title: string };
export type PickerProgramOption = {
  branch_code: string | null;
  ground_code: string | null;
  code: string;
  title: string;
  is_theoretical: boolean;
  validity_status?: string;
};

export type PickerOptions = {
  grades: PickerGradeOption[];
  branches: PickerBranchOption[];
  grounds: PickerGroundOption[];
  programs: PickerProgramOption[];
};

export type AcademicProfileResponse = {
  profile: AcademicProfileInfo;
  options?: PickerOptions;
  mirror?: { grade_level: number | null; major: string | null };
};

export type AcademicProfileSavePayload = {
  grade_number: number;
  branch_code: string | null;
  ground_code: string | null;
  field_code: string | null;
};

export function academicProfileErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return fallback;
}
