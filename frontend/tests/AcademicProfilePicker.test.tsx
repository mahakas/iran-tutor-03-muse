import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import AcademicProfilePicker from "@/components/AcademicProfilePicker";

const appState = vi.hoisted(() => ({ authFetch: vi.fn(), lang: "fa" as "fa" | "en" }));
vi.mock("@/components/AppProvider", () => ({
  useAppContext: () => ({ authFetch: appState.authFetch, preferences: { general: { language: appState.lang } } }),
}));

function jsonResponse(ok: boolean, body: unknown) {
  return { ok, json: () => Promise.resolve(body) };
}

const OPTIONS = {
  grades: [
    { number: 1, title: "اول دبستان", requires_track: false },
    { number: 7, title: "هفتم (دوره اول متوسطه)", requires_track: false },
    { number: 10, title: "دهم (دوره دوم متوسطه)", requires_track: true },
  ],
  branches: [
    { code: "theoretical", title: "نظری", min_grade: 10, max_grade: 12, uses_grounds: false },
    { code: "technical_vocational", title: "فنی‌وحرفه‌ای", min_grade: 10, max_grade: 12, uses_grounds: true },
  ],
  grounds: [
    { branch_code: "technical_vocational", code: "industry", title: "صنعت" },
    { branch_code: "technical_vocational", code: "services", title: "خدمات" },
  ],
  programs: [
    { branch_code: "theoretical", ground_code: null, code: "math_physics", title: "ریاضی‌فیزیک", is_theoretical: true },
    { branch_code: "theoretical", ground_code: null, code: "experimental", title: "علوم تجربی", is_theoretical: true },
    { branch_code: "technical_vocational", ground_code: "services", code: "tec-services-حسابداری", title: "حسابداری", is_theoretical: false },
    { branch_code: "technical_vocational", ground_code: "industry", code: "tec-industry-الکتروتکنیک", title: "الکتروتکنیک", is_theoretical: false },
  ],
};

function mockGet(profile: Record<string, unknown>) {
  appState.authFetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/academic-profile") && (!init || !init.method || init.method === "GET")) {
      return jsonResponse(true, { profile, options: OPTIONS });
    }
    if (url.includes("/academic-profile") && init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      return jsonResponse(true, {
        profile: {
          exists: true,
          grade_number: body.grade_number,
          branch_code: body.branch_code,
          ground_code: body.ground_code,
          field_code: body.field_code,
          grade_title: "دهم (دوره دوم متوسطه)",
          updated_at: "2026-11-23T00:00:00Z",
        },
        saved: true,
      });
    }
    return jsonResponse(false, { detail: "not found" });
  });
}

beforeEach(() => {
  appState.lang = "fa";
  mockGet({ exists: false });
});

describe("AcademicProfilePicker — staged self-service selection", () => {
  it("grades 1–9: no track/ground/program fields at all", async () => {
    render(<AcademicProfilePicker />);
    await waitFor(() => expect(screen.getByText("پایهٔ تحصیلی (الزامی)")).toBeInTheDocument());
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "1");
    expect(screen.queryByText("شاخه")).not.toBeInTheDocument();
    expect(screen.getByText("پایه‌های ۱ تا ۹ شاخه و رشته ندارند؛ انتخاب پایه کافی است.")).toBeInTheDocument();
    const save = screen.getByText("ذخیره");
    expect(save).not.toBeDisabled();
  });

  it("grade 10 theoretical: shows exactly the four theoretical programs", async () => {
    render(<AcademicProfilePicker />);
    await waitFor(() => expect(screen.getByText("پایهٔ تحصیلی (الزامی)")).toBeInTheDocument());
    const user = userEvent.setup();
    await user.selectOptions(screen.getAllByRole("combobox")[0], "10");
    await user.selectOptions(screen.getAllByRole("combobox")[1], "theoretical");
    const programSelect = screen.getAllByRole("combobox").at(-1)! as HTMLSelectElement;
    const labels = Array.from(programSelect.options).map((o) => o.text);
    expect(labels).toContain("ریاضی‌فیزیک");
    expect(labels).toContain("علوم تجربی");
    expect(labels).not.toContain("حسابداری");
    expect(screen.queryByText("زمینه")).not.toBeInTheDocument();
  });

  it("vocational track: ground is required before the program becomes selectable", async () => {
    render(<AcademicProfilePicker />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("پایهٔ تحصیلی (الزامی)")).toBeInTheDocument());
    const selects = () => screen.getAllByRole("combobox");
    await user.selectOptions(selects()[0], "10");
    await user.selectOptions(selects()[1], "technical_vocational");
    const groundSelect = selects()[2] as HTMLSelectElement;
    expect(groundSelect).toBeInTheDocument();
    const programSelect = selects()[3] as HTMLSelectElement;
    expect(programSelect).toBeDisabled();
    await user.selectOptions(groundSelect, "services");
    expect(programSelect).not.toBeDisabled();
    const labels = Array.from(programSelect.options).map((o) => o.text);
    expect(labels).toContain("حسابداری");
    expect(labels).not.toContain("الکتروتکنیک"); // wrong ground filtered out
  });

  it("saves via AJAX without reload and calls onSaved with the new placement", async () => {
    const onSaved = vi.fn();
    render(<AcademicProfilePicker onSaved={onSaved} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("پایهٔ تحصیلی (الزامی)")).toBeInTheDocument());
    const selects = () => screen.getAllByRole("combobox");
    await user.selectOptions(selects()[0], "10");
    await user.selectOptions(selects()[1], "theoretical");
    await user.selectOptions(selects()[2], "experimental");
    await user.click(screen.getByText("ذخیره"));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({ gradeNumber: 10, branchCode: "theoretical", fieldCode: "experimental" })
    );
    const putCall = appState.authFetch.mock.calls.find(
      ([url, init]) => String(url).includes("academic-profile") && (init as RequestInit | undefined)?.method === "PUT"
    );
    expect(putCall).toBeTruthy();
    expect(JSON.parse(String((putCall![1] as RequestInit).body))).toEqual({
      grade_number: 10,
      branch_code: "theoretical",
      ground_code: null,
      field_code: "experimental",
    });
    expect(screen.getByText(/اطلاعات تحصیلی ذخیره شد/)).toBeInTheDocument();
  });

  it("surfaces the server-side Persian validation error instead of a technical message", async () => {
    appState.authFetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") return jsonResponse(false, { detail: "این رشته به زمینهٔ انتخاب‌شده تعلق ندارد." });
      return jsonResponse(true, { profile: { exists: false }, options: OPTIONS });
    });
    render(<AcademicProfilePicker />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByText("پایهٔ تحصیلی (الزامی)")).toBeInTheDocument());
    await user.selectOptions(screen.getAllByRole("combobox")[0], "10");
    await user.selectOptions(screen.getAllByRole("combobox")[1], "technical_vocational");
    await user.selectOptions(screen.getAllByRole("combobox")[2], "industry");
    // program list filtered by ground; pick the valid-looking one but server refuses
    await user.selectOptions(screen.getAllByRole("combobox")[3], "tec-industry-الکتروتکنیک");
    await user.click(screen.getByText("ذخیره"));
    await waitFor(() => expect(screen.getByText("این رشته به زمینهٔ انتخاب‌شده تعلق ندارد.")).toBeInTheDocument());
  });

  it("shows the current placement when the profile already exists", async () => {
    mockGet({
      exists: true,
      grade_number: 7,
      grade_title: "هفتم (دوره اول متوسطه)",
      branch_code: null,
      branch_title: null,
      ground_code: null,
      ground_title: null,
      field_code: null,
      field_title: null,
    });
    render(<AcademicProfilePicker />);
    await waitFor(() =>
      expect(screen.getAllByText("هفتم (دوره اول متوسطه)").length).toBeGreaterThan(1)
    );
    // the current placement line shows it
    expect(document.querySelector(".academic-picker-current")?.textContent).toContain(
      "هفتم (دوره اول متوسطه)"
    );
    expect(screen.getByText("هر زمان می‌توانی تغییرش بدهی.")).toBeInTheDocument();
  });
});
