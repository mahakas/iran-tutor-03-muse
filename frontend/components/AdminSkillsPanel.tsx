"use client";

import { useCallback, useEffect, useState } from "react";

type SkillRow = {
  id: number;
  slug: string;
  capability_key: string;
  title_fa: string;
  version: number;
  is_active: boolean;
  updated_by: string | null;
};

type SkillVersionRow = {
  id: number;
  version: number;
  change_note: string | null;
  created_by: string | null;
};

type SkillDetail = SkillRow & {
  system_prompt: string;
  pedagogy_rules_md: string;
  safety_gate_rules: string;
  versions: SkillVersionRow[];
};

type TestResult = {
  skill_slug: string;
  skill_version: number;
  model_name: string | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  audit_id: string | null;
  status: string;
  answer: string;
};

type Props = {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

/** Admin editor for prompts / pedagogy rules with versioning and rollback. */
export default function AdminSkillsPanel({ authHeaders, onUnauthorized }: Props) {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [draft, setDraft] = useState({ system_prompt: "", pedagogy_rules_md: "", safety_gate_rules: "", change_note: "" });
  const [sample, setSample] = useState("");
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const guard = useCallback(
    (status: number) => {
      if (status === 401 || status === 403) {
        onUnauthorized();
        return false;
      }
      return status >= 200 && status < 300;
    },
    [onUnauthorized],
  );

  const loadList = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/admin/skills", { cache: "no-store", credentials: "same-origin", headers: authHeaders });
      if (!guard(response.status)) return;
      const payload = (await response.json()) as { skills: SkillRow[] };
      setSkills(payload.skills);
      setSelected((current) => current ?? payload.skills[0]?.slug ?? null);
    } catch {
      setError("بارگذاری مهارت‌ها ناموفق بود.");
    }
  }, [authHeaders, guard]);

  const loadDetail = useCallback(
    async (slug: string) => {
      try {
        const response = await fetch(`/api/v1/admin/skills/${slug}`, { cache: "no-store", credentials: "same-origin", headers: authHeaders });
        if (!guard(response.status)) return;
        const payload = (await response.json()) as SkillDetail;
        setError("");
        setDetail(payload);
        setDraft({
          system_prompt: payload.system_prompt,
          pedagogy_rules_md: payload.pedagogy_rules_md,
          safety_gate_rules: payload.safety_gate_rules,
          change_note: "",
        });
        setTestResult(null);
      } catch {
        setError("بارگذاری جزئیات مهارت ناموفق بود.");
      }
    },
    [authHeaders, guard],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    void loadList();
  }, [loadList]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount; setState runs after await
    if (selected) void loadDetail(selected);
  }, [selected, loadDetail]);

  async function save() {
    if (!selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/api/v1/admin/skills/${selected}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(draft),
      });
      if (!guard(response.status)) return;
      if (!response.ok) throw new Error("save failed");
      setNotice("نسخهٔ جدید مهارت ذخیره شد.");
      await loadList();
      await loadDetail(selected);
    } catch {
      setError("ذخیرهٔ مهارت ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function rollback(version: number) {
    if (!selected) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/api/v1/admin/skills/${selected}/rollback`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ to_version: version }),
      });
      if (!guard(response.status)) return;
      if (!response.ok) throw new Error("rollback failed");
      setNotice(`نسخهٔ ${version} بازگردانی شد (به‌صورت نسخهٔ جدید ثبت شد).`);
      await loadList();
      await loadDetail(selected);
    } catch {
      setError("بازگردانی نسخه ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (!selected || !sample.trim()) return;
    setBusy(true);
    setError("");
    setTestResult(null);
    try {
      const response = await fetch(`/api/v1/admin/skills/${selected}/test`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ sample_input: sample }),
      });
      if (!guard(response.status)) return;
      if (!response.ok) throw new Error("test failed");
      setTestResult((await response.json()) as TestResult);
    } catch {
      setError("آزمایش مهارت ناموفق بود.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive() {
    if (!selected || !detail) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/v1/admin/skills/${selected}`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ is_active: !detail.is_active }),
      });
      if (!guard(response.status)) return;
      await loadList();
      await loadDetail(selected);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-panel" dir="rtl">
      <header className="admin-panel-head">
        <h2>مهارت‌ها و قوانین تدریس</h2>
        <p>
          پرامپت سیستمی، قوانین آموزشی و گیت ایمنی هر مهارت قابل ویرایش است. هر ذخیره یک نسخهٔ جدید می‌سازد و بازگردانی نیز به‌صورت نسخهٔ تازه ثبت می‌شود.
        </p>
      </header>
      {error && <p className="admin-error">{error}</p>}
      {notice && <p className="admin-notice">{notice}</p>}
      <div className="admin-two-col">
        <aside className="admin-list">
          {skills.map((skill) => (
            <button
              key={skill.slug}
              type="button"
              className={`admin-list-item ${selected === skill.slug ? "active" : ""}`}
              onClick={() => setSelected(skill.slug)}
            >
              <strong>{skill.title_fa}</strong>
              <span className="admin-muted" dir="ltr">
                {skill.slug} · v{skill.version} · {skill.is_active ? "فعال" : "غیرفعال"}
              </span>
            </button>
          ))}
        </aside>
        {detail && (
          <div className="admin-editor">
            <div className="admin-row">
              <span className="admin-muted" dir="ltr">
                {detail.slug} → {detail.capability_key} · نسخهٔ {detail.version}
              </span>
              <button type="button" className="admin-btn" disabled={busy} onClick={() => void toggleActive()}>
                {detail.is_active ? "غیرفعال‌سازی" : "فعال‌سازی"}
              </button>
            </div>
            <label className="admin-field">
              <span>پرامپت سیستمی</span>
              <textarea
                rows={10}
                value={draft.system_prompt}
                onChange={(event) => setDraft({ ...draft, system_prompt: event.target.value })}
              />
            </label>
            <label className="admin-field">
              <span>قوانین آموزشی (Markdown)</span>
              <textarea
                rows={5}
                value={draft.pedagogy_rules_md}
                onChange={(event) => setDraft({ ...draft, pedagogy_rules_md: event.target.value })}
              />
            </label>
            <label className="admin-field">
              <span>گیت ایمنی</span>
              <textarea
                rows={3}
                value={draft.safety_gate_rules}
                onChange={(event) => setDraft({ ...draft, safety_gate_rules: event.target.value })}
              />
            </label>
            <label className="admin-field">
              <span>یادداشت تغییر</span>
              <input
                type="text"
                value={draft.change_note}
                onChange={(event) => setDraft({ ...draft, change_note: event.target.value })}
              />
            </label>
            <button type="button" className="admin-btn primary" disabled={busy} onClick={() => void save()}>
              ذخیره به‌عنوان نسخهٔ جدید
            </button>

            <h3>تاریخچهٔ نسخه‌ها</h3>
            <ul className="admin-versions">
              {detail.versions.map((version) => (
                <li key={version.id}>
                  <span dir="ltr">v{version.version}</span> — {version.change_note || "بدون یادداشت"}{" "}
                  {version.version !== detail.version && (
                    <button type="button" className="admin-btn" disabled={busy} onClick={() => void rollback(version.version)}>
                      بازگردانی
                    </button>
                  )}
                </li>
              ))}
            </ul>

            <h3>آزمایش مهارت</h3>
            <textarea rows={3} value={sample} onChange={(event) => setSample(event.target.value)} placeholder="یک سؤال نمونه بنویسید…" />
            <button type="button" className="admin-btn" disabled={busy || !sample.trim()} onClick={() => void runTest()}>
              اجرای آزمایش (از ai_gateway)
            </button>
            {testResult && (
              <div className="admin-test-result">
                <div className="admin-muted" dir="ltr">
                  model={testResult.model_name || "—"} · {testResult.latency_ms ?? "—"}ms · in={testResult.tokens_in ?? "—"} out={testResult.tokens_out ?? "—"} · audit={testResult.audit_id || "—"}
                </div>
                <pre className="admin-pre">{testResult.answer}</pre>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
