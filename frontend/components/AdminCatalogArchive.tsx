"use client";

import { useCallback, useEffect, useState } from "react";
import { ArchiveRestore, LoaderCircle, RefreshCw } from "lucide-react";
import { ADMIN_CATALOG_ENTITIES } from "@/lib/adminCatalog";

type ArchivedRow = Record<string, unknown> & { entity: string };

/** Cross-entity archive view: inactive/archived records with one-click restore. */
export default function AdminCatalogArchive({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [rows, setRows] = useState<ArchivedRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/v1/admin/catalog/archive", { headers: authHeaders });
      if (res.status === 401) return onUnauthorized();
      const payload = (await res.json()) as { items?: ArchivedRow[] };
      setRows(payload.items ?? []);
    } catch {
      setError("ارتباط با سرور برقرار نشد.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const restore = async (row: ArchivedRow) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/admin/catalog/${row.entity}/${row.id}/restore`, {
        method: "POST",
        headers: authHeaders,
      });
      if (res.status === 401) return onUnauthorized();
      if (!res.ok) {
        const payload = await res.json().catch(() => null);
        setError(String((payload as { detail?: string })?.detail ?? "بازیابی انجام نشد."));
        return;
      }
      setNotice("رکورد بازیابی شد و در انتخاب‌گر دانش‌آموز دوباره در دسترس است.");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const titleFor = (entity: string) => ADMIN_CATALOG_ENTITIES[entity]?.title ?? entity;

  return (
    <section className="admin-card" dir="rtl">
      <div className="card-heading">
        <div>
          <h2>آرشیو اطلاعات حذف‌شده یا غیرفعال</h2>
          <p className="admin-muted">
            رکوردهای غیرفعال/آرشیوشده — تاریخچهٔ دانش‌آموزان دست‌نخورده باقی می‌ماند و بازیابی فقط انتخاب‌های جدید را باز می‌کند.
          </p>
        </div>
        <button type="button" className="outline-button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={14} /> بروزرسانی
        </button>
      </div>
      {notice && <div className="success-note" role="status">{notice}</div>}
      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? (
        <div className="admin-catalog-loading" role="status">
          <LoaderCircle className="spin" size={16} /> در حال بارگذاری…
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>موجودیت</th>
                <th>عنوان/کد</th>
                <th>شناسه</th>
                <th>عملیات</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.entity}-${row.id}`}>
                  <td>{titleFor(String(row.entity))}</td>
                  <td>
                    {String(row.title_fa ?? row.title ?? row.code ?? row.number ?? "—")}
                  </td>
                  <td>{String(row.id)}</td>
                  <td>
                    <button type="button" className="outline-button" onClick={() => void restore(row)} disabled={busy}>
                      <ArchiveRestore size={14} /> بازیابی
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="admin-muted">
                    آرشیو خالی است — هیچ رکورد غیرفعالی وجود ندارد.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
