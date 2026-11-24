"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  FileUp,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import {
  ADMIN_CATALOG_ENTITIES,
  ADMIN_CATALOG_VIEWS,
  type AdminCatalogEntityConfig,
  type AdminCatalogField,
} from "@/lib/adminCatalog";

type Row = Record<string, unknown>;

type ListResponse = { items: Row[]; total: number; page: number; page_size: number };

function detail(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const d = (payload as { detail: unknown }).detail;
    if (typeof d === "string" && d.trim()) return d;
  }
  return fallback;
}

const STATUS_LABELS: Record<string, string> = {
  created: "ایجادشده",
  ingesting: "در پردازش",
  ready: "منتشرشده",
  failed: "ناموفق",
  needs_verification: "نیازمند راستی‌آزمایی",
  unknown: "نامشخص",
  active: "فعال",
  stopped_development: "توقف توسعه",
  redesigned: "بازطراحی",
  expired: "منقضی",
  inactive: "غیرفعال",
  confirmed: "قطعی",
  experimental: "اجرای آزمایشی",
  regional_pilot: "اجرای منطقه‌ای",
  general: "عمومی",
  girls: "ویژهٔ دختران",
  boys: "ویژهٔ پسران",
  religious_minority: "اقلیت‌های دینی",
  student_book: "کتاب اصلی",
  workbook: "کتاب کار",
  supplementary: "مکمل",
  periodical: "دوره‌ای",
  teacher_guide: "راهنمای معلم",
};

function cell(row: Row, col: { name: string; kind?: string }): string {
  const value = row[col.name];
  if (value === null || value === undefined || value === "") return "—";
  if (col.kind === "bool") return value ? "✔" : "—";
  if (typeof value === "string" && STATUS_LABELS[value]) return STATUS_LABELS[value];
  return String(value);
}

export type AdminCatalogManagerProps = {
  /** Entity key from ADMIN_CATALOG_ENTITIES, or a view key from ADMIN_CATALOG_VIEWS. */
  kind: string;
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
};

/**
 * Generic AJAX manager for one education-catalog entity: search, filters,
 * sorting, pagination, create/edit forms, dependency-aware delete confirm,
 * archive/restore, edition PDF upload and academic-year structure copy.
 * No full page reloads; filters and the current page survive every action.
 */
export default function AdminCatalogManager({ kind, authHeaders, onUnauthorized }: AdminCatalogManagerProps) {
  const config: AdminCatalogEntityConfig = useMemo(
    () => ADMIN_CATALOG_VIEWS[kind] ?? ADMIN_CATALOG_ENTITIES[kind],
    [kind]
  );
  const apiEntity = ("baseEntity" in (ADMIN_CATALOG_VIEWS[kind] ?? {}) ? (ADMIN_CATALOG_VIEWS[kind] as { baseEntity: string }).baseEntity : kind);

  // Phase 06 URL contract: page/q/sort/direction live in the URL of every
  // /admin/education/* page — read back on mount and written on change, so a
  // refresh or a shared link keeps the exact working context of the manager.
  const urlParams = useMemo(() => {
    try {
      return new URLSearchParams(window.location.search);
    } catch {
      return new URLSearchParams();
    }
  }, []);
  const urlPage = Math.max(1, Number.parseInt(urlParams.get("page") ?? "1", 10) || 1);
  const urlSort = urlParams.get("sort") ?? "";
  const urlDirection = urlParams.get("direction") === "desc" ? "desc" : "asc";

  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(urlPage);
  const [pageSize] = useState(25);
  const [q, setQ] = useState(urlParams.get("q") ?? "");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState(
    urlSort && (config.sortable.includes(urlSort) || urlSort === "id") ? urlSort : config.sortable[0] ?? "id"
  );
  const [direction, setDirection] = useState<"asc" | "desc">(urlDirection);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [editing, setEditing] = useState<Row | null>(null); // null=closed, {}=create
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [deps, setDeps] = useState<Record<string, number> | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [fkOptions, setFkOptions] = useState<Record<string, { value: string; label: string }[]>>({});
  const [yearCopySource, setYearCopySource] = useState("");
  const [pdfFile, setPdfFile] = useState<File | null>(null);

  // FK options for select fields
  useEffect(() => {
    const froms = new Set<string>();
    config.fields.forEach((f) => f.from && froms.add(f.from));
    config.filters.forEach((f) => f.from && froms.add(f.from));
    void (async () => {
      const next: Record<string, { value: string; label: string }[]> = {};
      for (const from of froms) {
        try {
          const res = await fetch(`/api/v1/admin/catalog/${from}?page_size=200`, { headers: authHeaders });
          if (res.status === 401) return onUnauthorized();
          const payload = (await res.json()) as ListResponse;
          next[from] = (payload.items ?? []).map((item) => ({
            value: String(item.id),
            label:
              String(item.title ?? item.title_fa ?? item.code ?? item.number ?? `#${item.id}`) +
              (item.ground_title ? ` (${item.ground_title})` : ""),
          }));
        } catch {
          next[from] = [];
        }
      }
      setFkOptions(next);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), sort, direction });
      if (q.trim()) params.set("q", q.trim());
      Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
      const res = await fetch(`/api/v1/admin/catalog/${apiEntity}?${params.toString()}`, { headers: authHeaders });
      if (res.status === 401) return onUnauthorized();
      const payload = (await res.json()) as ListResponse | { detail: string };
      if (!res.ok || !("items" in payload)) {
        setError(detail(payload, "بارگذاری فهرست ناموفق بود."));
        return;
      }
      setRows(payload.items);
      setTotal(payload.total);
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiEntity, page, pageSize, q, filters, sort, direction]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  // Mirror the working context back into the URL (best-effort, no history spam).
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("page", String(page));
      if (q.trim()) params.set("q", q.trim());
      else params.delete("q");
      if (sort !== (config.sortable[0] ?? "id")) params.set("sort", sort);
      else params.delete("sort");
      if (direction !== "asc") params.set("direction", direction);
      else params.delete("direction");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch {
      // history is best-effort
    }
  }, [page, q, sort, direction, config]);

  const openCreate = () => {
    const initial: Record<string, string | boolean> = { ...("presetFilters" in config ? (config as { presetFilters: Record<string, string> }).presetFilters : {}) };
    config.fields.forEach((f) => {
      if (!(f.name in initial)) initial[f.name] = f.type === "bool" ? true : "";
    });
    setDraft(initial);
    setEditing({});
    setError(null);
    setNotice(null);
  };

  const openEdit = (row: Row) => {
    const initial: Record<string, string | boolean> = {};
    config.fields.forEach((f) => {
      const value = row[f.name];
      if (f.type === "bool") initial[f.name] = Boolean(value);
      else initial[f.name] = value === null || value === undefined ? "" : String(value);
    });
    setDraft(initial);
    setEditing(row);
    setError(null);
    setNotice(null);
  };

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      config.fields.forEach((f) => {
        const value = draft[f.name];
        if (f.type === "bool") body[f.name] = Boolean(value);
        else if (f.type === "number") body[f.name] = value === "" ? null : Number(value);
        else body[f.name] = value === "" ? null : value;
      });
      const isCreate = !editing || editing.id === undefined;
      const url = isCreate
        ? `/api/v1/admin/catalog/${apiEntity}`
        : `/api/v1/admin/catalog/${apiEntity}/${(editing as Row).id}`;
      const res = await fetch(url, {
        method: isCreate ? "POST" : "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify(body),
      });
      if (res.status === 401) return onUnauthorized();
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(detail(payload, "ذخیره انجام نشد."));
        return;
      }
      setEditing(null);
      setNotice("تغییرات ذخیره شد و در کل درسیار اعمال می‌شود.");
      await load();
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setBusy(false);
    }
  };

  const askDelete = async (row: Row) => {
    setDeleting(row);
    try {
      const res = await fetch(`/api/v1/admin/catalog/${apiEntity}/${row.id}/dependencies`, { headers: authHeaders });
      if (res.status === 401) return onUnauthorized();
      const payload = (await res.json()) as { dependencies: Record<string, number> };
      setDeps(payload.dependencies ?? {});
    } catch {
      setDeps({});
    }
  };

  const confirmDelete = async () => {
    if (!deleting || busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/admin/catalog/${apiEntity}/${deleting.id}`, { method: "DELETE", headers: authHeaders });
      if (res.status === 401) return onUnauthorized();
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(detail(payload, "حذف انجام نشد."));
        setDeleting(null);
        return;
      }
      setNotice("رکورد حذف شد.");
      setDeleting(null);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const toggleArchive = async (row: Row) => {
    const archived = config.canArchive && (
      config.entity === "textbooks" ? Boolean(row.archived_at) : row.is_active === false
    );
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/admin/catalog/${apiEntity}/${row.id}/${archived ? "restore" : "archive"}`, {
        method: "POST",
        headers: authHeaders,
      });
      if (res.status === 401) return onUnauthorized();
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        setError(detail(payload, "عملیات آرشیو انجام نشد."));
        return;
      }
      setNotice(archived ? "رکورد بازیابی شد." : "رکورد آرشیو/غیرفعال شد — انتخاب‌های جدید متوقف می‌شود و تاریخچه محفوظ می‌ماند.");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const uploadPdf = async (row: Row) => {
    if (!pdfFile || busy) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", pdfFile);
      const res = await fetch(`/api/v1/admin/catalog/editions/${row.id}/pdf`, {
        method: "POST",
        headers: authHeaders,
        body: form,
      });
      if (res.status === 401) return onUnauthorized();
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(detail(payload, "بارگذاری PDF انجام نشد."));
        return;
      }
      setNotice(`PDF ذخیره شد (SHA256: ${String((payload as { sha256?: string }).sha256 ?? "").slice(0, 12)}…) — انتشار با خط پردازش انجام می‌شود.`);
      setPdfFile(null);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const copyYear = async (row: Row) => {
    if (!yearCopySource || busy) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/admin/catalog/academic-years/${row.id}/copy-structure`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ source_year_id: Number(yearCopySource) }),
      });
      if (res.status === 401) return onUnauthorized();
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setError(detail(payload, "کپی ساختار انجام نشد."));
        return;
      }
      const stats = (payload as { copied?: { program_availability?: number; links?: number } }).copied;
      setNotice(`کپی اولیه انجام شد: ${stats?.program_availability ?? 0} وضعیت اعتبار و ${stats?.links ?? 0} ارتباط کتاب. سال مبدأ دست‌نخورده ماند.`);
    } finally {
      setBusy(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <section className="admin-card" dir="rtl">
      <div className="card-heading">
        <div>
          <h2>{config.title}</h2>
          <p className="admin-muted">{config.description}</p>
        </div>
        <div className="report-head-actions">
          <button type="button" className="outline-button" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={14} /> بروزرسانی
          </button>
          <button type="button" className="primary-button" onClick={openCreate}>
            <Plus size={15} /> افزودن
          </button>
        </div>
      </div>

      <div className="admin-catalog-toolbar">
        <label className="admin-catalog-search">
          <Search size={14} />
          <input
            value={q}
            onChange={(event) => {
              setQ(event.target.value);
              setPage(1);
            }}
            placeholder="جست‌وجوی سریع…"
          />
        </label>
        {config.filters.map((filter) => (
          <select
            key={filter.name}
            value={filters[filter.name] ?? ""}
            onChange={(event) => {
              setFilters((prev) => ({ ...prev, [filter.name]: event.target.value }));
              setPage(1);
            }}
          >
            <option value="">{filter.label}: همه</option>
            {(filter.options ?? fkOptions[filter.from ?? ""] ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ))}
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          {config.sortable.map((field) => (
            <option key={field} value={field}>
              مرتب‌سازی: {field}
            </option>
          ))}
        </select>
        <select value={direction} onChange={(event) => setDirection(event.target.value as "asc" | "desc")}>
          <option value="asc">صعودی</option>
          <option value="desc">نزولی</option>
        </select>
      </div>

      {notice && <div className="success-note" role="status">{notice}</div>}
      {error && (
        <div className="inline-error" role="alert">
          <TriangleAlert size={14} /> {error}
        </div>
      )}

      {loading ? (
        <div className="admin-catalog-loading" role="status">
          <LoaderCircle className="spin" size={16} /> در حال بارگذاری…
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                {config.columns.map((col) => (
                  <th key={col.name}>{col.label}</th>
                ))}
                <th>عملیات</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row.id)}>
                  {config.columns.map((col) => (
                    <td key={col.name}>{cell(row, col)}</td>
                  ))}
                  <td>
                    <div className="admin-catalog-actions">
                      <button type="button" className="icon-button" aria-label="ویرایش" onClick={() => openEdit(row)}>
                        <Pencil size={14} />
                      </button>
                      {config.canArchive && (
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={config.entity === "textbooks" && row.archived_at ? "بازیابی" : "آرشیو"}
                          onClick={() => void toggleArchive(row)}
                          disabled={busy}
                        >
                          {config.entity === "textbooks" && row.archived_at ? <ArchiveRestore size={14} /> : <Archive size={14} />}
                        </button>
                      )}
                      <button
                        type="button"
                        className="icon-button danger"
                        aria-label="حذف"
                        onClick={() => void askDelete(row)}
                        disabled={busy}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={config.columns.length + 1} className="admin-muted">
                    رکوردی یافت نشد.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="admin-catalog-pagination">
        <button type="button" className="outline-button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
          قبلی
        </button>
        <span>
          صفحهٔ {page} از {totalPages} — {total} رکورد
        </span>
        <button
          type="button"
          className="outline-button"
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
        >
          بعدی
        </button>
      </div>

      {editing && (
        <div className="admin-catalog-modal" role="dialog" aria-modal="true">
          <div className="admin-catalog-modal-body">
            <div className="card-heading">
              <h3>{editing.id !== undefined ? "ویرایش رکورد" : "افزودن رکورد جدید"}</h3>
              <button type="button" className="icon-button" aria-label="بستن" onClick={() => setEditing(null)}>
                <X size={16} />
              </button>
            </div>
            <div className="admin-catalog-form">
              {config.fields.map((field: AdminCatalogField) => (
                <label className="form-field" key={field.name}>
                  <span>
                    {field.label}
                    {field.required ? " *" : ""}
                  </span>
                  {field.type === "bool" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(draft[field.name])}
                      onChange={(event) => setDraft((prev) => ({ ...prev, [field.name]: event.target.checked }))}
                    />
                  ) : field.type === "select" ? (
                    <select
                      value={String(draft[field.name] ?? "")}
                      onChange={(event) => setDraft((prev) => ({ ...prev, [field.name]: event.target.value }))}
                    >
                      <option value="">— انتخاب کنید —</option>
                      {(field.options ?? fkOptions[field.from ?? ""] ?? []).map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  ) : field.type === "textarea" ? (
                    <textarea
                      rows={3}
                      value={String(draft[field.name] ?? "")}
                      onChange={(event) => setDraft((prev) => ({ ...prev, [field.name]: event.target.value }))}
                    />
                  ) : (
                    <input
                      type={field.type === "number" ? "number" : "text"}
                      min={field.min}
                      max={field.max}
                      value={String(draft[field.name] ?? "")}
                      onChange={(event) => setDraft((prev) => ({ ...prev, [field.name]: event.target.value }))}
                    />
                  )}
                </label>
              ))}
            </div>
            {error && (
              <div className="inline-error" role="alert">
                <TriangleAlert size={14} /> {error}
              </div>
            )}
            <div className="admin-catalog-modal-actions">
              <button type="button" className="primary-button" onClick={() => void submit()} disabled={busy}>
                {busy ? <LoaderCircle className="spin" size={15} /> : null} ذخیره
              </button>
              <button type="button" className="outline-button" onClick={() => setEditing(null)}>
                انصراف
              </button>
            </div>
          </div>
        </div>
      )}

      {deleting && (
        <div className="admin-catalog-modal" role="alertdialog" aria-modal="true">
          <div className="admin-catalog-modal-body">
            <h3>تأیید حذف</h3>
            <p>
              این {config.title.replace("مدیریت ", "")} با شناسهٔ {String(deleting.id)} حذف دائمی می‌شود.
            </p>
            {deps && (
              <ul className="admin-catalog-deps">
                {Object.entries(deps)
                  .filter(([, count]) => count > 0)
                  .map(([label, count]) => (
                    <li key={label}>
                      {label}: {count}
                    </li>
                  ))}
                {Object.values(deps).every((count) => count === 0) && (
                  <li>هیچ وابستگی‌ای ندارد — حذف دائمی امن است.</li>
                )}
              </ul>
            )}
            <div className="admin-catalog-modal-actions">
              <button type="button" className="primary-button danger" onClick={() => void confirmDelete()} disabled={busy}>
                حذف دائمی
              </button>
              <button type="button" className="outline-button" onClick={() => setDeleting(null)}>
                انصراف و آرشیو به‌جای حذف
              </button>
            </div>
          </div>
        </div>
      )}

      {editing && editing.id !== undefined && config.supportsPdfUpload && (
        <div className="admin-catalog-modal" role="dialog" aria-modal="true">
          <div className="admin-catalog-modal-body">
            <h3>بارگذاری/جایگزینی PDF نسخهٔ {String(editing.id)}</h3>
            <input type="file" accept="application/pdf" onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)} />
            <p className="admin-muted">
              انتشار خودکار حفظ می‌شود: PDF ذخیره و SHA256 ثبت می‌گردد اما وضعیت ready فقط توسط خط پردازش تنظیم می‌شود.
            </p>
            <div className="admin-catalog-modal-actions">
              <button type="button" className="primary-button" onClick={() => void uploadPdf(editing)} disabled={busy || !pdfFile}>
                <FileUp size={15} /> بارگذاری
              </button>
              <button type="button" className="outline-button" onClick={() => setPdfFile(null)}>
                انصراف
              </button>
            </div>
          </div>
        </div>
      )}

      {config.supportsYearCopy && editing && editing.id !== undefined && (
        <div className="admin-catalog-modal" role="dialog" aria-modal="true">
          <div className="admin-catalog-modal-body">
            <h3>کپی اولیهٔ ساختار سال قبلی به «{String(editing.code ?? editing.id)}»</h3>
            <label className="form-field">
              <span>سال مبدأ</span>
              <select value={yearCopySource} onChange={(event) => setYearCopySource(event.target.value)}>
                <option value="">— انتخاب سال مبدأ —</option>
                {(fkOptions["academic-years"] ?? [])
                  .filter((option) => option.value !== String(editing.id))
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
            </label>
            <p className="admin-muted">
              وضعیت اعتبار رشته‌ها و ارتباط کتاب‌ها کپی می‌شود؛ رکوردهای سال مبدأ هیچ تغییری نمی‌کنند و کپی تکراری ایجاد نمی‌شود.
            </p>
            <div className="admin-catalog-modal-actions">
              <button type="button" className="primary-button" onClick={() => void copyYear(editing)} disabled={busy || !yearCopySource}>
                کپی ساختار
              </button>
              <button type="button" className="outline-button" onClick={() => setYearCopySource("")}>
                انصراف
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
