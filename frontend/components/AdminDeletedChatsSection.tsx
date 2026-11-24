"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

type DeletedChatRow = {
  id: string;
  user_id: string;
  phone_number: string | null;
  title: string;
  book_title: string | null;
  mode: string;
  message_count: number;
  deleted_at: string | null;
};

type DeletedPayload = { deleted_total: number; items: DeletedChatRow[] };

/** Monitoring: soft-deleted (Recycle Bin) chats stay visible to admins here. */
export default function AdminDeletedChatsSection({
  authHeaders,
  onUnauthorized,
}: {
  authHeaders: Record<string, string>;
  onUnauthorized: () => void;
}) {
  const [data, setData] = useState<DeletedPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const response = await fetch("/api/v1/admin/chat-sessions?status=deleted&limit=50", {
          cache: "no-store",
          credentials: "same-origin",
          headers: authHeaders,
        });
        if (response.status === 401 || response.status === 403) return onUnauthorized();
        if (!response.ok) throw new Error("load");
        const payload = (await response.json()) as DeletedPayload;
        if (active) setData(payload);
      } catch {
        if (active) setError("فهرست گفت‌وگوهای حذف‌شده بارگذاری نشد.");
      }
    })();
    return () => {
      active = false;
    };
  }, [authHeaders, onUnauthorized]);

  return (
    <section className="admin-card">
      <div className="admin-card-head">
        <h3>
          <Trash2 size={15} /> گفت‌وگوهای سطل بازیافت (حذف نرم)
        </h3>
        <span className="admin-muted">
          مجموع: {(data?.deleted_total ?? 0).toLocaleString("fa-IR")}
        </span>
      </div>
      {error && <div className="inline-error">{error}</div>}
      {!error && data && data.items.length === 0 && (
        <p className="admin-muted">گفت‌وگوی حذف‌شده‌ای وجود ندارد.</p>
      )}
      {data && data.items.length > 0 && (
        <div className="fc-admin-table-wrap">
          <table className="fc-admin-table">
            <thead>
              <tr>
                <th>عنوان</th>
                <th>کاربر</th>
                <th>کتاب</th>
                <th>پیام‌ها</th>
                <th>زمان حذف</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((chat) => (
                <tr key={chat.id}>
                  <td>{chat.title || "بدون عنوان"}</td>
                  <td>
                    <a href={`/admin/users/${chat.user_id}`} dir="ltr">
                      {chat.phone_number ?? chat.user_id}
                    </a>
                  </td>
                  <td>{chat.book_title ?? "—"}</td>
                  <td>{chat.message_count.toLocaleString("fa-IR")}</td>
                  <td dir="ltr">{chat.deleted_at ? new Date(chat.deleted_at).toLocaleString("fa-IR") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
