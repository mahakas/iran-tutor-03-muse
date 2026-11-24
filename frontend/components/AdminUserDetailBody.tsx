"use client";

import AdminGate from "@/components/AdminGate";
import AdminUserDetailPanel from "@/components/AdminUserDetailPanel";

/** `/admin/users/[id]`: Memory Inspector, deleted chats, and concept-link management. */
export default function AdminUserDetailBody({ userId }: { userId: string }) {
  return (
    <AdminGate
      title="پروندهٔ یادگیرنده"
      description="حافظهٔ L1/L2/L3 هر کاربر را ببین و ویرایش کن؛ گفت‌وگوهای حذف‌شده و پیوندهای مفهومی بین پایه‌ها را مدیریت کن."
    >
      {({ authHeaders, onUnauthorized }) => (
        <AdminUserDetailPanel userId={userId} authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
      )}
    </AdminGate>
  );
}
