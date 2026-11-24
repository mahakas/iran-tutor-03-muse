import type { Metadata } from "next";
import AdminEducationIndex from "@/components/AdminEducationIndex";

export const metadata: Metadata = {
  title: "مدیریت نظام آموزشی | درسیار",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AdminEducationIndex />;
}
