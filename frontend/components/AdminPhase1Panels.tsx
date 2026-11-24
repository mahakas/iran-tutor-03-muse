"use client";

import AdminGate from "@/components/AdminGate";
import AdminObservabilityPanel from "@/components/AdminObservabilityPanel";
import AdminProvidersPanel from "@/components/AdminProvidersPanel";
import AdminRolesQuotasPanel from "@/components/AdminRolesQuotasPanel";

export function AdminProvidersBody() {
  return (
    <AdminGate
      title="ارائه‌دهنده‌ها و مسیر مدل‌ها"
      description="مدیریت متمرکز ارائه‌دهنده‌های هوش مصنوعی، کلیدهای رمزنگاری‌شده و مدل هر قابلیت."
    >
      {({ authHeaders, onUnauthorized }) => (
        <AdminProvidersPanel authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
      )}
    </AdminGate>
  );
}

export function AdminObservabilityBody() {
  return (
    <AdminGate
      title="مرکز شفافیت کامل (Glass-Box)"
      description="هر فراخوانی هوش مصنوعی، پرامپت، پاسخ، منابع کتاب، توکن، هزینه و تأخیر — همه قابل بازبینی."
    >
      {({ authHeaders, onUnauthorized }) => (
        <AdminObservabilityPanel authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
      )}
    </AdminGate>
  );
}

export function AdminRolesBody() {
  return (
    <AdminGate
      title="کاربران، نقش‌ها و سهمیه‌ها"
      description="مدیریت نقش مدیر/معلم/دانش‌آموز/ولی، پایه و رشتهٔ تحصیلی و سیاست سهمیه و نرخ."
    >
      {({ authHeaders, onUnauthorized }) => (
        <AdminRolesQuotasPanel authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
      )}
    </AdminGate>
  );
}
