import type { Metadata } from "next";
import { AdminRolesBody } from "@/components/AdminPhase1Panels";

export const metadata: Metadata = {
  title: "نقش‌ها و سهمیه‌ها | درسیار",
  robots: { index: false, follow: false },
};

export default function AdminRolesPage() {
  return <AdminRolesBody />;
}
