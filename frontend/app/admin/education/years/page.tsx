import type { Metadata } from "next";
import AdminCatalogPage from "@/components/AdminCatalogPage";

export const metadata: Metadata = {
  title: "مدیریت سال‌های تحصیلی | درسیار",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AdminCatalogPage kind="academic-years" />;
}
