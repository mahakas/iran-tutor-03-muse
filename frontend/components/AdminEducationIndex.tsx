"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BookOpen, ChevronLeft } from "lucide-react";
import AdminGate from "@/components/AdminGate";
import { ADMIN_CATALOG_MODULES } from "@/lib/adminCatalog";

/** /admin/education — index of every education-catalog management module. */
export default function AdminEducationIndex() {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        // AdminGate below enforces auth; the fetch here is best-effort for counts.
        const res = await fetch("/api/v1/admin/catalog/overview");
        if (!res.ok || cancelled) return;
        const payload = (await res.json()) as { counts?: Record<string, number> };
        if (!cancelled && payload.counts) setCounts(payload.counts);
      } catch {
        /* counts are decorative */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AdminGate
      title="مدیریت نظام آموزشی و کاتالوگ درسی"
      description="مدیریت کامل دوره‌ها، پایه‌ها، شاخه‌ها، زمینه‌ها، رشته‌ها، درس‌ها، کتاب‌ها، نسخه‌ها و سال‌های تحصیلی — با حفظ تاریخچه و ثبت ممیزی."
    >
      {() => (
        <main className="admin-main admin-education-page" dir="rtl">
          <section className="admin-card">
            <div className="card-heading">
              <div>
                <h2>
                  <BookOpen size={18} /> مدیریت نظام آموزشی و کاتالوگ درسی
                </h2>
                <p className="admin-muted">
                  هر ماژول صفحه و لینک مستقل دارد؛ تغییرات بلافاصله در دیتابیس و انتخاب‌گر دانش‌آموز اعمال می‌شود.
                </p>
              </div>
            </div>
            <div className="admin-education-grid">
              {ADMIN_CATALOG_MODULES.map((module) => (
                <Link key={module.href} href={module.href} className="admin-education-card">
                  <span>{module.title}</span>
                  {counts && counts[module.kind] !== undefined && (
                    <small>{counts[module.kind]} رکورد</small>
                  )}
                  <ChevronLeft size={16} />
                </Link>
              ))}
            </div>
          </section>
        </main>
      )}
    </AdminGate>
  );
}
