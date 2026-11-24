"use client";

import AdminGate from "@/components/AdminGate";
import AdminCatalogArchive from "@/components/AdminCatalogArchive";

export default function AdminCatalogArchiveBody() {
  return (
    <AdminGate
      title="آرشیو اطلاعات حذف‌شده یا غیرفعال"
      description="بازیابی رکوردهای غیرفعال کاتالوگ آموزشی بدون آسیب به تاریخچه."
    >
      {({ authHeaders, onUnauthorized }) => (
        <main className="admin-main admin-education-page">
          <AdminCatalogArchive authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
        </main>
      )}
    </AdminGate>
  );
}
