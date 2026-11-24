import type { Metadata } from "next";
import AdminCatalogPage from "@/components/AdminCatalogPage";

export const metadata: Metadata = {
  title: "مدیریت پایه‌ها و کلاس‌ها | درسیار",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AdminCatalogPage kind="grades" />;
}
